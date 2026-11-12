#!/usr/bin/env python3
"""Opt-in native Ollama timing, independent of Hermes/Paperclip execution proof.

Plan without network or artifacts:
  python3 tests/ollama_benchmark.py
Execute only while other inference clients are idle:
  python3 tests/ollama_benchmark.py --run --threads 4 24 --num-predict 64
Quick three-profile screen before full repeated measurements:
  python3 tests/ollama_benchmark.py --run --threads 4 16 24 --skip-cold --warm-reps 1 --prompt-lines 12 --num-predict 32

This changes request-scoped options and the selected model's memory residency.
It never creates/pulls models, changes server settings, or drops the OS cache.
Official fields: https://docs.ollama.com/api/generate and /api/ps.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
import socket
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = "You are a technical writer completing a controlled local inference benchmark. Follow the supplied writing task."
def make_prompt(lines):
    return "\n".join([
    "Read the fixed engineering records below. They are synthetic benchmark data, not facts about this host.",
    "Explain reliable local service operation using the records. Write at least 250 words of continuous technical prose.",
    "Discuss bounded requests, cache reuse, explicit state, measurement, and recovery. Do not use tools, make API calls, or invent local observations.",
    *[f"Record {number:02d}: A local service reads a fixed cache and returns a compact status value for each queued request."
      for number in range(1, lines + 1)],
    "Now write the technical explanation. Continue with concrete engineering details rather than a greeting or a readiness acknowledgement.",
])
COUNTERS = ("total_duration", "load_duration", "prompt_eval_count", "prompt_eval_cached_count",
            "prompt_eval_duration", "eval_count", "eval_duration")


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def rate(count, duration_ns):
    return round(count * 1e9 / duration_ns, 4) if count is not None and duration_ns and duration_ns > 0 else None


def plan(args):
    return {
        "model": args.model, "endpoint": args.endpoint, "threads": args.threads,
        "num_ctx": args.num_ctx, "num_predict": args.num_predict,
        "seed": args.seed, "temperature": args.temperature, "warm_reps": args.warm_reps,
        "num_batch": args.num_batch, "docker_runner_container": args.docker_container,
        "prompt_sha256": sha(args.prompt), "system_sha256": sha(SYSTEM),
        "prompt_words": len(args.prompt.split()), "prompt_lines": args.prompt_lines,
        "prompt_token_target": [800, 1200] if args.prompt_lines == 36 else ([300, 500] if args.prompt_lines == 12 else None),
        "prompt_token_note": "Approximate before execution; actual rendered count is recorded from Ollama, never invented.",
        "request_timeout_seconds": args.timeout,
        "cold_order": [] if args.skip_cold else args.threads,
        "warm_order": args.threads * args.warm_reps,
        "generate_requests": len(args.threads) * ((0 if args.skip_cold else 1) + 2 * args.warm_reps),
        "warm_setup": "A one-token generation of the same prompt immediately precedes every warm sample; setup is recorded separately and excluded from aggregates.",
        "cold_definition": "Selected model unloaded before each cold sample; OS file cache remains intact.",
        "concurrency": "Synchronous requests and a nonblocking repository lock; unrelated clients must be idle. This script cannot police other Ollama clients.",
        "scope": "Native inference timings only. No tools, agents, orchestration, or fake task-execution evidence.",
    }


class Client:
    def __init__(self, endpoint, timeout):
        self.endpoint, self.timeout = endpoint, timeout
        # Ignore proxy environment variables for a reproducible direct endpoint.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self, path, body=None, metadata=False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.endpoint + path, data=data,
                                     headers={"Content-Type": "application/json"})
        started = time.monotonic()
        try:
            with self.opener.open(req, timeout=min(self.timeout, 30) if metadata else self.timeout) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise RuntimeError("Ollama response exceeded the 8 MiB benchmark limit")
            result = json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Ollama {path} returned HTTP {exc.code}; no automatic retry") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError("Ollama request timed out; server may still be running it. Benchmark stops without retries or further generation.") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise RuntimeError(f"Ollama {path} returned an invalid/error result")
        return result, time.monotonic() - started


def model_entry(client, model):
    tags, _ = client.request("/api/tags", metadata=True)
    matches = [item for item in tags.get("models", []) if item.get("name") == model or item.get("model") == model]
    if not matches:
        raise RuntimeError("Requested model is not installed under the exact supplied name; no pull attempted")
    if len(matches) != 1 or not matches[0].get("digest"):
        raise RuntimeError("Installed model identity is ambiguous or has no digest")
    return matches[0]


def running_snapshot(client, model, digest, num_ctx):
    ps, _ = client.request("/api/ps", metadata=True)
    models = ps.get("models", [])
    matching = [item for item in models if (item.get("name") == model or item.get("model") == model)
                and item.get("digest") == digest]
    if len(matching) != 1:
        raise RuntimeError("Selected model is no longer uniquely resident with the pinned digest")
    item = matching[0]
    observed = item.get("context_length")
    if observed is not None and observed != num_ctx:
        raise RuntimeError(f"Observed context_length={observed} differs from requested num_ctx={num_ctx}")
    return {key: item.get(key) for key in ("name", "digest", "size", "size_vram", "context_length")}


RUNNER_FLAGS = {
    "num_thread": ("--threads", "--n-threads", "-t"),
    "context_size": ("--ctx-size", "--n-ctx", "-c"),
    "batch_size": ("--batch-size", "--n-batch", "-b"),
    "micro_batch_size": ("--ubatch-size", "--n-ubatch", "-ub"),
    "parallel": ("--parallel", "-np"),
    "gpu_layers": ("--gpu-layers", "--n-gpu-layers", "-ngl"),
}


def runner_projection(text, model_blob):
    """Expose only target-runner PID and allowed numeric flags, never raw args."""
    projected = []
    if not model_blob:
        return projected
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit() or model_blob not in parts[1]:
            continue
        argv = shlex.split(parts[1])
        if not any("runner" in arg or "llama" in arg for arg in argv):
            continue
        row = {"pid": int(parts[0])}
        for key, aliases in RUNNER_FLAGS.items():
            for index, token in enumerate(argv):
                for alias in aliases:
                    value = None
                    if token == alias and index + 1 < len(argv):
                        value = argv[index + 1]
                    elif token.startswith(alias + "="):
                        value = token[len(alias) + 1:]
                    elif alias.startswith("-") and not alias.startswith("--") and token.startswith(alias):
                        value = token[len(alias):]
                    if value is not None and re.fullmatch(r"-?\d+", value):
                        row[key] = int(value)
        projected.append(row)
    return projected


def observe_runner(container, model_blob):
    if not container:
        return {"status": "not_requested"}
    if not model_blob:
        return {"status": "unavailable", "reason": "Target model blob could not be identified from /api/show"}
    try:
        result = subprocess.run(["docker", "top", container, "-eo", "pid,args"],
                                text=True, capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}
    if result.returncode:
        return {"status": "unavailable", "reason": "docker_top_failed", "exit_code": result.returncode}
    rows = runner_projection(result.stdout, model_blob)
    return {"status": "observed" if rows else "unavailable", "runners": rows,
            "source": "docker top target runner, numeric flag projection only; no environment or model path retained"}


def summarize(samples, threads):
    result = []
    for thread in threads:
        warm = [s for s in samples if s["phase"] == "warm" and s["num_thread"] == thread]
        cold = [s for s in samples if s["phase"] == "cold" and s["num_thread"] == thread]
        metrics = {}
        for key in ("generation_tokens_per_second", "wall_seconds", "load_seconds"):
            values = [s[key] for s in warm if s.get(key) is not None]
            metrics[key] = {"median": round(statistics.median(values), 4),
                            "min": min(values), "max": max(values)} if values else None
        result.append({"num_thread": thread, "warm_samples": len(warm), "cold_sample_ids": [s["id"] for s in cold],
                       "warm_metrics": metrics})
    return result


def run(args):
    document = {"schema_version": 1, "started_at": utc_now(), "status": "running", "plan": plan(args),
                "prompt": args.prompt, "system": SYSTEM, "samples": [], "warnings": [],
                "documentation": ["https://docs.ollama.com/api/generate", "https://docs.ollama.com/api/ps",
                                  "https://github.com/ollama/ollama/blob/main/api/types.go"]}
    output = Path(args.output)
    client = Client(args.endpoint, args.timeout)
    executed = False
    model_blob = None

    def save():
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(json.dumps(document, indent=2) + "\n")
        temporary.replace(output)

    def sample(phase, thread, repetition=0, predict=None):
        nonlocal executed
        row = {"id": len(document["samples"]) + 1, "phase": phase, "num_thread": thread,
               "repetition": repetition, "started_at": utc_now()}
        document["samples"].append(row)
        options = {"num_ctx": args.num_ctx, "num_thread": thread, "seed": args.seed,
                   "temperature": args.temperature, "num_predict": args.num_predict if predict is None else predict}
        if args.num_batch is not None:
            options["num_batch"] = args.num_batch
        row["request_options"] = options
        executed = True
        response, wall = client.request("/api/generate", {"model": args.model, "system": SYSTEM, "prompt": args.prompt,
                                                         "stream": False, "keep_alive": args.keep_alive,
                                                         "options": options})
        if response.get("done") is not True or response.get("remote_host") or response.get("remote_model"):
            raise RuntimeError("Generation did not finish locally")
        row.update({key: response.get(key) for key in COUNTERS})
        cached = response.get("prompt_eval_cached_count")
        count = response.get("prompt_eval_count")
        uncached = max(0, count - cached) if isinstance(count, int) and isinstance(cached, int) else None
        row.update({"finished_at": utc_now(), "wall_seconds": round(wall, 6),
                    "load_seconds": round(response.get("load_duration", 0) / 1e9, 6),
                    "generation_tokens_per_second": rate(response.get("eval_count"), response.get("eval_duration")),
                    "generation_tokens_per_wall_second": round(response.get("eval_count", 0) / wall, 4),
                    "prompt_reported_count_per_eval_second": rate(count, response.get("prompt_eval_duration")),
                    "uncached_prompt_eval_count": uncached,
                    "uncached_prompt_tokens_per_second": rate(uncached, response.get("prompt_eval_duration")),
                    "cache_counter_available": "prompt_eval_cached_count" in response,
                    "done_reason": response.get("done_reason"),
                    "response": response.get("response", ""), "response_sha256": sha(response.get("response", "")),
                    "running_model": running_snapshot(client, args.model, document["model"]["digest"], args.num_ctx),
                    "effective_runner": observe_runner(args.docker_container, model_blob)})
        target = document["plan"]["prompt_token_target"]
        if phase in ("cold", "warm_setup") and target and isinstance(count, int) and not target[0] <= count <= target[1]:
            document["warnings"].append(f"Sample {row['id']} rendered {count} input tokens, outside proposed target {target}; exact same prompt was retained.")
        save()
        for runner in row["effective_runner"].get("runners", []):
            if runner.get("num_thread") is not None and runner["num_thread"] != thread:
                raise RuntimeError(f"Effective runner threads={runner['num_thread']} differs from requested num_thread={thread}; profile comparison stopped")
        print(f"{phase} threads={thread} rep={repetition} wall={wall:.2f}s eval_tps={row['generation_tokens_per_second']} cached={cached}", flush=True)

    try:
        version, _ = client.request("/api/version", metadata=True)
        entry = model_entry(client, args.model)
        show, _ = client.request("/api/show", {"model": args.model}, metadata=True)
        if args.model.endswith(":cloud") or show.get("remote_host") or show.get("remote_model"):
            raise RuntimeError("This benchmark requires a locally installed model, not a cloud model")
        for line in show.get("modelfile", "").splitlines():
            if line.upper().startswith("FROM "):
                reference = line.split(None, 1)[1].strip().strip('"')
                basename = Path(reference).name
                if basename.startswith("sha256-"):
                    model_blob = basename
        document.update({"ollama_version": version.get("version"),
                         "host": {"cpu_count": os.cpu_count(), "python_version": sys.version.split()[0]},
                         "model": {key: entry.get(key) for key in ("name", "digest", "size", "details")},
                         "model_configuration": {"parameters": show.get("parameters"),
                                                 "template_sha256": sha(show.get("template", "")),
                                                 "system_sha256": sha(show.get("system", "")),
                                                 "modelfile_sha256": sha(show.get("modelfile", ""))}})
        for thread in ([] if args.skip_cold else args.threads):
            executed = True
            unloaded, wall = client.request("/api/generate", {"model": args.model, "stream": False, "keep_alive": 0})
            if unloaded.get("done") is not True:
                raise RuntimeError("Selected model unload was not acknowledged")
            document["samples"].append({"id": len(document["samples"]) + 1, "phase": "unload",
                                        "num_thread": thread, "wall_seconds": round(wall, 6),
                                        "done_reason": unloaded.get("done_reason")})
            sample("cold", thread)
        for repetition in range(1, args.warm_reps + 1):
            for thread in args.threads:
                sample("warm_setup", thread, repetition, predict=1)
                sample("warm", thread, repetition)
        if model_entry(client, args.model)["digest"] != document["model"]["digest"]:
            raise RuntimeError("Selected model digest changed during benchmarking")
        document.update({"status": "completed", "finished_at": utc_now(),
                         "summary": summarize(document["samples"], args.threads),
                         "comparison_scope": "Controlled native generation only; a separate real Paperclip/Hermes tool task must verify any selected profile.",
                         "cache_interpretation": "Null cached count means unsupported/unreported, never zero. Reported prompt-count rate can include cached tokens; uncached rate is supplied only when its counter is available.",
                         "thread_observation": "num_thread is requested in each request. Optional Docker observations record actual target-runner numeric flags after completion while keep_alive retains it; /api/ps records actual context. Missing flags are unknown, not confirmed. A known thread mismatch stops comparison."})
        save()
        print(f"Recorded actual native timings: {output}", flush=True)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        document.update({"status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
                         "finished_at": utc_now(), "error": str(exc),
                         "retry_policy": "No automatic generation retry or continuation after an error; inspect server activity before another run."})
        if executed:
            save()
        print(document["error"], file=sys.stderr, flush=True)
        return 130 if isinstance(exc, KeyboardInterrupt) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default=os.environ.get("JARVIS_TEST_MODEL", "jarvis-hermes:3b"))
    parser.add_argument("--threads", type=int, nargs="+", default=[4, 24])
    parser.add_argument("--num-ctx", type=int, default=65536)
    parser.add_argument("--num-batch", type=int, default=None, help="Optional common runner batch size, e.g. 1024 for an explicit AIgoat-style comparison")
    parser.add_argument("--docker-container", default=None, help="Optionally inspect this local Ollama container after each request; records only target PID and numeric runner flags")
    parser.add_argument("--num-predict", type=int, choices=(32, 64, 128), default=64)
    parser.add_argument("--prompt-lines", type=int, default=36, help="36 records target roughly 800–1200 tokens; 12 records target a 300–500-token screening prompt")
    parser.add_argument("--skip-cold", action="store_true", help="Skip runner-cold samples for a quick warm-only screen; warm setup is still measured separately")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--warm-reps", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--keep-alive", default="10m")
    parser.add_argument("--output", default=str(ROOT / "docs/evidence/ollama-speed.json"))
    parser.add_argument("--run", action="store_true", help="Actually issue model load/generation requests; otherwise print the offline plan only")
    args = parser.parse_args()
    args.endpoint = args.endpoint.rstrip("/")
    endpoint = urllib.parse.urlsplit(args.endpoint)
    if endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        parser.error("Endpoint must be an HTTP(S) base URL without embedded credentials, query, or fragment")
    if args.docker_container and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.docker_container):
        parser.error("Docker container must be a simple container name or ID")
    if args.num_batch is not None and args.num_batch < 1:
        parser.error("num_batch must be positive when supplied")
    if not args.threads or len(set(args.threads)) != len(args.threads) or any(thread < 1 for thread in args.threads):
        parser.error("Threads must be unique positive integers")
    if not 1 <= args.warm_reps <= 10 or not 0 < args.timeout <= 1800 or args.num_ctx < 2048 or not 1 <= args.prompt_lines <= 128:
        parser.error("Use 1–10 warm repeats, 1–128 prompt lines, timeout in (0,1800], and context >=2048")
    args.prompt = make_prompt(args.prompt_lines)
    if not args.run:
        print(json.dumps({"status": "not_executed", **plan(args)}, indent=2))
        return 0
    lock_path = ROOT / ".runtime/ollama-benchmark.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another benchmark holds the repository lock; no requests issued")
        return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
