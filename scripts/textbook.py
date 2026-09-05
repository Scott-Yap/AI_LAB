"""Manage the running backend's single textbook index; avoids a second database writer."""

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    try:
        with urlopen(
            Request(
                "http://127.0.0.1:8000/api/textbook" + path,
                data=body,
                headers={"Content-Type": "application/json"},
            ),
            timeout=180,
        ) as response:
            return json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"Backend error: {exc.read().decode()}") from exc
    except URLError as exc:
        raise SystemExit("Start the AI Lab backend on port 8000 first.") from exc


parser = argparse.ArgumentParser(description=__doc__)
sub = parser.add_subparsers(dest="command", required=True)
index = sub.add_parser("index")
index.add_argument("--force", action="store_true", help="Recompute even when the index fingerprint matches.")
sub.add_parser("status")
search = sub.add_parser("search")
search.add_argument("query")
args = parser.parse_args()
if args.command == "status":
    print(json.dumps(request("/status"), indent=2))
elif args.command == "search":
    results = request("/search", {"query": args.query, "top_k": 5})["results"]
    for result in results:
        print(f"{result['score']:.3f}  {result['chapter']} / {result['section']}  [{result['chunk_id']}]")
elif args.command == "index":
    request("/index?force=" + str(args.force).lower(), {})
    previous = None
    while True:
        status = request("/status")
        state = (status["state"], status.get("progress"))
        if state != previous:
            print(f"{state[0]}  {state[1] or 0}%", flush=True)
            previous = state
        if status["state"] != "indexing":
            if status["state"] == "failed":
                print(status.get("error"), file=sys.stderr)
                sys.exit(1)
            print(f"Ready: {status['chunk_count']} textbook passages.")
            break
        time.sleep(2)
