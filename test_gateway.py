"""入口的規則：沒 key／錯 key 擋、上限擋、格式擋、一次一發、轉送內容與每一發的紀錄。上游用假的。"""
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SENT = []
SLOW = {"seconds": 0.0}


class FakeUpstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self._json({"model": "ews-0.6"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SENT.append((body, self.headers.get("x-client")))
        time.sleep(SLOW["seconds"])
        self._json({"id": "x", "model": "ews-0.6", "answers": {k: {"noul": 0.7} for k in body["questions"]}})

    def _json(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def api(monkeypatch):
    up = ThreadingHTTPServer(("127.0.0.1", 0), FakeUpstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    tmp = tempfile.TemporaryDirectory()
    import gateway
    monkeypatch.setattr(gateway, "UPSTREAM", f"http://127.0.0.1:{up.server_port}/v1/decisions")
    monkeypatch.setattr(gateway, "DATA", Path(tmp.name))
    monkeypatch.setattr(gateway, "WAIT_FOR_SLOT", 0.2)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    SENT.clear()
    SLOW["seconds"] = 0.0
    yield gateway, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    up.shutdown()
    tmp.cleanup()


def post(base, body, key=None):
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(base + "/v1/decisions", data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


GOOD = {"model": "ews-0.6", "state": "She handed him the bread and he ate it.",
        "questions": {"ate": {"type": "noul", "instructions": "Did anyone eat something?"}}}


def logs(gateway):
    rows = []
    for path in (gateway.DATA / "logs").glob("*.jsonl"):
        rows += [json.loads(l) for l in path.read_text().splitlines()]
    return rows


def test_有效的key_轉給上游_回答案(api):
    gateway, base = api
    key_id, key = gateway.newkey("tester", "email:t@example.com", 5).split()
    status, body = post(base, GOOD, key)
    assert status == 200 and body["answers"]["ate"]["noul"] == 0.7
    sent, client = SENT[0]
    assert sent == {"model": "ews-0.6", "state": GOOD["state"], "questions": GOOD["questions"]}
    assert client == f"api:{key_id}"
    row = logs(gateway)[-1]
    assert row["status"] == 200 and row["key_id"] == key_id and "state" not in row


def test_沒key_錯key_停用的key都擋而且有記(api):
    gateway, base = api
    key_id, key = gateway.newkey("tester", "discord:t", 5).split()
    assert post(base, GOOD)[0] == 401
    assert post(base, GOOD, "ews_wrong")[0] == 401
    gateway.main(["revoke", key_id])
    assert post(base, GOOD, key)[0] == 401
    assert SENT == []
    assert [r["status"] for r in logs(gateway)] == [401, 401, 401]


def test_每日上限(api):
    gateway, base = api
    _, key = gateway.newkey("tester", "ig:t", 2).split()
    assert [post(base, GOOD, key)[0] for _ in range(3)] == [200, 200, 429]
    assert len(SENT) == 2


@pytest.mark.parametrize("bad", [
    {"state": "", "questions": GOOD["questions"]},
    {"state": "x", "questions": {}},
    {"state": "x", "questions": {"q": {"type": "essay", "instructions": "?"}}},
    {"state": "x", "questions": {"q": {"type": "choice", "instructions": "?"}}},
    {"model": "gpt-9", "state": "x", "questions": GOOD["questions"]},
])
def test_格式不對直接回400_不送上游(api, bad):
    gateway, base = api
    _, key = gateway.newkey("tester", "threads:t", 5).split()
    status, body = post(base, bad, key)
    assert status == 400 and body["error"]["message"]
    assert SENT == []


def test_外部一次一發_忙的時候回429(api):
    gateway, base = api
    _, key = gateway.newkey("tester", "email:t", 10).split()
    SLOW["seconds"] = 1.0
    results = []
    threads = [threading.Thread(target=lambda: results.append(post(base, GOOD, key)[0])) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [200, 429]
