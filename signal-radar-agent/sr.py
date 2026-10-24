#!/usr/bin/env python3
"""Signal Radar agent CLI: the only way the Cowork agent talks to Signal Radar.

Reads {"app_url": ..., "token": ...} from ~/.signal-radar/agent.json (chmod 600), so the token
never appears in the agent's prompt or transcript. Standard library only.

  sr.py config
  sr.py session start
  sr.py session end --pages 23 [--notes "..."] [--warning "LinkedIn said: ..."]
  sr.py signals <file.json | ->            # {"items": [...]}
  sr.py next [--limit 5]
  sr.py result <action_id> sent|skipped|failed [--text "..."] [--detail "..."]
                [--connection connected|pending|none] [--in-conversation]

Every command prints the JSON response. Exit code 0 = ok, 1 = API error, 2 = usage/config error.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

CONFIG_PATH = os.path.expanduser(os.environ.get("SR_CONFIG", "~/.signal-radar/agent.json"))
TIMEOUT = 60


def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except FileNotFoundError:
        sys.exit(f"config not found: {CONFIG_PATH} (see signal-radar-agent/README.md)")
    if not cfg.get("app_url") or not cfg.get("token"):
        sys.exit(f"{CONFIG_PATH} needs app_url and token")
    return cfg


def call(method: str, path: str, body: dict | None = None) -> dict:
    cfg = load_config()
    url = cfg["app_url"].rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {cfg['token']}",
        "Content-Type": "application/json",
        "User-Agent": "signal-radar-agent/0.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode() or "{}"
            return {"http_status": resp.status, **json.loads(raw)} if raw.strip().startswith("{") \
                else {"http_status": resp.status, "data": json.loads(raw)}
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:500]
        print(json.dumps({"ok": False, "http_status": err.code, "error": detail}))
        sys.exit(1)
    except urllib.error.URLError as err:
        print(json.dumps({"ok": False, "error": f"network: {err.reason}"}))
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="sr.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("config")

    s = sub.add_parser("session")
    s.add_argument("phase", choices=["start", "end"])
    s.add_argument("--pages", type=int, default=0)
    s.add_argument("--notes", default="")
    s.add_argument("--warning", default=None)

    sg = sub.add_parser("signals")
    sg.add_argument("file", help="JSON file with {\"items\": [...]}, or - for stdin")

    n = sub.add_parser("next")
    n.add_argument("--limit", type=int, default=5)

    r = sub.add_parser("result")
    r.add_argument("action_id")
    r.add_argument("status", choices=["sent", "skipped", "failed"])
    r.add_argument("--text", default=None, help="exact text that was sent")
    r.add_argument("--detail", default=None)
    r.add_argument("--connection", choices=["connected", "pending", "none"], default=None)
    r.add_argument("--in-conversation", action="store_true")

    a = p.parse_args(argv)

    if a.cmd == "config":
        out = call("GET", "/api/public/agent/config")
    elif a.cmd == "session":
        body = {"phase": a.phase, "pages_viewed": a.pages, "notes": a.notes}
        if a.warning:
            body["warning"] = a.warning
        out = call("POST", "/api/public/agent/session", body)
    elif a.cmd == "signals":
        raw = sys.stdin.read() if a.file == "-" else open(a.file).read()
        payload = json.loads(raw)
        if isinstance(payload, list):
            payload = {"items": payload}
        if not isinstance(payload.get("items"), list):
            sys.exit("signals payload must be {\"items\": [...]}")
        out = call("POST", "/api/public/agent/signals", payload)
    elif a.cmd == "next":
        out = call("GET", f"/api/public/agent/outreach/next?limit={max(1, min(a.limit, 20))}")
    else:
        observed = {}
        if a.connection:
            observed["connection_status"] = a.connection
        if a.in_conversation:
            observed["already_in_conversation"] = True
        body = {"status": a.status, "observed": observed}
        if a.text is not None:
            body["sent_text"] = a.text
        if a.detail:
            body["detail"] = a.detail
        out = call("POST", f"/api/public/agent/outreach/{a.action_id}/result", body)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
