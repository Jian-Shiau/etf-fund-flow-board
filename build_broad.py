#!/usr/bin/env python3
"""重建 broadData（全市场宽基 ETF，按跟踪指数分 12 类）——先在重叠窗口做口径校验"""
import json, os, re, sys, urllib.request
from collections import defaultdict

BASE = "/home/ubuntu/projects/repo-push"
tok = [l.strip().split("=", 1)[1] for l in open(os.path.expanduser("~/.hermes/.env"))
       if l.startswith("TUSHARE_TOKEN=")][0]

def api(n, p, f=""):
    body = json.dumps({"api_name": n, "token": tok, "params": p, "fields": f}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request("https://api.tushare.pro", data=body,
                  headers={"Content-Type": "application/json"}), timeout=120))
    if r.get("code") != 0:
        print("ERR", n, r.get("msg")); return []
    return [dict(zip(r["data"]["fields"], row)) for row in r["data"]["items"]]

CATS = ["沪深300", "中证1000", "中证500", "科创50", "中证A500", "创业板指", "上证50",
        "其他宽基", "创业板50", "双创50", "中证2000", "国证2000"]

def classify(name, bench):
    s = (name or "") + "|" + (bench or "")
    if "创业板50" in s: return "创业板50"
    if "双创50" in s or "科创创业50" in s: return "双创50"
    if "沪深300" in s: return "沪深300"
    if "中证1000" in s: return "中证1000"
    if "中证500" in s: return "中证500"
    if "中证A500" in s or "A500" in s: return "中证A500"
    if "科创50" in s or "科创板50" in s: return "科创50"
    if "创业板" in s: return "创业板指"
    if "上证50" in s: return "上证50"
    if "中证2000" in s: return "中证2000"
    if "国证2000" in s: return "国证2000"
    if re.search(r"上证180|深证100|中证100|中证800|中证A100|中证全指|MSCI|北证50|上证380|中证A50|深证成指|央视50|中证1000", s):
        return "其他宽基"
    return None

fb = api("fund_basic", {"market": "E", "status": "L"}, "ts_code,name,benchmark,fund_type,invest_type")
uni = {}
for f in fb:
    if f["fund_type"] not in ("股票型", "混合型"): continue
    c = classify(f["name"], f["benchmark"])
    if c: uni[f["ts_code"]] = c
print("归类 ETF 数:", len(uni), "| 分类分布:", {k: sum(1 for v in uni.values() if v == k) for k in CATS})

def day_flows(d):
    sh = {x["ts_code"]: float(x["fd_share"] or 0) for x in api("fund_share", {"trade_date": d}, "ts_code,fd_share")}
    px = {x["ts_code"]: float(x["close"] or 0) for x in api("fund_daily", {"trade_date": d}, "ts_code,close")}
    return sh, px

out = {}
prev_sh = None
dates = ["20261103","20261104","20261105","20261106","20261109","20261110"]
# 需要 11/02 的份额作为 11/03 的基准
prev_sh, _ = day_flows("20261102")
for d in dates:
    sh, px = day_flows(d)
    cats = defaultdict(float)
    for code, cat in uni.items():
        if code in sh and code in prev_sh and code in px:
            cats[cat] += (sh[code] - prev_sh[code]) * px[code] / 10000.0
    out[d] = {k: round(cats.get(k, 0.0), 2) for k in CATS}
    out[d]["_total"] = round(sum(cats.values()), 2)
    prev_sh = sh
    print(d, out[d]["_total"], {k: out[d][k] for k in CATS[:4]})

json.dump(out, open("/tmp/broad_test.json", "w"), ensure_ascii=False, indent=1)

D = json.load(open("/tmp/islands.json", encoding="utf-8"))
bd = D["broadData"]
print("\n=== 与存档对比（2026-11-10）")
i = bd["dates"].index("2026-11-10")
for c in CATS:
    st = bd["series"][c][i]
    print(f"  {c:8s} 存档 {st:8.2f}  我算 {out['20261110'][c]:8.2f}  差 {out['20261110'][c]-st:+7.2f}")
print("  合计   存档", bd["total"][i], " 我算", out["20261110"]["_total"])
