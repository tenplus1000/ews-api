"""ews 對外入口：驗 key、每日上限、外部一次一發，轉給推論主機的 judge-serve。

    python3 gateway.py serve                      # 開服務（預設 127.0.0.1:8106）
    python3 gateway.py newkey --name 某人 --contact discord:xxx [--daily 500]
    python3 gateway.py list
    python3 gateway.py revoke <key_id>

設定（環境變數）：
  EWS_UPSTREAM   推論主機的 decisions 端點（預設 http://100.64.167.92:8101/v1/decisions）
  EWS_DATA       key、用量、紀錄放哪（預設 ./data，不進 git）
  EWS_PORT       預設 8106
  EWS_MODEL      送到推論主機的模型名（預設 ews-0.6）

Elsewhen 自己照舊直接連推論主機，不經過這裡；這裡一次只放一發外部請求進去，顯卡忙就回 429，
不會排在遊戲前面。key 只存雜湊；每一發（含被擋的）都記一行，題目原文由推論主機那邊記。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

UPSTREAM = os.environ.get("EWS_UPSTREAM", "http://100.64.167.92:8101/v1/decisions")
DATA = Path(os.environ.get("EWS_DATA", Path(__file__).resolve().parent / "data"))
PORT = int(os.environ.get("EWS_PORT", "8106"))
MODEL = os.environ.get("EWS_MODEL", "ews-0.6")
MODEL_NAMES = {"ews", "ews-0.6", MODEL}
DEFAULT_DAILY = 500
MAX_BODY = 64_000            # bytes
MAX_STATE = 20_000           # characters
MAX_QUESTIONS = 20
WAIT_FOR_SLOT = 5.0          # 外部請求最多等幾秒拿到位子，等不到回 429
UPSTREAM_TIMEOUT = 20.0
DOCS = "https://github.com/tenplus1000/ews-api"

_slot = threading.Semaphore(1)       # 外部一次一發
_lock = threading.Lock()             # 讀寫 key／用量檔


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def keys() -> dict:
    return _read(DATA / "keys.json", {})


def log(row: dict) -> None:
    """每一發都記：誰（key_id）、結果、耗時、大小。不記題目原文。"""
    path = DATA / "logs" / f"{_today()}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"ts": round(time.time(), 2), **row}, ensure_ascii=False) + "\n")


def _count(key_id: str, daily: int) -> bool:
    """今天再用一次。超過上限回 False（不加）。"""
    path = DATA / "usage" / f"{_today()}.json"
    with _lock:
        used = _read(path, {})
        if used.get(key_id, 0) >= daily:
            return False
        used[key_id] = used.get(key_id, 0) + 1
        _write(path, used)
    return True


def _find(auth: str) -> tuple[str, dict] | tuple[None, None]:
    if not auth.startswith("Bearer "):
        return None, None
    wanted = _hash(auth[7:].strip())
    for key_id, row in keys().items():
        if row.get("hash") == wanted and not row.get("revoked"):
            return key_id, row
    return None, None


class Handler(BaseHTTPRequestHandler):
    server_version = "ews-api"

    def log_message(self, *args):        # 不印到標準錯誤，紀錄走 log()
        pass

    def _send(self, status: int, body: dict, headers: dict | None = None) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _refuse(self, status: int, why: str, key_id: str = "", headers: dict | None = None) -> None:
        log({"key_id": key_id, "status": status, "refused": why})
        self._send(status, {"error": {"code": status, "message": why}}, headers)

    def do_GET(self):
        if self.path == "/health":
            try:
                with urllib.request.urlopen(UPSTREAM.rsplit("/v1/", 1)[0] + "/health", timeout=5) as r:
                    up = json.loads(r.read())
                return self._send(200, {"ok": True, "model": up.get("model")})
            except Exception:
                return self._send(503, {"ok": False, "error": "model server unreachable"})
        return self._send(200, {"service": "ews decisions API", "docs": DOCS,
                                "endpoint": "POST /v1/decisions"})

    def do_POST(self):
        if self.path != "/v1/decisions":
            return self._send(404, {"error": {"code": 404, "message": "POST /v1/decisions"}})
        key_id, row = _find(self.headers.get("Authorization", ""))
        if key_id is None:
            return self._refuse(401, "missing or invalid API key (Authorization: Bearer <key>)")
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0 or size > MAX_BODY:
            return self._refuse(413, f"request body must be 1..{MAX_BODY} bytes", key_id)
        try:
            body = json.loads(self.rfile.read(size))
        except ValueError:
            return self._refuse(400, "body is not JSON", key_id)
        problem = _check(body)
        if problem:
            return self._refuse(400, problem, key_id)
        if not _count(key_id, int(row.get("daily") or DEFAULT_DAILY)):
            return self._refuse(429, "daily limit reached; resets at 00:00 UTC", key_id)
        if not _slot.acquire(timeout=WAIT_FOR_SLOT):
            return self._refuse(429, "busy, retry in a few seconds", key_id, {"Retry-After": "5"})
        started = time.time()
        try:
            payload = json.dumps({"model": MODEL, "state": body["state"],
                                  "questions": body["questions"]}).encode()
            req = urllib.request.Request(UPSTREAM, data=payload, method="POST", headers={
                "Content-Type": "application/json", "x-client": f"api:{key_id}"})
            with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as r:
                answer = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            log({"key_id": key_id, "status": 502, "error": f"{type(error).__name__}"[:80],
                 "elapsed": round(time.time() - started, 3)})
            return self._send(502, {"error": {"code": 502, "message": "model server unavailable, retry later"}})
        finally:
            _slot.release()
        log({"key_id": key_id, "status": 200, "elapsed": round(time.time() - started, 3),
             "questions": len(body["questions"]), "state_chars": len(body["state"])})
        answer["model"] = MODEL
        return self._send(200, answer)


def _check(body) -> str:
    if not isinstance(body, dict):
        return "body must be a JSON object"
    if body.get("model") not in (None, *MODEL_NAMES):
        return f"unknown model; use \"{MODEL}\""
    state, questions = body.get("state"), body.get("questions")
    if not isinstance(state, str) or not state.strip():
        return "\"state\" must be a non-empty string"
    if len(state) > MAX_STATE:
        return f"\"state\" is longer than {MAX_STATE} characters"
    if not isinstance(questions, dict) or not questions:
        return "\"questions\" must be a non-empty object"
    if len(questions) > MAX_QUESTIONS:
        return f"at most {MAX_QUESTIONS} questions per request"
    for name, q in questions.items():
        if not isinstance(q, dict) or q.get("type") not in ("noul", "choice"):
            return f"question \"{name}\": type must be \"noul\" or \"choice\""
        if not isinstance(q.get("instructions"), str) or not q["instructions"].strip():
            return f"question \"{name}\": \"instructions\" must be a non-empty string"
        if q["type"] == "choice" and not isinstance(q.get("criteria"), dict):
            return f"question \"{name}\": choice questions need \"criteria\" {{id: description}}"
    return ""


def newkey(name: str, contact: str, daily: int) -> str:
    key = "ews_" + secrets.token_urlsafe(24)
    key_id = "k" + secrets.token_hex(4)
    with _lock:
        data = keys()
        data[key_id] = {"hash": _hash(key), "name": name, "contact": contact, "daily": daily,
                        "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _write(DATA / "keys.json", data)
    return f"{key_id} {key}"


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description="ews decisions API gateway")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    n = sub.add_parser("newkey")
    n.add_argument("--name", required=True)
    n.add_argument("--contact", required=True, help="how they reached you: email:…／discord:…／ig:…／threads:…")
    n.add_argument("--daily", type=int, default=DEFAULT_DAILY)
    sub.add_parser("list")
    r = sub.add_parser("revoke")
    r.add_argument("key_id")
    a = p.parse_args(argv)
    if a.cmd == "serve":
        print(f"ews-api on 127.0.0.1:{PORT} → {UPSTREAM}", flush=True)
        ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
    elif a.cmd == "newkey":
        key_id, key = newkey(a.name, a.contact, a.daily).split()
        print(f"key_id: {key_id}\nkey:    {key}\n（這把 key 只印這一次，存的是雜湊）")
    elif a.cmd == "list":
        used = _read(DATA / "usage" / f"{_today()}.json", {})
        for key_id, row in keys().items():
            state = "停用" if row.get("revoked") else "使用中"
            print(f"{key_id}  {row['name']}  {row['contact']}  每日 {row['daily']}  今天 {used.get(key_id, 0)}  {state}")
    elif a.cmd == "revoke":
        with _lock:
            data = keys()
            if a.key_id not in data:
                sys.exit(f"沒有這把：{a.key_id}")
            data[a.key_id]["revoked"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _write(DATA / "keys.json", data)
        print(f"已停用 {a.key_id}")


if __name__ == "__main__":
    main()
