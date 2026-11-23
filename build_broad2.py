#!/usr/bin/env python3
"""重建 broadData：全市场宽基 ETF（按跟踪指数 12 分类）逐日净流入，先校验再追加"""
import json, os, re, urllib.request
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
BAD = re.compile(r"增强|价值|成长|ESG|红利|低波|等权|医药|非银|金融|消费|科技|国企|央企|"
                 r"恒生|港股|纳斯达克|标普|日经|德国|法国|东南亚|沙特|QDII|黄金|债|货币|REIT")
OTHER = re.compile(r"上证180|深证100|中证100|中证800|中证A100|中证A50|中证全指|MSCI|北证50|"
                   r"上证380|深证成指|央视50|中证200|中证300|中证700|中证A800|上证综指|深证综指")

def classify(name, bench):
    s = (name or "")
    if BAD.search(s): return None
    if "创业板50" in s: return "创业板50"
    if "双创50" in s or "科创创业50" in s: return "双创50"
    if "沪深300" in s: return "沪深300"
    if "中证1000" in s: return "中证1000"
    if "中证500" in s: return "中证500"
    if "A500" in s: return "中证A500"
    if "科创50" in s or "科创板50" in s: return "科创50"
    if "创业板" in s: return "创业板指"
    if "上证50" in s: return "上证50"
    if "中证2000" in s: return "中证2000"
    if "国证2000" in s: return "国证2000"
    if OTHER.search(s) or OTHER.search(str(bench or "")): return "其他宽基"
    return None

fb = api("fund_basic", {"market": "E", "status": "L"}, "ts_code,name,benchmark,fund_type,invest_type")
uni = {}
for f in fb:
    if f["fund_type"] != "股票型": continue
    if f["invest_type"] == "增强指数型": continue
    c = classify(f["name"], f["benchmark"])
    if c: uni[f["ts_code"]] = c
print("归类 ETF:", len(uni), {k: sum(1 for v in uni.values() if v == k) for k in CATS})

def day(d):
    sh = {x["ts_code"]: float(x["fd_share"] or 0) for x in api("fund_share", {"trade_date": d}, "ts_code,fd_share")}
    px = {x["ts_code"]: float(x["close"] or 0) for x in api("fund_daily", {"trade_date": d}, "ts_code,close")}
    return sh, px

dates = ["20261103","20261104","20261105","20261106","20261109","20261110",
         "20261111","20261112","20261113","20261116","20261117","20261118","20261119","20261120"]
prev_sh, _ = day("20261102")
res = {}
for d in dates:
    sh, px = day(d)
    cats = defaultdict(float)
    for code, cat in uni.items():
        if code in sh and code in prev_sh and code in px:
            cats[cat] += (sh[code] - prev_sh[code]) * px[code] / 10000.0
    res[d] = {k: round(cats.get(k, 0.0), 4) for k in CATS}
    res[d]["_total"] = round(sum(cats.values()), 4)
    prev_sh = sh
    print(d, "合计", res[d]["_total"])

json.dump(res, open(f"{BASE}/broad_new.json", "w"), ensure_ascii=False, indent=1)

D = json.load(open("/tmp/islands.json", encoding="utf-8"))
bd = D["broadData"]
print("\n=== 校验（存档 vs 重算）")
for d in ["2026-11-03", "2026-11-10"]:
    i = bd["dates"].index(d)
    k = d.replace("-", "")
    errs = []
    for c in CATS:
        st, mine = bd["series"][c][i], res[k][c]
        errs.append(abs(mine - st))
        print(f"  {d} {c:8s} 存档 {st:8.2f} 重算 {mine:8.2f} 差 {mine-st:+7.2f}")
    print(f"  {d} 合计 存档 {bd['total'][i]:.2f} 重算 {res[k]['_total']:.2f} | 平均绝对误差 {sum(errs)/len(errs):.2f}")
