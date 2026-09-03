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

使用方式：
    python3 thsr_watcher.py            # 常駐執行，每隔 CHECK_INTERVAL_SECONDS 檢查一次
    python3 thsr_watcher.py --once     # 只檢查一次就結束（適合排 cron / 測試用）
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

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

    "REQUEST_TIMEOUT": 15,
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


def fetch_page_text(url: str) -> str:
    """抓取頁面並萃取『可見文字』，過濾掉 script/style/導覽選單雜訊。"""
    headers = {
        "User-Agent": CONFIG["USER_AGENT"],
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    }
    resp = requests.get(url, headers=headers, timeout=CONFIG["REQUEST_TIMEOUT"])

    # --- 除錯資訊：印出 HTTP 狀態碼、最終網址（有沒有被導向別的頁面）、內容長度 ---
    log.info(
        "[debug] GET %s -> status=%s final_url=%s content_length=%s",
        url, resp.status_code, resp.url, len(resp.text),
    )

    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    # 高鐵官網主要內容通常在 id="main-content" 或 <main> 內；
    # 抓不到就退回整個 body，避免漏抓。
    main = soup.find(id="main-content") or soup.find("main") or soup.body or soup
    text = main.get_text(separator="\n")

    # 壓縮多餘空白行
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    result = "\n".join(lines)

    # --- 除錯資訊：把抓到的前 300 字印出來，方便判斷是不是抓到空殼/擋牆頁面 ---
    preview = result[:300].replace("\n", " | ") if result else "(空白，什麼都沒抓到)"
    log.info("[debug] 內容預覽（前300字）: %s", preview)

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


def check_once(state: dict) -> dict:
    """檢查一輪所有網址，回傳更新後的 state。"""
    for name, url in CONFIG["URLS"].items():
        try:
            text = fetch_page_text(url)
        except requests.RequestException as e:
            log.error("抓取「%s」失敗：%s", name, e)
            continue

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
