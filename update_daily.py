#!/usr/bin/env python3
"""
盘后数据同步（v2，2026-11-23 重写）
------------------------------------------------
变更点：
1. 不再依赖已失效的上游站 etf-fund-flow-board.app.workbuddy.host（现返回 403）。
2. 日度申赎净流入改为 Tushare 直连计算：
       netflow(亿元) = (当日 fd_share − 前一有效日 fd_share) × 当日 close / 10000
   fd_share 单位万份、close 单位元 → 万份×元/1e4 = 亿元。
   环境变量 TUSHARE_TOKEN 必填（Actions 里放 repo secret）。
3. 当日分时累计仍用新浪 1 分钟 K（无需 token），断点截断，不写假平线。
4. 幂等：data.js 已含某日则不重复追加；cumdays 当日键可反复覆盖。

用法：python3 update_daily.py            # 收盘后跑（15:35 / 19:00）
"""
import datetime
import json
import os
import ssl
import time
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SSL_CTX = ssl._create_unverified_context()
DATA_JS = os.path.join(BASE_DIR, "data.js")
CUM_JSON = os.path.join(BASE_DIR, "cumdays.json")

# (代码, 市场) 1=沪 0=深
ETFS = [
    ("510310", "1"), ("588000", "1"), ("159915", "0"), ("510300", "1"), ("563360", "1"),
    ("159352", "0"), ("512100", "1"), ("159338", "0"), ("510500", "1"), ("159949", "0"),
    ("588080", "1"), ("510050", "1"), ("510210", "1"), ("159845", "0"), ("159952", "0"),
    ("159361", "0"), ("512050", "1"), ("159633", "0"), ("560010", "1"), ("159919", "0"),
]
IDX_CODE = "000001.SH"      # 上证指数（与 data.js idx 数组同口径）
LOOKBACK = 30               # 每次回看交易日数，够覆盖长假


def ts_code(c):
    return c + (".SH" if c.startswith(("5", "6")) else ".SZ")


def full_axis():
    """241 点：09:30-11:30 + 13:01-15:00"""
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


# ---------------------------------------------------------------- Tushare
def tushare(name, params, fields, token):
    body = json.dumps({"api_name": name, "token": token, "params": params, "fields": fields}).encode()
    req = urllib.request.Request("https://api.tushare.pro", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        r = json.loads(resp.read().decode("utf-8"))
    if r.get("code") != 0:
        raise RuntimeError(f"tushare {name}: {r.get('msg')}")
    return [dict(zip(r["data"]["fields"], row)) for row in r["data"]["items"]]


def tushare_daily(token):
    """返回 {日期(20261120): {'amount': 亿, 'netflow': 亿}}"""
    end = datetime.date.today().strftime("%Y%m%d")
    start = (datetime.date.today() - datetime.timedelta(days=LOOKBACK)).strftime("%Y%m%d")
    rows, shares = [], []
    for c, _ in ETFS:
        rows += tushare("fund_daily", {"ts_code": ts_code(c), "start_date": start,
                                       "end_date": end}, "ts_code,trade_date,close,amount", token)
        shares += tushare("fund_share", {"ts_code": ts_code(c), "start_date": start,
                                         "end_date": end}, "ts_code,trade_date,fd_share", token)
    by_day = {}
    for r in rows:
        by_day.setdefault(r["trade_date"], {})[r["ts_code"]] = r
    sh = {}
    for s in shares:
        sh.setdefault(s["ts_code"], {})[s["trade_date"]] = float(s["fd_share"] or 0)

    out = {}
    for dt, m in by_day.items():
        amt = flow = 0.0
        for c, _ in ETFS:
            r = m.get(ts_code(c))
            if not r:
                continue
            amt += float(r["amount"] or 0) / 1e5
            ds = sh.get(ts_code(c), {})
            cur = ds.get(dt)
            before = [x for x in ds if x < dt]
            if cur is not None and before:
                flow += (cur - ds[before[-1]]) * float(r["close"] or 0) / 10000.0
        out[dt] = {"amount": round(amt, 2), "netflow": round(flow, 2)}
    return out


def index_close(token, dates):
    if not dates:
        return {}
    d = tushare("index_daily", {"ts_code": IDX_CODE, "start_date": min(dates), "end_date": max(dates)},
                "trade_date,close", token)
    return {x["trade_date"]: x["close"] for x in d}


# ---------------------------------------------------------------- data.js
def load_islands():
    import subprocess
    js = ("global.window={};const fs=require('fs');"
          "eval(fs.readFileSync(process.argv[1],'utf8'));"
          "fs.writeFileSync(process.argv[2], JSON.stringify(window.__ISLANDS));")
    subprocess.run(["node", "-e", js, DATA_JS, os.path.join(BASE_DIR, "_islands.json")], check=True)
    return json.load(open(os.path.join(BASE_DIR, "_islands.json"), encoding="utf-8"))


def save_islands(D):
    hdr = "/* 数据层：由 tools/rebuild_from_xlsx.py 重建（2026-10-15 换仓后20只） */\n"
    with open(DATA_JS, "w", encoding="utf-8") as f:
        f.write(hdr + "window.__ISLANDS = " + json.dumps(D, ensure_ascii=False, separators=(",", ":")) + ";\n")


def update_daily(token):
    D = load_islands()
    dd = D["dailyData"]
    last_iso = dd["dates"][-1]
    print(f"[日度] data.js 现有最后日期 {last_iso}（{len(dd['dates'])} 行）")
    daily = tushare_daily(token)
    new = sorted(k for k in daily if f"{k[:4]}-{k[4:6]}-{k[6:]}" > last_iso)
    if not new:
        print("[日度] 已是最新，无新增交易日")
        return D
    idx = index_close(token, new)
    for k in new:
        iso = f"{k[:4]}-{k[4:6]}-{k[6:]}"
        dd["dates"].append(iso)
        dd["amount"].append(daily[k]["amount"])
        dd["netflow"].append(daily[k]["netflow"])
        dd["idx"].append(idx.get(k))
        print(f"  + {iso} 成交 {daily[k]['amount']:.2f} 亿 / 净流入 {daily[k]['netflow']:+.2f} 亿")

    c = D["cmpData"]
    hist = [{"date": dd["dates"][i], "amount": dd["amount"][i], "netflow": dd["netflow"][i]}
            for i in range(len(dd["dates"]))]
    known = {s["date"] for s in c["support"]}
    n = len(new)
    c["support"] += [{"date": h["date"], "amount": h["amount"], "netflow": h["netflow"]}
                     for h in hist[len(hist) - n:-2] if h["netflow"] > 100 and h["date"] not in known]
    recent = hist[-2:]
    for h in recent:
        h["amountPct"] = round(sum(1 for s in hist if s["amount"] < h["amount"]) / len(hist) * 100, 1)
        h["netflowPct"] = round(sum(1 for s in hist if s["netflow"] < h["netflow"]) / len(hist) * 100, 1)
    c["recent"] = recent
    c["latest"] = dict(recent[-1])
    c["today"] = {"date": recent[-1]["date"], "amount": recent[-1]["amount"],
                  "amountPct": recent[-1]["amountPct"]}
    return D


# ---------------------------------------------------------------- 当日分时
def update_cum(D):
    sums, trade_date = {}, None
    for code, m in ETFS:
        sym = ("sh" if m == "1" else "sz") + code
        url = ("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
               f"?symbol={sym}&scale=1&ma=no&datalen=300")
        arr = None
        for k in range(3):
            try:
                req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn/",
                                                           "User-Agent": "Mozilla/5.0"})
                arr = json.loads(urllib.request.urlopen(req, timeout=15, context=SSL_CTX)
                                 .read().decode("utf-8", "replace"))
                break
            except Exception:
                time.sleep(1.2 * (k + 1))
        if not isinstance(arr, list) or not arr:
            print(f"  [分时] {code} 取数失败，跳过")
            continue
        if trade_date is None:
            trade_date = arr[-1].get("day", "")[:10]
        for it in arr:
            if it.get("day", "")[:10] == trade_date:
                t = it["day"][11:16]
                sums[t] = sums.get(t, 0.0) + float(it.get("amount", 0) or 0)
    if not sums:
        print("[分时] 无数据")
        return D
    acc, got = 0.0, []
    for t in FULL_T:
        if t in sums:
            acc += sums[t] / 1e8
            got.append(round(acc, 2))
        elif got:
            break
    days = json.load(open(CUM_JSON, encoding="utf-8")) if os.path.exists(CUM_JSON) else {}
    days[trade_date] = got
    json.dump(days, open(CUM_JSON, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"[分时] {trade_date} 写入 {len(got)} 点，累计 {got[-1]:.2f} 亿")

    ds = sorted(days)
    if len(ds) >= 3:
        prev = days[ds[-2]]
        last20 = [days[d] for d in ds[-21:-1]]
        avg = [round(sum(c) / len(c), 2) for c in zip(*last20)]
        D["cumData"].update({"prevDate": ds[-2], "prev": prev, "avgDays": len(last20), "avg20": avg,
                             "builtAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
    return D


def main():
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if not token:
        print("[warn] 未设置 TUSHARE_TOKEN：跳过日度净流入更新，只补当日分时")
    D = load_islands()
    if token:
        D = update_daily(token)
    D = update_cum(D)
    save_islands(D)
    print(f"[done] data.js / cumdays.json 已写入 {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")


if __name__ == "__main__":
    main()
