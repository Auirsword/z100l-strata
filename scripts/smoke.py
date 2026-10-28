#!/usr/bin/env python3
"""Check the real local server without printing generated conversation text."""
import argparse
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_json(url, timeout=3):
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '18080')}")
    parser.add_argument("--wait", type=int, default=0)
    parser.add_argument("--generate", action="store_true", help="also send one short synthetic text request")
    args = parser.parse_args()
    deadline = time.monotonic() + args.wait
    while True:
        try:
            health = get_json(args.url.rstrip("/") + "/health")
            if health.get("loaded") and health.get("status") == "ok":
                break
            error = "engine is not loaded"
        except (HTTPError, URLError, TimeoutError, ValueError, ConnectionError) as exc:
            error = str(exc)
        if time.monotonic() >= deadline:
            raise SystemExit(f"health check failed: {error}")
        time.sleep(min(5, max(1, deadline - time.monotonic())))
    print(json.dumps({"health": health.get("status"), "model": health.get("model"),
                      "max_context": health.get("max_context"), "images": health.get("images")}, ensure_ascii=False))
    if args.generate:
        body = {"model": "Qwen3.8-Flash-Next-IQ3_S", "stream": False, "max_tokens": 16,
                "temperature": 0, "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "user", "content": "Reply with exactly Z100L_OK."}]}
        request = Request(args.url.rstrip("/") + "/v1/chat/completions",
                          data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        started = time.monotonic()
        with urlopen(request, timeout=600) as response:
            result = json.load(response)
        if not result.get("choices") or not result.get("usage"):
            raise SystemExit("generation did not return choices and usage")
        print(json.dumps({"generation_http": 200, "seconds": round(time.monotonic() - started, 3),
                          "usage": result["usage"], "timings": result.get("timings")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
