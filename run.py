"""Collects raw answers from both providers. Append-only, resumable.

Usage:
    python3 run.py --pass 1 --pilot     # 5 questions, validates the pipeline
    python3 run.py --pass 1             # full pass
    python3 run.py --pass 2             # run a couple of hours later
    python3 run.py --pass 3

Three passes spread over an afternoon rather than three calls in a row: repeats
taken back-to-back only measure decoding randomness, whereas spaced repeats also
capture routing and index variation. The report states which of the two it got,
based on the timestamps recorded here.

Resumability is keyed on (prompt_id, model, condition, pass). Only successful
calls are written, so an interrupted or failed run is simply resumed — no call
is ever paid for twice.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from dotenv import load_dotenv

import config
import prompts

load_dotenv()

# Only these two keys are ever read. Everything else in .env stays untouched.
REQUIRED_KEYS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")

# Keys that must never end up in a public repository. Warned about, not read.
FOREIGN_KEYS = ("SEMRUSH_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "ahrefs_key")

_write_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(record: dict) -> tuple:
    return (record["prompt_id"], record["model_key"], record["condition"], record["pass"])


def load_completed(path) -> set[tuple]:
    """Keys already collected. An interrupted run resumes from here."""
    if not path.exists():
        return set()
    done = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(_key(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                print(f"  advarsel: sprang en ulæselig linje over i {path.name}", file=sys.stderr)
    return done


def append(path, record: dict) -> None:
    with _write_lock:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


# --- Providers ---------------------------------------------------------------
# No system prompt, provider defaults otherwise. Note that provider defaults are
# not the same thing across providers: claude-opus-5 thinks by default. The
# report says so rather than presenting the two as identically configured.


def call_anthropic(model: str, question: str, search: bool) -> dict:
    import anthropic

    client = anthropic.Anthropic(max_retries=config.MAX_RETRIES, timeout=config.REQUEST_TIMEOUT_S)
    kwargs = {
        "model": model,
        "max_tokens": config.MAX_OUTPUT_TOKENS,
        "messages": [{"role": "user", "content": question}],
    }
    if search:
        kwargs["tools"] = [{"type": "web_search_20260209", "name": "web_search"}]

    response = client.messages.create(**kwargs)
    text = "\n".join(block.text for block in response.content if block.type == "text")
    return {
        "text": text,
        "stop_reason": response.stop_reason,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        },
    }


# The built-in web-search tool has been named both ways across SDK versions.
# Try the current name, fall back once, and remember which worked so the whole
# run does not pay for the same discovery repeatedly.
_OPENAI_SEARCH_TOOLS = ["web_search", "web_search_preview"]
_openai_search_tool: list[str] = []


def call_openai(model: str, question: str, search: bool) -> dict:
    from openai import OpenAI

    client = OpenAI(max_retries=config.MAX_RETRIES, timeout=config.REQUEST_TIMEOUT_S)

    def create(tool_type: str | None):
        kwargs = {
            "model": model,
            "input": question,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
        }
        if tool_type:
            kwargs["tools"] = [{"type": tool_type}]
        return client.responses.create(**kwargs)

    if not search:
        response = create(None)
    else:
        candidates = _openai_search_tool or _OPENAI_SEARCH_TOOLS
        last_error: Exception | None = None
        response = None
        for tool_type in candidates:
            try:
                response = create(tool_type)
                if not _openai_search_tool:
                    _openai_search_tool.append(tool_type)
                break
            except Exception as error:  # noqa: BLE001 - fall back on tool-name rejection
                last_error = error
                if "tool" not in str(error).lower():
                    raise
        if response is None:
            raise RuntimeError(f"intet gyldigt websøgnings-værktøjsnavn accepteret: {last_error}")

    status = getattr(response, "status", None)
    usage = getattr(response, "usage", None)
    return {
        "text": response.output_text,
        "stop_reason": status,
        "usage": {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
        },
    }


PROVIDERS = {"anthropic": call_anthropic, "openai": call_openai}


# --- Orchestration -----------------------------------------------------------


def build_jobs(pass_no: int, pilot: bool, done: set[tuple]) -> list[dict]:
    selected = prompts.PROMPTS[:5] if pilot else prompts.PROMPTS
    jobs = []
    for prompt in selected:
        for model, condition in config.cells():
            job = {
                "prompt_id": prompt.id,
                "intent": prompt.intent,
                "question": prompt.text,
                "model_key": model["key"],
                "provider": model["provider"],
                "model": model["model"],
                "condition": condition["key"],
                "search": condition["search"],
                "pass": pass_no,
            }
            if _key(job) not in done:
                jobs.append(job)
    return jobs


def execute(job: dict) -> dict:
    started = time.monotonic()
    result = PROVIDERS[job["provider"]](job["model"], job["question"], job["search"])
    return {
        "ts": _now(),
        "pass": job["pass"],
        "prompt_id": job["prompt_id"],
        "intent": job["intent"],
        "question": job["question"],
        "model_key": job["model_key"],
        "model": job["model"],
        "condition": job["condition"],
        "search": job["search"],
        "text": result["text"],
        "stop_reason": result["stop_reason"],
        "usage": result["usage"],
        "latency_s": round(time.monotonic() - started, 2),
    }


def check_environment() -> None:
    missing = [key for key in REQUIRED_KEYS if not os.getenv(key)]
    if missing:
        print(f"FEJL: manglende nøgler i .env: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    present = [key for key in FOREIGN_KEYS if os.getenv(key)]
    if present:
        print(
            "ADVARSEL: din .env indeholder nøgler, der ikke bruges her:\n"
            f"  {', '.join(present)}\n"
            "  De læses ikke af dette program, men de ligger i den mappe, du pusher fra.\n"
            "  Flyt dem ud af projektet, før du gør repoet offentligt.\n",
            file=sys.stderr,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Indsamler rå svar fra sprogmodellerne.")
    parser.add_argument("--pass", dest="pass_no", type=int, required=True,
                        choices=range(1, config.RUN_PASSES + 1))
    parser.add_argument("--pilot", action="store_true",
                        help="Kør kun de første 5 spørgsmål for at validere pipelinen.")
    args = parser.parse_args()

    check_environment()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)

    done = load_completed(config.RAW_PATH)
    jobs = build_jobs(args.pass_no, args.pilot, done)

    total_for_pass = (5 if args.pilot else len(prompts.PROMPTS)) * len(config.cells())
    print(f"Kørsel {args.pass_no}/{config.RUN_PASSES}{' (pilot)' if args.pilot else ''}")
    print(f"  allerede gennemført: {total_for_pass - len(jobs)}/{total_for_pass}")
    print(f"  tilbage at hente:    {len(jobs)}")
    if not jobs:
        print("Intet at gøre. Kørslen er allerede fuldført.")
        return 0
    print()

    ok = 0
    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENCY) as pool:
        futures = {pool.submit(execute, job): job for job in jobs}
        for index, future in enumerate(as_completed(futures), start=1):
            job = futures[future]
            label = f"{job['prompt_id']} {job['model_key']}/{job['condition']}"
            try:
                record = future.result()
            except Exception as error:  # noqa: BLE001 - record and continue; rerun resumes
                failures.append(f"{label}: {error}")
                print(f"  [{index}/{len(jobs)}] {label}  FEJLEDE")
                continue
            append(config.RAW_PATH, record)
            ok += 1
            truncated = " (AFKORTET)" if record["stop_reason"] in {"max_tokens", "incomplete"} else ""
            print(f"  [{index}/{len(jobs)}] {label}  {record['latency_s']}s{truncated}")

    print(f"\nGemt {ok} svar i {config.RAW_PATH}")
    if failures:
        print(f"\n{len(failures)} kald fejlede. Kør kommandoen igen — kun de manglende hentes:")
        for failure in failures[:10]:
            print(f"  ✗ {failure}")
        if len(failures) > 10:
            print(f"  … og {len(failures) - 10} mere")
        return 1

    if args.pass_no < config.RUN_PASSES:
        print(
            f"\nVent mindst {config.RECOMMENDED_PASS_GAP_HOURS} timer, og kør så:"
            f"\n  python3 run.py --pass {args.pass_no + 1}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
