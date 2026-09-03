#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_telegram.py
=================
獨立測試 Telegram Bot 通知是否設定正確，跟 thsr_watcher.py 的監控邏輯完全無關。
如果這支程式能收到訊息，代表 Token / Chat ID 沒問題；
如果連這支都收不到，問題就出在 Telegram 設定，不是高鐵監控程式的邏輯。

使用方式：
    export THSR_TG_TOKEN="8832061778:AAEs1fh-5fZ65FkSqvs2Ks4N-Or-KxTLKe4"
    export THSR_TG_CHAT_ID="1211817511"
    python3 test_telegram.py

或直接把下面兩個變數改成你的值也可以。
"""

import os
import sys
import requests

TOKEN = os.environ.get("THSR_TG_TOKEN", "8832061778:AAEs1fh-5fZ65FkSqvs2Ks4N-Or-KxTLKe4")
CHAT_ID = os.environ.get("THSR_TG_CHAT_ID", "1211817511")


def main():
    if "請填入" in TOKEN or "請填入" in str(CHAT_ID):
        print("❌ 還沒設定 TOKEN / CHAT_ID，請先修改本檔案上方變數，或用環境變數帶入。")
        sys.exit(1)

    print(f"[debug] TOKEN 前 10 碼: {TOKEN[:10]}...")
    print(f"[debug] CHAT_ID: {CHAT_ID}")

    # 1. 先驗證 Token 本身有沒有效（不需要 chat_id）
    print("\n--- 步驟 1：驗證 Bot Token（getMe）---")
    r = requests.get(f"https://api.telegram.org/bot{TOKEN}/getMe", timeout=10)
    print("HTTP 狀態碼:", r.status_code)
    print("回應內容:", r.text)
    if r.status_code != 200:
        print("❌ Token 本身有問題，請重新確認是不是複製完整、有沒有多餘空白/符號。")
        sys.exit(1)
    print("✅ Token 有效")

    # 2. 實際發一則訊息
    print("\n--- 步驟 2：發送測試訊息（sendMessage）---")
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": "🚄 這是一則測試訊息，如果你看到這則代表設定成功！"},
        timeout=10,
    )
    print("HTTP 狀態碼:", r.status_code)
    print("回應內容:", r.text)

    if r.status_code == 200:
        print("\n✅ 成功！去看看 Telegram 有沒有跳通知。")
    else:
        print("\n❌ 發送失敗，常見原因：")
        print("   - CHAT_ID 錯誤（要跟 getUpdates 抓到的一致，且必須是主動跟 bot 說過話後才拿得到）")
        print("   - Bot 被你封鎖 / 沒開始對話過")
        sys.exit(1)


if __name__ == "__main__":
    main()