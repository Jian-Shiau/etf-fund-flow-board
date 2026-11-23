#!/usr/bin/env python3
"""用 histData 反解原口径：20 只 ETF 的逐日净流入，试试不同价格基准能否复现存档累计值"""
import json, os, urllib.request

BASE = "/home/ubuntu/projects/repo-push"
tok = [l.strip().split("=", 1)[1] for l in open(os.path.expanduser("~/.hermes/.env")) if l.startswith("TUSHARE_TOKEN=")][0]

def api(n, p, f):
    b = json.dumps({"api_name": n, "token": tok, "params": p, "fields": f}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request("https://api.tushare.pro", data=b,
                  headers={"Content-Type": "application/json"}), timeout=60))
    return [dict(zip(r["data"]["fields"], row)) for row in r["data"]["items"]]

D = json.load(open("/tmp/islands.json", encoding="utf-8"))
hd = D["histData"]
dates = hd["dates"]
start, end = dates[0].replace("-", ""), "20261110"
codes = [f["code"] for f in hd["funds"]]
def tsc(c): return c + (".SH" if c.startswith(("5", "6")) else ".SZ")

sh, px = {}, {}
for c in codes:
    for s in api("fund_share", {"ts_code": tsc(c), "start_date": "20251231", "end_date": end},
                 "trade_date,fd_share"):
        sh.setdefault(c, {})[s["trade_date"]] = float(s["fd_share"] or 0)
    for r in api("fund_daily", {"ts_code": tsc(c), "start_date": "20251231", "end_date": end},
                 "trade_date,close"):
        px.setdefault(c, {})[r["trade_date"]] = float(r["close"] or 0)
print("数据就绪", len(sh), "只")

def build(basis):
    out = {}
    for c in codes:
        ds = sorted(sh.get(c, {}))
        cum, run = [], 0.0
        for d in [x.replace("-", "") for x in dates]:
            before = [x for x in ds if x < d]
            if d in sh.get(c, {}) and before:
                delta = sh[c][d] - sh[c][before[-1]]
                if basis == "close":
                    p = px.get(c, {}).get(d, 0)
                elif basis == "prev_close":
                    p = px.get(c, {}).get(before[-1], 0)
                else:
                    p = px.get(c, {}).get(d, 0)
                run += delta * p / 10000.0
            cum.append(round(run, 4))
        out[c] = cum
    return out

for basis in ["close", "prev_close"]:
    got = build(basis)
    c = codes[0]
    a = got[c]
    b = hd["cum"][c]
    # 对齐首日
    diff_last = round(a[-1] - b[-1], 2)
    print(f"[{basis}] {c}: 末值 我 {a[-1]:.2f} / 存档 {b[-1]:.2f} 差 {diff_last:+.2f}")
    for i in (0, 1, 50, 100, len(a) - 1):
        print(f"    idx{i} {dates[i]}: 我 {a[i]:.2f} 存档 {b[i]:.2f}")
