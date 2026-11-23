#!/usr/bin/env python3
"""把重算的全市场宽基日度净流入并回 data.js 的 broadData（保留历史，追加新日期）"""
import json

BASE = "/home/ubuntu/projects/repo-push"
D = json.load(open("/tmp/islands.json", encoding="utf-8"))
bd = D["broadData"]
res = json.load(open(f"{BASE}/broad_new.json", encoding="utf-8"))
CATS = bd["cats"]

last = bd["dates"][-1]
new = sorted(k for k in res if f"{k[:4]}-{k[4:6]}-{k[6:]}" > last)
print("追加日期:", new)

cum = bd["totalCum"][-1]
for k in new:
    iso = f"{k[:4]}-{k[4:6]}-{k[6:]}"
    bd["dates"].append(iso)
    for c in CATS:
        bd["series"][c].append(round(res[k][c], 2))
    tot = round(sum(res[k][c] for c in CATS), 2)
    bd["total"].append(tot)
    cum = round(cum + tot, 1)
    bd["totalCum"].append(cum)
    print(f"  {iso} 合计 {tot:+7.2f} 亿 | 累计 {cum:.1f}")

# 一致性检查：各序列长度必须相等
L = len(bd["dates"])
assert all(len(bd["series"][c]) == L for c in CATS), "series 长度不一致"
assert len(bd["total"]) == L and len(bd["totalCum"]) == L

hdr = "/* 数据层：由 tools/rebuild_from_xlsx.py 重建（2026-10-15 换仓后20只） */\n"
open(f"{BASE}/data.js", "w", encoding="utf-8").write(
    hdr + "window.__ISLANDS = " + json.dumps(D, ensure_ascii=False, separators=(",", ":")) + ";\n")
print("写入 data.js | dates", L, "| 末行", bd["dates"][-1], "| totalCum", bd["totalCum"][-1])
