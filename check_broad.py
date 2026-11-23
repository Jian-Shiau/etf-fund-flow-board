#!/usr/bin/env python3
"""验证 broadData 的分类映射：用 20 只 ETF 的日度净流入按类别加总，与 data.js 存档比对"""
import json, os, urllib.request

BASE = "/home/ubuntu/projects/repo-push"
tok = [l.strip().split("=", 1)[1] for l in open(os.path.expanduser("~/.hermes/.env"))
       if l.startswith("TUSHARE_TOKEN=")][0]

def api(name, params, fields):
    body = json.dumps({"api_name": name, "token": tok, "params": params, "fields": fields}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request("https://api.tushare.pro", data=body,
                  headers={"Content-Type": "application/json"}), timeout=40))
    return [dict(zip(r["data"]["fields"], row)) for row in r["data"]["items"]]

ETFS = ["510310","588000","159915","510300","563360","159352","512100","159338","510500","159949",
        "588080","510050","510210","159845","159952","159361","512050","159633","560010","159919"]
def tsc(c): return c + (".SH" if c.startswith(("5","6")) else ".SZ")

start, end = "20261103", "20261120"
rows, sh = [], {}
for c in ETFS:
    rows += api("fund_daily", {"ts_code": tsc(c), "start_date": start, "end_date": end}, "ts_code,trade_date,close,amount")
    for s in api("fund_share", {"ts_code": tsc(c), "start_date": "20261031", "end_date": end}, "ts_code,trade_date,fd_share"):
        sh.setdefault(s["ts_code"], {})[s["trade_date"]] = float(s["fd_share"] or 0)

by = {}
for r in rows:
    by.setdefault(r["trade_date"], {})[r["ts_code"]] = r

flow = {}   # flow[date][code] = 亿
for dt, m in by.items():
    flow[dt] = {}
    for c in ETFS:
        r = m.get(tsc(c))
        if not r: continue
        ds = sh.get(tsc(c), {})
        before = [x for x in ds if x < dt]
        if dt in ds and before:
            flow[dt][c] = round((ds[dt] - ds[before[-1]]) * float(r["close"] or 0) / 10000.0, 4)

CAT = {
 "沪深300": ["510310","510300","159919"],
 "A500":    ["563360","159352","159338","159361","512050"],
 "中证500": ["510500"],
 "中证1000":["512100","159845","159633","560010"],
 "科创50":  ["588000","588080"],
 "创业板":  ["159915","159952","159949"],
 "上证50":  ["510050"],
 "上证综指":["510210"],
}
import subprocess
subprocess.run(["node","-e","""
global.window={};const fs=require('fs');
eval(fs.readFileSync(process.argv[1],'utf8'));
fs.writeFileSync(process.argv[2], JSON.stringify(window.__ISLANDS));""",
 f"{BASE}/data.js", "/tmp/islands.json"], check=True)
D = json.load(open("/tmp/islands.json", encoding="utf-8"))
bd = D["broadData"]
print("broadData cats:", bd["cats"])
i = bd["dates"].index("2026-11-10")
print("\n2026-11-10 存档值 vs 我的分类加总：")
for cat in bd["cats"]:
    stored = bd["series"].get(cat, [])
    sv = stored[i] if stored else None
    mine = None
    if cat in CAT:
        mine = round(sum(flow["20261110"].get(c, 0) for c in CAT[cat]), 2)
    # 名称模糊匹配
    print(f"  {cat:8s} 存档 {sv!s:>10}  我的 {mine!s:>8}")
print("\n总计：存档", bd["total"][i], " 我算", round(sum(flow['20261110'].values()),2))
