#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
thsr_watcher.py
================
監控台灣高鐵官網「最新消息 / 疏運日程表 / 疏運期間對號座銷售資訊」等公開頁面，
偵測到頁面內容變動或出現指定關鍵字（例如「加開」「疏運」「中秋」）時，
立即透過 Telegram Bot 發送通知。

★ 重要說明 ★
本程式「只做監控與通知」，不會、也不建議拿去自動化訂票（irs.thsrc.com.tw 的
查詢/訂票流程有圖形驗證碼，是官方刻意設計來防止機器人搶票的機制，自動繞過
它等於在做搶票外掛，對其他排隊的乘客不公平，也可能違反高鐵使用條款）。
收到通知後，請自己手動打開訂票網站完成查詢與付款。

技術說明：高鐵官網的內容頁面是 JS 動態渲染的（不是單純的靜態 HTML），
所以這裡改用 Playwright 開一個無頭瀏覽器把頁面完整渲染後再抓文字內容。

使用方式：
    python3 thsr_watcher.py            # 常駐執行，每隔 CHECK_INTERVAL_SECONDS 檢查一次
    python3 thsr_watcher.py --once     # 只檢查一次就結束（適合排 cron / GitHub Actions）

首次使用前，除了 pip install，還需要額外安裝瀏覽器核心（只需一次）：
    playwright install chromium
    # 若在 Linux 伺服器/GitHub Actions 上，建議：
    playwright install --with-deps chromium
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# ======================================================================
# 設定區（改這裡就好）
# ======================================================================

CONFIG = {
    # --- Telegram 設定 ---
    # 1. 跟 @BotFather 對話，輸入 /newbot，依指示建立 bot，拿到 Token
    # 2. 跟你剛建立的 bot 隨便說一句話（例如 /start）
    # 3. 瀏覽器打開：https://api.telegram.org/bot<你的TOKEN>/getUpdates
    #    在回傳的 JSON 裡找 "chat":{"id": 這個數字就是 CHAT_ID
    "TELEGRAM_BOT_TOKEN": os.environ.get("THSR_TG_TOKEN", "請填入你的 Bot Token"),
    "TELEGRAM_CHAT_ID": os.environ.get("THSR_TG_CHAT_ID", "請填入你的 Chat ID"),

    # --- 檢查頻率（秒）。太短容易被網站擋，建議不要低於 60 秒 ---
    "CHECK_INTERVAL_SECONDS": 180,

    # --- 要監控的官方公開頁面 ---
    "URLS": {
        "最新消息": "https://www.thsrc.com.tw/ArticleContent/6f0648a4-2e78-4a57-b669-44acd8e2daea",
        "疏運日程表": "https://www.thsrc.com.tw/ArticleContent/60dbfb79-ac20-4280-8ffb-b09e7c94f043",
        "疏運期間對號座銷售資訊": "https://www.thsrc.com.tw/ArticleContent/89c627b2-e4a4-4b6b-9c9b-150197fdc1db",
        "對號座訂位開放時程": "https://www.thsrc.com.tw/ArticleContent/d4b49835-e43b-4be8-bc4d-0a1fe74143ff",
    },

    # --- 你特別關心的關鍵字（新內容命中時會在通知裡特別標註⭐） ---
    "KEYWORDS": ["中秋", "教師節", "加開", "疏運", "開賣", "開放訂位", "熱銷"],

    # --- 狀態存檔位置（記錄上次抓到的內容，重開程式不會重複通知） ---
    "STATE_FILE": "thsr_watcher_state.json",

    # --- 對外偽裝成一般瀏覽器，降低被擋機率 ---
    "USER_AGENT": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),

    "REQUEST_TIMEOUT": 15,       # Telegram API 用（秒）
    "PAGE_LOAD_TIMEOUT_MS": 25000,  # Playwright 頁面載入逾時（毫秒）
    "EXTRA_WAIT_MS": 2000,          # 頁面載入完後，額外多等幾秒讓 JS 把內容渲染完

    # --- 假期開賣日提醒清單 ---
    # 高鐵通常會在假期前 1~2 個月，於「疏運日程表」「疏運期間對號座銷售資訊」
    # 這兩個頁面公布正確的開賣日期/時間。上面的頁面監控功能偵測到這兩頁有更新時，
    # 記得回去看一下公布了什麼新日期，再手動把正確的日期填進下面清單即可，
    # 之後這個功能就會自動在開賣前幫你倒數提醒。
    #
    # 格式說明：
    #   name              - 這個假期的名稱，通知裡會顯示
    #   open_date         - 開賣日期，格式 YYYY-MM-DD
    #   open_time         - 開賣時間，格式 HH:MM（24小時制），不確定可以先留空字串
    #   remind_days_before - 開賣前幾天提醒你，可以填多個，0 代表「開賣當天」也提醒
    #
    # 下面先放一組範例（日期是隨便寫的，請務必改成官方公告的正確日期後再使用！）
    "HOLIDAY_TICKET_OPENINGS": [
        {
            "name": "範例：2027年春節疏運",
            "open_date": "2026-12-25",
            "open_time": "07:00",
            "remind_days_before": [3, 1, 0],
        },
    ],

    # --- 自動從「疏運日程表」頁面解析出來的假期日期，要提前幾天提醒 ---
    # （不用手動填假期進 HOLIDAY_TICKET_OPENINGS 了，只要那個表格格式沒大改，
    #   程式每次檢查都會自動抓出目前公告的所有假期日期並自動加提醒）
    "AUTO_REMIND_DAYS_BEFORE": [3, 1, 0],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("thsr_watcher")


# ======================================================================
# 核心邏輯
# ======================================================================

def load_state(path: str) -> dict:
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("讀取狀態檔失敗，將視為全新開始：%s", e)
    return {}


def save_state(path: str, state: dict) -> None:
    Path(path).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_page_text(url: str, pw_page) -> str:
    """用 Playwright 開真的瀏覽器把頁面 JS 跑完，再抓可見文字。"""
    pw_page.goto(
        url,
        timeout=CONFIG["PAGE_LOAD_TIMEOUT_MS"],
        wait_until="networkidle",
    )
    # 有些內容是網路閒置後才用前端邏輯塞進 DOM 的，多等一下比較保險
    pw_page.wait_for_timeout(CONFIG["EXTRA_WAIT_MS"])

    text = pw_page.inner_text("body")

    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    result = "\n".join(lines)

    preview = result[:300].replace("\n", " | ") if result else "(空白，什麼都沒抓到)"
    log.info("[debug] %s 內容長度=%d 預覽（前300字）: %s", url, len(result), preview)

    return result


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_keyword_hits(text: str, keywords) -> list:
    hits = []
    for kw in keywords:
        if kw in text:
            hits.append(kw)
    return hits


def diff_snippet(old_text: str, new_text: str, context_chars: int = 60) -> str:
    """簡易差異摘要：找出新內容裡舊內容沒有的行，回傳前幾行給人看。"""
    old_lines = set(old_text.splitlines())
    new_lines = new_text.splitlines()
    added = [ln for ln in new_lines if ln not in old_lines]
    if not added:
        return "(偵測到內容變動，但無法擷取具體差異，建議直接開頁面確認)"
    snippet = "\n".join(added[:8])
    if len(snippet) > 800:
        snippet = snippet[:800] + " …(以下省略)"
    return snippet


def send_telegram_message(text: str) -> bool:
    token = CONFIG["TELEGRAM_BOT_TOKEN"]
    chat_id = CONFIG["TELEGRAM_CHAT_ID"]
    if not token or "請填入" in token or not chat_id or "請填入" in str(chat_id):
        log.warning("Telegram Token / Chat ID 尚未設定，改用終端機印出通知：")
        print("\n" + "=" * 60)
        print(text)
        print("=" * 60 + "\n")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": False},
            timeout=CONFIG["REQUEST_TIMEOUT"],
        )
        if r.status_code == 200:
            log.info("Telegram 通知已送出")
            return True
        else:
            log.error("Telegram 傳送失敗：%s %s", r.status_code, r.text)
            return False
    except requests.RequestException as e:
        log.error("Telegram 傳送發生例外：%s", e)
        return False


def parse_holiday_schedule(text: str) -> list:
    """從「疏運日程表」頁面的文字內容中，自動抓出每個假期的：
    假期名稱、疏運期間（起訖）、開放預售日期。

    實際觀察到的格式是「一行一個假期」，欄位用 Tab 字元分隔，日期用全形括號
    標註星期、期間中間用全形波浪號分隔，例如：
        春節\\t2026/02/13（五）～2026/02/23（一）\\t2026/01/16（五）

    如果高鐵改版排版，這裡可能會抓不到東西（回傳空清單），
    但既有的「頁面內容變動偵測」通知仍會照常運作，讓你自己回來看發生什麼事。
    """
    line_re = re.compile(
        r"^(?P<name>\S+?)\t"
        r"(?P<start>\d{4}/\d{2}/\d{2})[（(][一二三四五六日][）)]\s*[~～]\s*"
        r"(?P<end>\d{4}/\d{2}/\d{2})[（(][一二三四五六日][）)]\t"
        r"(?P<presale>\d{4}/\d{2}/\d{2})[（(][一二三四五六日][）)]\s*$"
    )

    results = []
    for raw_line in text.splitlines():
        line = raw_line.strip("\n\r")
        m = line_re.match(line)
        if m:
            results.append(
                {
                    "name": m.group("name"),
                    "period_start": m.group("start"),
                    "period_end": m.group("end"),
                    "presale_date": m.group("presale"),
                }
            )

    return results


def get_all_holiday_openings(state: dict) -> list:
    """合併「手動設定」跟「自動從疏運日程表解析出來」的假期開賣日清單。"""
    merged = list(CONFIG.get("HOLIDAY_TICKET_OPENINGS", []))

    for item in state.get("auto_holiday_schedule", []):
        merged.append(
            {
                "name": f"{item['name']}（自動偵測）",
                "open_date": item["presale_date"].replace("/", "-"),
                "open_time": "",
                "remind_days_before": CONFIG.get("AUTO_REMIND_DAYS_BEFORE", [3, 1, 0]),
            }
        )

    return merged


def check_holiday_reminders(state: dict) -> dict:
    """檢查合併後的假期開賣日清單，開賣日前 N 天自動發提醒。
    用 state 記錄「已經發送過的提醒」，避免每 5 分鐘重複轟炸。"""
    sent_key = "holiday_reminders_sent"
    sent = set(state.get(sent_key, []))
    today = datetime.now().date()

    for item in get_all_holiday_openings(state):
        name = item.get("name", "（未命名假期）")
        try:
            open_date = datetime.strptime(item["open_date"], "%Y-%m-%d").date()
        except (KeyError, ValueError) as e:
            log.error("「%s」的開賣日期格式錯誤，請確認是否為 YYYY-MM-DD：%s", name, e)
            continue

        open_time = item.get("open_time", "")

        for days_before in item.get("remind_days_before", []):
            target_date = open_date - timedelta(days=days_before)
            unique_key = f"{name}|{item['open_date']}|{days_before}"

            if today == target_date and unique_key not in sent:
                if days_before == 0:
                    when_text = "就是今天！"
                elif days_before == 1:
                    when_text = "明天！"
                else:
                    when_text = f"還有 {days_before} 天"

                msg = (
                    f"🎫 高鐵訂票開賣提醒\n"
                    f"「{name}」\n"
                    f"開賣日期：{item['open_date']}"
                    + (f" {open_time}" if open_time else "")
                    + f"\n距離開賣{when_text}，記得準時上 irs.thsrc.com.tw 搶票！"
                )
                send_telegram_message(msg)
                sent.add(unique_key)
                log.info("已發送「%s」開賣提醒（%s）", name, when_text)

    state[sent_key] = sorted(sent)
    return state


def check_once(state: dict) -> dict:
    """檢查一輪所有網址，回傳更新後的 state。用同一個瀏覽器分頁依序查詢。"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pw_page = browser.new_page(
            user_agent=CONFIG["USER_AGENT"],
            locale="zh-TW",
        )

        for name, url in CONFIG["URLS"].items():
            try:
                text = fetch_page_text(url, pw_page)
            except Exception as e:
                log.error("抓取「%s」失敗：%s", name, e)
                continue

            # 如果是「疏運日程表」頁面，順便自動解析裡面的假期日期
            if name == "疏運日程表":
                parsed = parse_holiday_schedule(text)
                if parsed:
                    state["auto_holiday_schedule"] = parsed
                    log.info(
                        "[debug] 自動解析到 %d 筆假期日期：%s",
                        len(parsed),
                        "、".join(item["name"] for item in parsed),
                    )
                else:
                    log.warning("[debug] 這次沒有從「疏運日程表」解析到任何假期日期，可能排版有變動")
                    # 找出含有西元年份日期格式的那幾行，用 repr() 印出精確結構
                    # （repr 可以清楚看到空白、Tab、換行、全形/半形符號等，方便比對）
                    date_like = re.compile(r"\d{4}/\d{2}/\d{2}")
                    sample_lines = [ln for ln in text.splitlines() if date_like.search(ln)][:10]
                    log.info("[debug] 疑似含日期的原始行內容（repr）：")
                    for ln in sample_lines:
                        log.info("[debug]   %r", ln)

            h = text_hash(text)
            prev = state.get(url, {})
            prev_hash = prev.get("hash")

            if prev_hash is None:
                # 第一次執行，先記錄基準內容，不發通知（避免一啟動就洗版）
                log.info("首次記錄「%s」內容基準", name)
                state[url] = {
                    "hash": h,
                    "text": text,
                    "last_checked": datetime.now().isoformat(timespec="seconds"),
                }
                continue

            hits = find_keyword_hits(text, CONFIG["KEYWORDS"])

            if h != prev_hash:
                log.info("「%s」內容有變動！", name)
                snippet = diff_snippet(prev.get("text", ""), text)
                star = " ⭐關鍵字命中：" + "、".join(hits) if hits else ""
                msg = (
                    f"🚄 高鐵頁面更新通知\n"
                    f"頁面：{name}{star}\n"
                    f"連結：{url}\n"
                    f"時間：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"—— 新增/變動內容摘要 ——\n{snippet}"
                )
                send_telegram_message(msg)
            else:
                log.info("「%s」內容無變動", name)

            state[url] = {
                "hash": h,
                "text": text,
                "last_checked": datetime.now().isoformat(timespec="seconds"),
            }

        browser.close()

    # 用剛剛抓到的最新假期日期（加上手動設定的清單）檢查是否該發開賣提醒
    state = check_holiday_reminders(state)

    return state


def main():
    parser = argparse.ArgumentParser(description="THSR 疏運/加開資訊監控通知程式")
    parser.add_argument(
        "--once", action="store_true", help="只執行一次檢查就結束（適合搭配 cron）"
    )
    args = parser.parse_args()

    state = load_state(CONFIG["STATE_FILE"])

    if args.once:
        state = check_once(state)
        save_state(CONFIG["STATE_FILE"], state)
        return

    log.info(
        "開始常駐監控，每 %s 秒檢查一次；按 Ctrl+C 結束",
        CONFIG["CHECK_INTERVAL_SECONDS"],
    )
    try:
        while True:
            state = check_once(state)
            save_state(CONFIG["STATE_FILE"], state)
            time.sleep(CONFIG["CHECK_INTERVAL_SECONDS"])
    except KeyboardInterrupt:
        log.info("收到中斷指令，結束程式")
        save_state(CONFIG["STATE_FILE"], state)
        sys.exit(0)


if __name__ == "__main__":
    main()
