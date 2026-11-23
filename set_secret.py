#!/usr/bin/env python3
"""把 TUSHARE_TOKEN 写入仓库 Actions secrets（不出现在日志里）"""
import base64, json, os, sys, urllib.request
from nacl import encoding, public

TOKEN = open(os.path.expanduser("~/.config/hermes_gh_token")).read().strip()
REPO = "Jian-Shiau/etf-fund-flow-board"
TS = [l.strip().split("=", 1)[1] for l in open(os.path.expanduser("~/.hermes/.env"))
      if l.startswith("TUSHARE_TOKEN=")][0]

def api(method, path, payload=None):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        data=json.dumps(payload).encode() if payload else None,
        method=method,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return r.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:200]}

code, key = api("GET", f"/repos/{REPO}/actions/secrets/public-key")
print("public-key:", code)
if code != 200:
    print(key); sys.exit(1)

pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
box = public.SealedBox(pk)
enc = base64.b64encode(box.encrypt(TS.encode())).decode()

code, res = api("PUT", f"/repos/{REPO}/actions/secrets/TUSHARE_TOKEN",
                {"encrypted_value": enc, "key_id": key["key_id"]})
print("set secret:", code, "| 长度校验:", len(TS), "字符")
print("成立" if code in (201, 204) else res)
