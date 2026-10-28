#!/usr/bin/env python3
"""Measure upstream prompt/decode timings using synthetic or user-supplied text."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import time
import uuid
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '18080')}")
    parser.add_argument("--model", default="Qwen3.8-Flash-Next-IQ3_S")
    parser.add_argument("--prompt-file", help="text input; only token counts and timings are saved")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--tag", default="local")
    args = parser.parse_args()
    if args.repetitions < 1 or args.max_tokens < 1:
        parser.error("repetitions and max-tokens must be positive")
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
    else:
        prompt = "Explain how a mixture-of-experts model uses memory bandwidth.\n" * 180
    samples = []
    for index in range(args.repetitions):
        # Cold requests deliberately do not reuse the previous exact prompt.
        text = f"benchmark-request-{uuid.uuid4()}\n{prompt}" if not args.prompt_file else prompt
        body = {"model": args.model, "stream": False, "max_tokens": args.max_tokens,
                "temperature": 0, "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "user", "content": text}]}
        request = Request(args.url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        started = time.monotonic()
        with urlopen(request, timeout=1800) as response:
            result = json.load(response)
        elapsed = time.monotonic() - started
        usage = result.get("usage", {})
        timings = result.get("timings", {})
        sample = {"request": index + 1, "wall_s": round(elapsed, 3), "usage": usage,
                  "prompt_per_second": timings.get("prompt_per_second"),
                  "predicted_per_second": timings.get("predicted_per_second"),
                  "prompt_ms": timings.get("prompt_ms"), "predicted_ms": timings.get("predicted_ms")}
        samples.append(sample)
        print(json.dumps(sample, ensure_ascii=False))
    decodes = [s["predicted_per_second"] for s in samples if s["predicted_per_second"] is not None]
    prefills = [s["prompt_per_second"] for s in samples if s["prompt_per_second"] is not None]
    result = {"schema": 1, "tag": args.tag, "created_at": datetime.now(timezone.utc).isoformat(),
              "metric_scope": "upstream per-request timings; means are not aggregate throughput",
              "samples": samples, "mean_single_request_decode_tok_s": statistics.mean(decodes) if decodes else None,
              "mean_single_request_prefill_tok_s": statistics.mean(prefills) if prefills else None}
    destination = Path(os.environ.get("DATA_DIR", str(Path.home() / ".local/share/z100l-strata"))) / "benchmarks"
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.tag.replace("/", "_") + ".json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved timing-only report: {output}")


if __name__ == "__main__":
    main()
