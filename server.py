#!/usr/bin/env python3
"""
重点ETF资金看板 - 本地独立服务端
直接对接新浪财经（1分钟分时K线）与东方财富（实时行情快照）公开接口，无需原站密码或网关。
"""
import json
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", "8765"))
SSL_CTX = ssl._create_unverified_context()

# 内存缓存，避免高频刷新触发上游限流
_cache_lock = threading.Lock()
_kline_cache = {}  # key: (symbol, scale, datalen) -> (ts, list)
_hq_cache = {}     # key: codes_str -> (ts, bytes)

KLINE_TTL = 15.0   # 分时 K 线缓存 15 秒
HQ_TTL = 5.0       # 实时行情缓存 5 秒

_executor = ThreadPoolExecutor(max_workers=10)


def fetch_sina_kline(symbol: str, scale: str = "1", datalen: str = "260"):
    key = (symbol, scale, datalen)
    now = time.time()
    with _cache_lock:
        hit = _kline_cache.get(key)
        if hit and (now - hit[0]) < KLINE_TTL:
            return hit[1]

    url = (
        "https://quotes.sina.cn/cn/api/json_v2.php/"
        f"CN_MarketDataService.getKLineData?symbol={urllib.parse.quote(symbol)}"
        f"&scale={urllib.parse.quote(scale)}&ma=no&datalen={urllib.parse.quote(datalen)}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Referer": "https://finance.sina.com.cn/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            arr = json.loads(raw)
            if isinstance(arr, list) and arr:
                with _cache_lock:
                    _kline_cache[key] = (time.time(), arr)
                return arr
    except Exception:
        pass
    # 失败时若缓存里有旧数据则兜底返回
    with _cache_lock:
        hit = _kline_cache.get(key)
        if hit:
            return hit[1]
    return []


def code_to_secid(code: str) -> str:
    code = code.strip().lower()
    if code.startswith("sh"):
        return "1." + code[2:]
    if code.startswith("sz"):
        return "0." + code[2:]
    if "." in code:
        return code
    return ("1." if code.startswith(("5", "6")) else "0.") + code


def fetch_eastmoney_hq(codes_str: str) -> bytes:
    now = time.time()
    with _cache_lock:
        hit = _hq_cache.get(codes_str)
        if hit and (now - hit[0]) < HQ_TTL:
            return hit[1]

    codes = [c for c in codes_str.split(",") if c.strip()]
    secids = ",".join(code_to_secid(c) for c in codes)
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?fltt=2&invt=2&fields=f2,f3,f6,f12,f14,f18&secids={urllib.parse.quote(secids)}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Referer": "https://quote.eastmoney.com/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10, context=SSL_CTX) as resp:
            data = resp.read()
            if data:
                with _cache_lock:
                    _hq_cache[codes_str] = (time.time(), data)
                return data
    except Exception:
        pass
    with _cache_lock:
        hit = _hq_cache.get(codes_str)
        if hit:
            return hit[1]
    return b'{"rc":-1,"data":{"diff":[]}}'


class ETFBoardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def log_message(self, fmt, *args):
        # 精简日志
        pass

    def _send_json(self, payload: bytes, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/kline":
            symbol = (qs.get("symbol") or ["sh000001"])[0]
            scale = (qs.get("scale") or ["1"])[0]
            datalen = (qs.get("datalen") or ["260"])[0]
            arr = fetch_sina_kline(symbol, scale, datalen)
            self._send_json(json.dumps(arr, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/ktrends":
            symbols_str = (qs.get("symbols") or [""])[0]
            scale = (qs.get("scale") or ["1"])[0]
            datalen = (qs.get("datalen") or ["260"])[0]
            symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]

            def _job(sym):
                arr = fetch_sina_kline(sym, scale, datalen)
                slim = [
                    {"day": r.get("day"), "close": r.get("close"), "amount": r.get("amount")}
                    for r in arr
                    if isinstance(r, dict) and "day" in r
                ]
                return sym, slim

            out = {}
            for sym, slim in _executor.map(_job, symbols):
                out[sym] = slim

            self._send_json(json.dumps(out, ensure_ascii=False).encode("utf-8"))
            return

        if path == "/api/hq":
            codes = (qs.get("codes") or [""])[0]
            data = fetch_eastmoney_hq(codes)
            self._send_json(data)
            return

        if path == "/api/ping":
            self._send_json(b'{"ok":true}')
            return

        return super().do_GET()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), ETFBoardHandler)
    print(f"重点ETF资金看板已启动: http://0.0.0.0:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
