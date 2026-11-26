"""本地端到端 smoke。先起 `wrangler dev --local --port 8788`，再跑：

    python3 scripts/smoke_worker.py

默认打 http://127.0.0.1:8788，可用 ARGUS_SMOKE_URL 覆盖。
"""

import http.client
import json
import os
import re
import uuid
from urllib.parse import urlparse

BASE = os.environ.get("ARGUS_SMOKE_URL", "http://127.0.0.1:8788")
_PARSED = urlparse(BASE)
HOST = _PARSED.hostname or "127.0.0.1"
PORT = _PARSED.port or 80
PREFIX = _PARSED.path.rstrip("/")


def call(method, path, body=None, headers=None, cookie=None):
    conn = http.client.HTTPConnection(HOST, PORT, timeout=30)
    h = dict(headers or {})
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        else:
            data = body
    if cookie:
        h["Cookie"] = f"argus_user_v2={cookie}"
    conn.request(method, PREFIX + path, body=data, headers=h)
    res = conn.getresponse()
    raw = res.read()
    status = res.status
    set_cookie = res.getheader("Set-Cookie") or ""
    conn.close()
    try:
        payload = json.loads(raw) if raw else None
    except Exception:
        payload = raw.decode(errors="replace")
    return status, payload, set_cookie


def expect(status, want, label, payload=None):
    assert status == want, f"{label}: expected {want}, got {status}: {payload}"
    print(f"ok {label} ({status})")


def token_of(set_cookie):
    m = re.search(r"argus_user_v2=([^;]+)", set_cookie)
    assert m, f"cookie missing: {set_cookie!r}"
    return m.group(1)


def main():
    status, payload, _ = call("GET", "/api/me")
    expect(status, 401, "guest /api/me", payload)
    status, payload, _ = call("GET", "/api/ping")
    expect(status, 401, "guest /api/ping", payload)

    name = f"smoke{uuid.uuid4().hex[:8]}"
    status, payload, cookie = call("POST", "/api/auth/register",
                                   {"username": name, "password": "pw"})
    expect(status, 200, "register", payload)
    token = token_of(cookie)

    status, payload, _ = call("GET", "/api/me", cookie=token)
    expect(status, 200, "me", payload)
    assert payload["me"]["user"] == name

    status, payload, _ = call("GET", "/api/chat/sessions", cookie=token)
    expect(status, 200, "empty sessions", payload)
    assert payload["sessions"] == []

    status, payload, _ = call("GET", "/api/jobs", cookie=token)
    expect(status, 200, "empty jobs", payload)
    assert payload["jobs"] == []
    status, payload, _ = call("GET", "/api/careers", cookie=token)
    expect(status, 200, "empty careers", payload)
    assert payload["careers"] == []

    status, payload, _ = call("POST", "/api/chat/delete",
                              {"sid": "ghost"}, cookie=token)
    expect(status, 200, "delete ghost", payload)
    status, payload, _ = call("GET", "/api/chat/sessions", cookie=token)
    expect(status, 200, "sessions after delete", payload)
    assert payload["sessions"] == []

    status, payload, _ = call("POST", "/api/chat", b"[]", cookie=token,
                              headers={"Content-Type": "application/json",
                                       "X-Session-Id": "s1"})
    expect(status, 400, "bad chat body", payload)
    status, payload, _ = call("GET", "/api/resumes/..%2Fpersona", cookie=token)
    expect(status, 400, "invalid resume id", payload)

    status, payload, _ = call("GET", "/api/auth/logout", cookie=token)
    expect(status, 405, "logout GET", payload)
    status, payload, _ = call("POST", "/api/auth/logout", cookie=token)
    expect(status, 200, "logout POST", payload)
    status, payload, _ = call("GET", "/api/me", cookie=token)
    expect(status, 401, "me after logout", payload)

    status, payload, cookie = call("POST", "/api/auth/login",
                                   {"username": name, "password": "pw"})
    expect(status, 200, "login", payload)
    token = token_of(cookie)
    status, payload, _ = call("GET", "/api/me", cookie=token)
    expect(status, 200, "me after login", payload)
    assert payload["me"]["user"] == name
    print("SMOKE PASS")


if __name__ == "__main__":
    main()
