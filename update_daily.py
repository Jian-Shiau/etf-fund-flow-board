#!/usr/bin/env python3
"""
盘后数据同步与分时累计更新脚本 (update_daily.py)
功能：
1. 若原站点仍在线，可一键同步最新的 data.js 与 cumdays.json（包含 Choice T-1 申赎净流入数据）
2. 本地直接从新浪财经拉取 20 只重点 ETF 的当日 1 分钟 K 线，计算 241 点分钟累计成交额并写入 cumdays.json，
   即使原站点未更新或已下线，也能在每日收盘后把当天分时累计曲线存档供后续对比。
"""
import json
import os
import ssl
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SSL_CTX = ssl._create_unverified_context()

ETFS = [
    ("510310", "1"), ("588000", "1"), ("159915", "0"), ("510300", "1"), ("563360", "1"),
    ("159352", "0"), ("512100", "1"), ("159338", "0"), ("510500", "1"), ("159949", "0"),
    ("588080", "1"), ("510050", "1"), ("510210", "1"), ("159845", "0"), ("159952", "0"),
    ("159361", "0"), ("512050", "1"), ("159633", "0"), ("560010", "1"), ("159919", "0"),
]


def full_axis():
    ts = []
    for start, count in [("09:30", 121), ("13:01", 120)]:
        hh, mm = int(start[:2]), int(start[3:5])
        for _ in range(count):
            ts.append(f"{hh:02d}:{mm:02d}")
            mm += 1
            if mm == 60:
                mm = 0
                hh += 1
    return ts


FULL_T = full_axis()


def sync_from_upstream():
    base = "https://etf-fund-flow-board.app.workbuddy.host"
    try:
        req = urllib.request.Request(
            f"{base}/api/verify",
            data=json.dumps({"password": "jinke@dongcai"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";")[0]
        if not cookie:
            return False

        for fname, min_len in [("data.js", 50000), ("cumdays.json", 50000)]:
            for attempt in range(5):
                url = f"{base}/{fname}?_={int(time.time()*1000)}_{attempt}"
                r = urllib.request.Request(url, headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(r, timeout=20, context=SSL_CTX) as resp:
                    data = resp.read()
                    if len(data) >= min_len:
                        with open(os.path.join(BASE_DIR, fname), "wb") as f:
                            f.write(data)
                        print(f"[上游同步] 已更新 {fname} ({len(data)} bytes)")
                        break
                time.sleep(0.3 * (attempt + 1))
        return True
    except Exception as e:
        print(f"[上游同步] 跳过（原因: {e}），使用本地计算")
        return False


def update_today_cum_from_sina():
    sums = {}
    trade_date = None
    for code, m in ETFS:
        sym = ("sh" if m == "1" else "sz") + code
        url = (
            "https://quotes.sina.cn/cn/api/json_v2.php/"
            f"CN_MarketDataService.getKLineData?symbol={sym}&scale=1&ma=no&datalen=260"
        )
        req = urllib.request.Request(
            url, headers={"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            arr = json.loads(resp.read().decode("utf-8", errors="replace"))
        if not isinstance(arr, list) or not arr:
            continue
        last_day = arr[-1].get("day", "")[:10]
        if not trade_date:
            trade_date = last_day
        for item in arr:
            d = item.get("day", "")
            if d[:10] == trade_date:
                t = d[11:16]
                sums[t] = sums.get(t, 0.0) + float(item.get("amount", 0.0))

    if not trade_date or not sums:
        print("[新浪计算] 未获取到分时数据")
        return

    cum_arr = []
    acc = 0.0
    for t in FULL_T:
        acc += sums.get(t, 0.0) / 1e8
        cum_arr.append(round(acc, 2))

    cum_path = os.path.join(BASE_DIR, "cumdays.json")
    cum_days = {}
    if os.path.exists(cum_path):
        with open(cum_path, "r", encoding="utf-8") as f:
            cum_days = json.load(f)

    cum_days[trade_date] = cum_arr
    with open(cum_path, "w", encoding="utf-8") as f:
        json.dump(cum_days, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[新浪计算] 已将 {trade_date} 的 241 分钟累计成交额（收盘合计 {cum_arr[-1]} 亿）写入 cumdays.json")


if __name__ == "__main__":
    sync_from_upstream()
    update_today_cum_from_sina()
