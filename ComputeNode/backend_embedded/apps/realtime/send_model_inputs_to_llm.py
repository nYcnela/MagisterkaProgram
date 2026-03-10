from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


def call_llm_server(llm_url: str, rec: Dict[str, Any], timeout_s: float = 30.0) -> Optional[Dict[str, Any]]:
    payload = json.dumps(
        {
            "instruction": rec.get("instruction", ""),
            "input": rec.get("input", ""),
        }
    ).encode("utf-8")
    url = llm_url.rstrip("/") + "/generate"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        print(f"[ERR ] LLM unavailable: {exc}")
        return None
    except Exception as exc:
        print(f"[ERR ] LLM call failed: {exc}")
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Send model_inputs JSONL to local LLM server and save feedback JSONL.")
    ap.add_argument("--in-jsonl", type=Path, required=True, help="Path to input JSONL with {instruction,input}.")
    ap.add_argument("--out-jsonl", type=Path, required=True, help="Path to output JSONL with feedback results.")
    ap.add_argument("--llm-url", required=True, help="Base LLM URL, e.g. http://127.0.0.1:8000")
    ap.add_argument("--timeout-s", type=float, default=30.0, help="HTTP timeout for one request.")
    ap.add_argument("--limit", type=int, default=0, help="Optional number of lines to process (0 = all).")
    args = ap.parse_args()

    if not args.in_jsonl.exists():
        raise FileNotFoundError(f"Missing input JSONL: {args.in_jsonl}")

    args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    args.out_jsonl.write_text("", encoding="utf-8")

    lines = args.in_jsonl.read_text(encoding="utf-8").splitlines()
    total = 0
    ok = 0
    t0 = time.monotonic()

    with args.out_jsonl.open("a", encoding="utf-8") as out_f:
        for i, ln in enumerate(lines, start=1):
            if args.limit > 0 and total >= args.limit:
                break

            ln = ln.strip()
            if not ln:
                continue

            try:
                rec = json.loads(ln)
            except Exception as exc:
                print(f"[WARN] line={i} invalid JSON: {exc}")
                continue

            total += 1
            fb = call_llm_server(args.llm_url, rec, timeout_s=args.timeout_s)
            if fb is None:
                out = {
                    "line_no": i,
                    "instruction": rec.get("instruction", ""),
                    "input": rec.get("input", ""),
                    "error": "llm_call_failed",
                }
            else:
                ok += 1
                out = {
                    "line_no": i,
                    "instruction": rec.get("instruction", ""),
                    "input": rec.get("input", ""),
                    **fb,
                }
            out_f.write(json.dumps(out, ensure_ascii=False) + "\n")
            print(f"[{total}] score={out.get('score')} latency={out.get('latency_s')}s")

    dt = time.monotonic() - t0
    print(f"[DONE] processed={total} ok={ok} failed={total - ok} elapsed={dt:.2f}s")
    print(f"[DONE] saved: {args.out_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
