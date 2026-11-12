# Local Ollama performance tuning

Status on 2026-11-12: **the clean native rerun completed: 24 threads measured
2.44 times the four-thread decode throughput. A real worker task took
80.089 seconds on the copied profile versus 352.719 seconds on the control.**
Fresh JAR-35 self execution and JAR-36/JAR-37 delegation passed through the
actual HUD. Five-service restart, separate direct-chat regression and explicit
AIgoat restoration also passed; all final delivery checks passed.
Earlier contended timings
are superseded for tuning decisions. The copied profile has been selected in
both runtime files for the verified functional workflow. AIgoat's
temporary runtime pause was explicitly restored at 11:47:44.873 UTC.
The AIgoat reference
inspection made metadata requests only and changed no AIgoat service/model.
Subsequent inference ran against JARVIS's Ollama instance; its idle-host
assumption was not established for the earlier measurements.
The accepted CEO workflow is recorded in [CEO_ORCHESTRATION.md](CEO_ORCHESTRATION.md).

## AIgoat reference: configured values and loaded execution differ

The AIgoat Compose project is `/home/kali/AIGoat/docker`, using
`docker-compose.yml` and `docker-compose.override.yml`. Its Ollama, backend and
frontend containers are `aigoat-ollama-1`, `aigoat-backend-1` and
`aigoat-frontend-1`. AIgoat has a separate Ollama instance from JARVIS.

The source of backend settings is the mounted
`/home/kali/AIGoat/docker/config.yml`, not the repository's other
`config/config.yml` copy. The latter has a different timeout. Only sanitized
inference values are retained in
[ollama.aigoat.reference.json](../deploy/ollama.aigoat.reference.json).

| Setting | Mounted configuration / fresh backend resolution | Saved model defaults | Observed loaded runner |
| --- | --- | --- | --- |
| Model | `ministral-3:3b` | Same name; Mistral3 3.8B Q4_K_M | Same loaded model |
| Ollama server | 0.40.11 | — | Native ELF `/usr/bin/ollama` launching `llama-server` |
| CPU threads | `num_thread: 16` | 16 | **`-t 24`** |
| Context | `num_ctx: 8192` | 8192 | `-c 8192` |
| Concurrent requests | Server `OLLAMA_NUM_PARALLEL=1` | — | `-np 1` |
| Batch | No explicit application setting found | No explicit saved setting | `-b 1024`, `-ub 1024` |
| Output limit | `max_tokens: 768`, sent as `num_predict: 768` | 768 | Generation limit is per request; not a runner CLI flag |
| Temperature | **0.7 sent by the application** | **0.15** | No generation sampled during inspection |
| Sampling | `top_p: 0.9`, `top_k: 40`, `think: false` | Other defaults not inferred | No generation sampled |
| Keep alive | Application and server: `24h` | — | Loaded model observed |
| Request timeout | 600 seconds | — | Application deadline, not inference speed |
| Loaded models | Server `OLLAMA_MAX_LOADED_MODELS=1` | — | One CPU-loaded model; `size_vram: 0` |

The active runner also has `--load-mode none`, `--flash-attn auto`,
`--context-shift`, `--keep 4`, `--offline` and `--no-jinja`.
Its template and projector contents were not copied or printed. A process's
total OS-thread count is not its inference-thread setting.

**Configured 16 and observed 24 must remain separate facts.** The backend's
fresh `get_settings()` and `_request_options(None)` resolve to 16; they are not
a memory snapshot of the already running backend process. No request was sent
to reconcile the discrepancy or force an AIgoat runner reload. The caller/load
that selected 24 threads and batch 1024 has not been established. This is not
evidence that `num_thread` is ignored.

The source paths establish the application behavior:

- `docker/config.yml:16`: model; lines 18–22: thinking, threads, context,
  keep-alive and timeout; lines 43–46: chat sampling and output limit.
- `docker/docker-compose.yml:41`: one parallel request.
- `docker/docker-compose.override.yml:5`: loaded-model limit, default context
  and keep-alive on lines 5–7.
- `app/core/config.py:162`: mounted config loader; `get_settings` caches its
  result per process at line 179.
- `app/services/ollama_client.py:98`: client constructor; line 122 merges
  request options and unconditionally supplies configured threads/context.
  Line 297 constructs the client from the settings. Generation uses native
  `/api/generate`; chat uses native `/api/chat`.

## Hardware and execution scope

The Xen guest exposes 32 logical CPUs, with a reported topology of 16 virtual
sockets, two cores each and one thread per core. `nproc` is 32, effective CPU
affinity is `0-31`, and AVX2/FMA are available. The physical host's core count
and scheduling contention are unknown; this is not proof of 32 dedicated
physical cores.

Both AIgoat's and JARVIS's Ollama containers have no Docker CPU quota or CPU
pinning. AIgoat's effective cgroup reports `cpu.max: max 100000`, CPUs `0-31`
and no container memory limit. No NVIDIA device nodes or GPU device requests
were present; the loaded AIgoat model reported zero VRAM usage. `/dev/dri`
exists, but that alone does not establish GPU inference.

## Supported controls

`num_thread` controls CPU threads in a model runner. Native Ollama requests can
supply it inside `options`, and a separately named Modelfile model can store
it with `PARAMETER num_thread`. Ollama 0.40.11 passes an explicitly positive
thread count to `llama-server -t`, and `num_batch` becomes `-b` and `-ub`.
Runner options are compared when reusing a loaded model; a changed setting can
cause a reload. [Pinned API options](https://github.com/ollama/ollama/blob/v0.40.11/api/types.go#L529),
[thread launch](https://github.com/ollama/ollama/blob/v0.40.11/llm/llama_server.go#L407),
[batch launch](https://github.com/ollama/ollama/blob/v0.40.11/llm/llama_server.go#L570),
[reload guard](https://github.com/ollama/ollama/blob/v0.40.11/server/sched.go#L1328)

`OLLAMA_NUM_PARALLEL` is a server setting for simultaneous requests per model,
not CPU threads. More slots increase context memory allocation; 24 slots is
not a way to make one CEO use 24 cores. This work must not change the shared
server's concurrency, loaded-model or context settings to tune one agent.
[Official concurrency documentation](https://docs.ollama.com/faq#how-does-ollama-handle-concurrent-requests)

Hermes v0.23.1 uses Ollama's OpenAI-compatible endpoint. Its custom provider
has explicit `ollama_num_ctx` handling, but no supported main-agent
`num_thread`/`num_batch` option bridge was found. Its `/v1/runs` request options
decode reasoning and service tier rather than arbitrary native Ollama options.
Ollama's compatibility request schema does not expose general `options`; its
documentation recommends a new Modelfile model for served context settings.
Do not assume unknown Hermes JSON keys take effect.
[Pinned Hermes provider](https://github.com/NousResearch/hermes-agent/blob/v0.23.1/plugins/model-providers/custom/__init__.py#L56),
[Hermes request options](https://github.com/NousResearch/hermes-agent/blob/v0.23.1/gateway/platforms/api_server_request_options.py#L13),
[Ollama compatibility](https://docs.ollama.com/api/openai-compatibility#setting-the-local-context-size)

## Copied profile and explicit runtime selection

The original JARVIS alias is `jarvis-hermes:3b`, with `num_ctx 65536`,
`num_thread 4` and `temperature 0.1`. It and all eight pre-existing model
definitions are preserved. The original CEO milestone and fresh-install source
defaults use that alias. The operator selected the copied 24-thread alias in
the two existing runtime files; fresh JAR-35/JAR-36 functional, restart and
direct-chat checks now verify that selection.
The additional `jarvis-hermes-aigoat24:3b` profile was created from existing
layers only, using [Modelfile.hermes.aigoat](../deploy/Modelfile.hermes.aigoat):

```text
FROM jarvis-hermes:3b
PARAMETER num_thread 24
PARAMETER num_batch 1024
PARAMETER num_predict 768
PARAMETER top_k 40
PARAMETER top_p 0.9
```

It inherits the established 65,536-token context, template, weights and 0.1
temperature. It is now the verified operator-selected runtime model; source
example defaults still use the original four-thread alias.
No existing model was overwritten, and no cloud model was added. The native
thread comparison below used the original alias with per-request thread
overrides and batch 1024 fixed for every profile; it did not measure the new
alias's combined 768-token/profile behavior.

AIgoat's 8K context is unsuitable as a blind replacement for the established
65K Hermes context. Its 0.7 sampling temperature changes agent behavior and is
not a CPU optimization. A 600-second HTTP timeout does not speed inference.
Its 768-token cap can shorten responses but can also truncate tool calls or
reports; any such cap needs a separate correctness test. A 24-hour keep-alive
reduces cold loads while retaining memory, and must not be copied globally.
Do not import CTF prompts, credentials, tool permissions or unrestricted access.

## Clean native rerun

[ollama-speed-clean.json](evidence/ollama-speed-clean.json) contains the new
10:18:05–10:21:59 UTC run. Its independently recomputed
[clean summary](evidence/ollama-speed-clean-summary.json) strictly verifies the
same prompt/system hashes, original model digest, seed 42, temperature 0.1,
65,536 context, batch/micro-batch 1024 and 32 generated tokens for every warm
measurement. Actual runner flags confirm four or 24 threads and one request
slot. The original saved model configuration matches its earlier snapshot.
There are three alternating warm samples per profile; prior contended data
is not pooled into these statistics.

| Threads | Warm samples | Median decode tokens/s | Decode range | Median warm wall time | Median uncached setup prefill tokens/s |
| --- | --- | --- | --- | --- | --- |
| 4 | 3 | 5.0524 | 4.6752–5.7205 | 6.6034 s | 14.9997 |
| 24 | 3 | 12.3117 | 11.7934–13.6541 | 2.7220 s | 100.6624 |

Within this sampled low-contention native workload, 24-thread median decoding
was **2.44 times faster**, median warm wall time was **2.43 times shorter**,
and uncached setup prefill throughput was **6.71 times higher**. The result
supersedes the earlier contended comparison. This is a short fixed-length
inference measurement, not yet a measured improvement in real agent completion
time or answer quality.

The quiet-host gate, approved temporary AIgoat pause and competing-resource
monitor are recorded below. Corrected cgroup monitoring observed no competing
inference while sampling; physical-host exclusivity and another client of the
same Ollama server cannot be proven from CPU counters alone. One-token setup
generations are excluded from decode statistics; the prefill column uses only
the setup's 404 uncached prompt tokens. Warm samples reuse 403 of 404 prompt
tokens and deliberately stop at 32 generated tokens.

## Earlier native measurements: superseded under contention

The user reported another process using agent/host resources. A subsequent
read-only snapshot confirmed heavy inference activity in both AIgoat and main
Ollama, with the host almost fully busy. The earlier timings remain real
recorded observations, but **their comparison is invalid for deciding which
thread profile is faster**. No setting will be promoted from these results.
Raw timing/sample fields are preserved for audit. Five historical contended
artifacts now carry explicit `post_measurement_review` metadata marking them
`superseded_for_performance_decisions`; summary source-hash references were
updated and pre-review hashes retained separately. Clean measurements were not
changed. This correction supersedes their provisional performance
interpretation.

[ollama-speed-screen.json](evidence/ollama-speed-screen.json) screened 4, 16
and 24 threads once; [ollama-speed-repeat.json](evidence/ollama-speed-repeat.json)
then ran two further alternating 4/24 measurements. The combined raw-counter
calculation is [ollama-speed-summary.json](evidence/ollama-speed-summary.json).
The aggregate asserts the same prompt/system hashes, seed 42, temperature 0.1,
65,536 context, batch/micro-batch 1024, model digest and 32 generated tokens per
warm sample. Actual runner flags confirmed each thread count, context and
single request slot. Saved original model configuration snapshots match.

| Threads | Warm samples | Median decode tokens/s | Decode range | Median warm wall time | Median uncached setup prefill tokens/s |
| --- | --- | --- | --- | --- | --- |
| 4 | 3 | 5.5505 | 5.1294–5.6025 | 6.0015 s | 22.9176 |
| 16 | 1 | 1.0658 | One sample | 31.1514 s | 53.1834 |
| 24 | 3 | 0.2813 | 0.2509–0.3565 | 117.6967 s | 42.4946 |

The raw recorded ratios are 19.73 for four-thread versus 24-thread median
decode throughput and 1.85 for 24-thread versus four-thread uncached setup
prefill. These potentially contended observations **cannot be attributed to
thread count** and do not establish that 24 threads makes the model or agents
slower. They will not be combined with a clean rerun's aggregate. Prompt
processing and generation remain separate measurements.

Each warm request followed a one-token setup on the same prompt. Setup
requests had 404 uncached prompt tokens; warm requests reused 403 of 404 prompt
tokens. The setup's one-token generation counters are excluded from decoding
statistics because their near-zero reported evaluation duration is not a
meaningful generation rate. Warm prompt-count rates include cached tokens and
must not be called uncached prefill throughput. Loading time is recorded
separately; the setup is not an OS-cache-cleared cold-start benchmark.

Every measured warm output stopped at the deliberate 32-token limit. This
controls output length, not answer quality. Fixed seeds did not produce
identical prose across thread settings. Three short samples per 4/24 profile
and one 16-thread sample do not establish a universal optimum; VM host
contention remains outside complete control.

Native `/api/chat` exposes `total_duration`, `load_duration`,
`prompt_eval_count`, `prompt_eval_cached_count` when present,
`prompt_eval_duration`, `eval_count` and `eval_duration`. Compute uncached
prompt throughput and generated-token throughput from these nanosecond
counters, and retain wall-clock time and termination reason.
[Official chat metrics](https://docs.ollama.com/api/chat)

Ollama 0.40.11 does not expose a separate prompt-thread parameter through
`api.Options`, Modelfile or its launch environment. Its pinned llama.cpp
`b11845` supports CLI `-tb`/`--threads-batch`, but no environment mapping for
that option; Ollama passes only `-t`. A profile cannot combine four decoding
threads with sixteen prompt threads through supported alias parameters.
[Pinned llama.cpp arguments](https://github.com/ggml-org/llama.cpp/blob/b11845/common/arg.cpp#L1519),
[Ollama's pinned backend version](https://github.com/ollama/ollama/blob/v0.40.11/LLAMA_CPP_VERSION)

## Matched real-worker comparison and verified CEO compatibility

### Capacity and queue limits

The actual selected-model runner uses **`-np 1`**, as confirmed by the native
and worker flag observations. The CEO and worker have separate authenticated
Hermes runtimes and issue contexts but use the same model alias and share that
one inference slot. Another agent or direct-chat request can wait in the
model queue or encounter its Hermes runtime's admission limit. Several
Paperclip tasks can exist without their LLM calls executing simultaneously.

`num_thread 24` is CPU parallelism within an inference request; it does not
create 24 agent slots. These results are serial-workload measurements, not a
multi-user throughput benchmark. No shared `OLLAMA_NUM_PARALLEL` or server
concurrency setting was increased. Other model runners can have their own
capacity; this describes the observed shared JARVIS runner, not a general
one-human-user restriction.

The clean matched control is JAR-19,
`f8e8dae4-c661-4f7a-bd2e-29e9b8d3dfec`, using the original four-thread model.
Its real execution succeeded in **352.719 seconds** with a verified signed
record of all nine models. Two model calls consumed 5,941 input and 190 output
tokens: the first reported 2,331 input/9 output tokens in 171.1 seconds, the
second 3,610 input/181 output in 173.2 seconds. These are actual execution
measurements, not a quality pass: prose-contract limitations are retained in
the worker evidence.

The clean candidate is JAR-20,
`945af4e0-eb2c-4383-8cd3-d51f3b66279f`, on a fresh issue/session with the
same task prompt, authorized tools and nine-model inventory. Its execution
succeeded under the same temporary pause with valid signed tool evidence.
It took **80.089 seconds**, an observed **4.4041-fold reduction in run wall
time** versus the 352.719-second control. The native speed ratio is not
substituted for these real execution measurements.

| Measured case | Canonical Paperclip run | Run wall time | Model calls | Input/output tokens |
| --- | --- | --- | --- | --- |
| JAR-19 / original four-thread alias | `c88d6e57-e04d-4417-98e2-f3052ea00bf9` | 352.719 s | 2 | 5,941 / 190 |
| JAR-20 / copied 24-thread profile | `4707b1b0-d724-4357-b3b4-1e3a00550cc4` | 80.089 s | 2 | 5,967 / 144 |

The candidate's provider calls reported 44.2 and 32.2 seconds, with 2,344/9
and 3,623/135 input/output tokens respectively. Provider-call time includes
queueing, prompt evaluation and decoding; reliable native per-call stage
durations are not exposed in these Hermes records. Canonical cached-token
zero does not prove a cache miss: the second call reports cache reads in the
provider metrics. The actual served models are verified through Hermes
runtime/call evidence; Paperclip's normalized usage model field is `unknown`.

Both issues have the same canonical HUD/Paperclip identity and succeeded
worker runs, with all nine model values in real signed tool records. The
candidate passed the numeric-count and under-60-word checks; both profiles
failed the exact first-three-name/byte presentation contract. This is verified
execution with output limitations, not a complete prose-quality pass.
Evidence: [control](evidence/agent-speed-clean-control4.json),
[candidate and comparison](evidence/agent-speed-clean-candidate24.json),
[read-only observer](evidence/agent-speed-clean-observer.json).

The actual control runner was observed with `-t 4`, `-c 65536`, `-b 2048`,
`-ub 2048` and `-np 1`. The original saved model has no explicit batch or
output-limit parameter; its served batch default must not be inferred from
the native test's request overrides. The copied candidate specifies 24 threads,
batch/micro-batch 1024 and an output cap of 768, with the same 65K context and
inherited 0.1 temperature. Therefore this real-worker test measures the
**whole configuration-copy outcome**, including the batch/output settings,
not pure thread-count causality. The native test held both thread profiles at
batch 1024 and 32 output tokens to isolate that separate comparison. Retain
actual token counts, tool proof and report quality for both worker runs.
Inventory is stable at the original eight definitions plus the new ninth
experimental alias.

The superseded earlier control is JAR-17,
`4125a6d4-133a-4767-a137-d09d2f62ffb4`, using the original four-thread model.
Its verified worker execution took 309.474 seconds with two model calls,
5,951 input tokens and 229 output tokens. The signed tool record correctly
contained nine models, but the prose reported four and omitted exact byte
sizes; it did not pass the requested report contract. Its timing is also
potentially contended. The earlier candidate JAR-18,
`c7dd6cc0-741d-463c-aa8c-ce46de14a185`, is not accepted as a clean comparison.
Fresh matched runs must follow the resource gate below. A direct worker comparison is
not a fresh CEO-to-worker acceptance run. The accepted CEO milestone remains
the separate JAR-14/JAR-15/JAR-16 evidence.

Paperclip supports per-issue
`assigneeAdapterOverrides.adapterConfig.payloadTemplate.model`, and Hermes
native `/v1/runs` accepts that model selection. This permits matched isolated
issues without altering global agent defaults. Preserve other existing
`payloadTemplate` fields because Paperclip merges the outer adapter config
shallowly. Use new sessions: a persisted session model can outrank a request
override. Verify the actual served model and runner flags, not the requested
model's echoed name alone.
[Paperclip Hermes adapter](https://github.com/paperclipai/paperclip/blob/d69631b01b9c658f80bf8bed389863dce82643e1/packages/adapters/hermes/src/gateway/server/execute.ts#L393),
[Hermes per-request selection](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server#per-request-model-selection)

This is one matched real task pair under sampled low contention. The candidate
generated fewer output tokens and used a different batch/output profile, so
the observed 4.4041 ratio is a whole-profile task result, not a universal agent
speedup or an isolated thread effect. The selected profile passed the final
fresh CEO UI/dispatch/delegation/result compatibility and restart checks.
Historical accepted JAR-14/15/16 evidence remains the original
four-thread baseline, archived separately in `ceo-before-tuning.json`.

The first copied-profile CEO compatibility cycle, JAR-21/JAR-22, is **not
accepted**. The inventory-only JAR-21 unnecessarily delegated to child JAR-23.
Real worker execution and native continuation worked, but that did not satisfy
the minimum-team policy. These attempts must be retained as rejected
compatibility evidence; they cannot establish final profile acceptance.

A text-only policy clarification was checked against 82 existing CEO tests and
has now been deployed after both rejected graphs became terminal. It requires
a direct self plan/tool for inventory-only work
without an explicit independent operator/reviewer requirement; employee
availability alone is not a delegation reason. Explicit two-role work still
uses the existing worker. The deployed update includes `deploy/CEO_POLICY.md`,
the CEO tool instructions, the runtime SOUL copy and bootstrap instructions;
the CEO restarted healthy. That stage's current-source suite passed **111 tests**
with three upstream warnings. It was exercised by the subsequent JAR-25/JAR-26
cycle under the same 24-thread profile. Routing, permissions and native
scheduling were unchanged. Acceptance was still unverified at that stage;
neither those rejected graphs nor source tests counted as a pass. The later
JAR-35/JAR-36 cycle below establishes the final accepted behavior.

The next fresh cycle, JAR-25/JAR-26, is also **not accepted**. JAR-25 recorded
two explicit self-plan handler errors before delegating to child JAR-27.
The actual tool contract was inconsistent: text was described as optional,
while the handler required at least ten characters and did not accept the
model's alternate `plan` field. This was a handler-contract failure, not proof
that the faster model/profile is inherently incompatible with CEO policy.

The corrected handler is now **deployed**. It accepts a string `text` or
`plan` alias. Only when the model explicitly chooses `self` and omits its
rationale does it record the real objective plus existing authorized tool
scope as a clearly labeled **runtime-generated** plan. It does not invent a
model rationale, select an agent, execute tools, create evidence or schedule
tasks. Invalid/missing decisions, nonstrings, oversized inputs and missing
delegate/hire rationale remain rejected.

The complete current-source suite passed **121 tests**. Both runtime containers
restarted healthy after the owned JAR-25/JAR-26 cleanup, retaining the selected
24-thread model. Old cycle evidence remains rejected and retained. A new
actual-HUD harness then exercised fresh JAR-29/JAR-30. No cloud provider or
upstream core change is involved.

That paired cycle is **not accepted**. JAR-29
(`eeb52003-acef-4a34-98cf-45ffe585919e`) called the inventory gate before a
plan existed. The gate correctly performed no HTTP request, but returned a
successful-looking `status: not_executed` payload with misleading next-step
guidance. The model wrote waiting prose instead of recording the required
plan, and finalization correctly left the issue blocked. JAR-30 and worker
child JAR-31 did complete real delegation/execution/native continuation; their
success does not substitute for the failed simple objective.

The inventory gate contract is now corrected and **deployed** in the plugin's
`__init__.py`, with updated tests: a denied call returns a real **error**,
explicitly says no asynchronous work/result is pending and directs the
caller to the required authorized next step. The same 121-test suite passes,
the CEO restarted healthy after JAR-30 became terminal, and runtime identity,
permissions, source model/profile and native scheduling remain unchanged.
No plan, tool execution or evidence is automatically synthesized by this gate.
Exact actual tool-call/response evidence is retained in
[ceo-tool-contract-mismatches.json](evidence/ceo-tool-contract-mismatches.json)
and the rejected-cycle stage files.

A further fresh actual-HUD JAR-32/JAR-33 cycle started at 11:15 UTC on the
selected 24-thread profile. It is **not accepted**: JAR-32
(`48560754-910f-4521-b5c9-ad4078efef24`) made a real direct inventory-tool
choice, received the correctly deployed gate error, then ended with prose
instead of a plan-tool call. Read-only session inspection confirms two model
calls and one tool call, below the eight-turn budget; no forced toolless
budget summary caused the result. JAR-33's separate real delegation graph is
later completed, but cannot substitute for the failed simple case.

A symmetric **atomic self-plan/read contract is now deployed**, after
**131 passing tests** with three existing warnings. Both runtime containers
restarted and the bootstrap policy was synchronized. When a validated current CEO actually invokes
the local inventory tool, with **no recorded plan and no child issues**, that
real tool selection is itself the explicit self-execution decision. The
handler persists a clearly labeled runtime-generated objective/tool scope
in Paperclip **before** the HTTP read. This matches the existing atomic
delegate action, whose model-selected assignment scope is persisted before
creating its child issue.

This contract does not parse prose, route by objective keywords,
invent a model rationale or manufacture a `paperclip_ceo` tool call. A recorded
delegate/hire decision or any child issue retains the error/no-HTTP boundary.
No hook initiates a tool automatically. The model still chooses direct work
or delegation through its actual tool selection. This removes a redundant
interface step that rejected the model's real authorized read choice.

JAR-33 finished its separate delegation graph, while JAR-32 remains blocked;
the paired cycle stays rejected. **Fresh JAR-35/JAR-36 functional browser
acceptance passed** on the same selected 24-thread profile. JAR-35
`44a371b4-603a-4f13-9952-4940ec4e54d1` is done with actual direct-tool self
selection, no child, and a substantive inventory visible in the HUD.

JAR-36 `0ea710dd-98ac-456f-93ea-41e03be73d7d` is done after its model selected
and scoped existing JARVIS-01, creating JAR-37
`ac83a32e-e476-4648-b615-dbe2cdbe7665`. Worker run
`d95e85c8-68dc-4e6f-bf4d-2bccb82bf18e` succeeded with valid issue-bound signed
proof. Paperclip natively woke CEO continuation
`d3599b2f-2ec4-4779-ba08-9df1a8fdef33`; authenticated preflight delivered the
verified child results at 11:35:01.715 UTC, and the CEO wrote a substantive
final report. Both canonical statuses and visible reports passed actual-HUD
checks, browser refresh preserved them, and the roster stayed at two.
`docs/evidence/ceo-browser.json` is the current authoritative browser evidence.

All nine exact model names and byte sizes are retained in canonical tool-data
appendices. The model's prose is imperfect: JAR-35 mis-copied one long-tag byte
value, JAR-36 shortened that name, and some descriptive metadata is unsupported.
The functional pass verifies real execution and persistent delegation, not
unqualified correctness of every generated statement. The five-service restart
preserved the exact completed graph and full history-ID set with zero new
objectives, and actual browser `--resume` passed. Separate direct-chat and
AIgoat restoration checks also passed. This acceptance is functionality
verification, not another timing comparison.

## Profile selection and rollback

`deploy/select_ollama_profile.py` validates an already installed local,
tool-capable alias and the preserved 65K runtime configuration. By default it
reports a dry run. With `--apply` it backs up both existing runtime files and
atomically changes only their `model.default` values. Provider, endpoint,
context, tools, permissions and credentials retain their settings. The
operator applied this helper after a dry run and restarted the two Hermes
runtimes for the new selection.

From the project root, select the copied profile with:

```sh
python3 deploy/select_ollama_profile.py jarvis-hermes-aigoat24:3b
python3 deploy/select_ollama_profile.py jarvis-hermes-aigoat24:3b --apply
docker compose -f deploy/compose.yaml restart hermes hermes-ceo
```

Wait for active work to finish before changing either runtime. To roll back to
the preserved original four-thread alias:

```sh
python3 deploy/select_ollama_profile.py jarvis-hermes:3b
python3 deploy/select_ollama_profile.py jarvis-hermes:3b --apply
docker compose -f deploy/compose.yaml restart hermes hermes-ceo
```

The existing original model remains installed. Fresh installation source
defaults retain it; the helper is the explicit operator step selecting a
copied profile for existing runtime files. Per-issue session model selections
can retain an earlier model, so compatibility checks use fresh objectives.

### Existing direct-chat model and history

An existing Hermes session can retain its old model despite a changed runtime
default. The first actual direct-chat regression returned HTTP 200 and visible
READY through the original four-thread session; the expected-model mismatch is
retained in `direct-chat-sticky-model-diagnostic.json`.

The operator then used Hermes's supported
`POST /api/sessions/{session_id}/model` endpoint to select
`jarvis-hermes-aigoat24:3b` with the existing custom provider. Wait for the
session to be idle before changing its model lock; changing runtime defaults
alone does not override an existing lock. No history reset,
inference or provider-configuration change was part of that migration. All
11 projected client messages (oldest order, including compacted history), their
count and SHA-256 were identical before/after, and the same session ID remained.
This comparison excludes hidden/rewound raw database columns. The next actual
HUD chat turn verified the selected alias/provider, HTTP 200, visible READY,
authentication/WebSocket behavior, task/CEO-session isolation and response/DOM
secret checks. The response included extra prose before READY; exact one-word
compliance is not claimed. See
[model migration receipt](evidence/direct-chat-model-migration.json),
[passing browser regression](evidence/direct-chat-regression.json) and the
[pinned supported handler](https://github.com/NousResearch/hermes-agent/blob/v0.23.1/gateway/platforms/api_server.py#L3246).

## Required resource gate before retry

At 10:09:41 UTC, three two-second host samples showed only 0.9–1.6% idle CPU,
load averages about 51.5/48.0/38.8 on 32 vCPUs and 0.02–0.03% steal. Two
`llama-server` processes each consumed roughly 13–15 CPU cores. Docker's
snapshot attributed about 1,336% of one core to `aigoat-ollama-1` and 1,517%
to main `ollama`. This is direct evidence of contention, not merely a high
historical load average. Process arguments, prompts and credentials were not
collected in this resource report.

At 10:10:35 UTC Paperclip listed no active runs and both Hermes runtimes
reported `active_runs: 0` and `gateway_busy: false`. Yet a 10:10:49 snapshot
still showed about 99% host busy, AIgoat Ollama at 1,359% and main Ollama at
1,492%. Orchestrator/runtime idleness does not prove that an upstream model
request has stopped. A loaded but CPU-idle model is also distinct from active
inference.

The rerun must enforce and retain a sustained preflight window, rather than
assuming the repository's benchmark lock excludes other clients:

- Confirm no unrelated active/queued Paperclip or Hermes turns and no
  competing Ollama requests/CPU-heavy runners, including other containers.
- Record interval CPU idle/busy, steal and I/O wait, runnable/load counts,
  process **names only**, container CPU usage, available memory and swap
  pressure. Use a documented low-contention threshold throughout the window.
- Do not stop external workloads. Wait for them to finish or report the gate
  blocked. Only the operator may resolve unrelated running work.
- Monitor contention during every measurement, attributing the expected
  benchmark runner separately. Reject a sample if another heavy inference
  job, significant steal or memory pressure overlaps it; a quiet preflight
  alone cannot validate a later busy sample.
- Collect a new matched sequence with the same model/context/prompt and
  generation budget. Keep these new samples separate from the provisional
  files. Verify actual tools and report quality on the real-worker tasks.

The initial busy-host gate failed. After the runtime actions below,
[ollama-clean-gate.json](evidence/ollama-clean-gate.json) passed a fresh
20.699-second window: all five samples had 87.58–89.33% CPU idle,
0.206–0.282% steal and no heavy active inference. Both Ollama containers
reported 0% CPU, both Hermes runtimes were idle and Paperclip had no active or
queued runs. The recorded preflight limits require at least 85% idle, no more
than 1% steal/I/O wait, no process over one CPU core, no inference process over
5% of one core and at least 12 GiB available memory.

A read-only monitor samples competing work every 15 seconds into
`.runtime/ollama-clean-cgroup-monitor.jsonl`. It separates main Ollama's expected
benchmark CPU from other inference and host work using container cgroup
cumulative CPU counters, including runner children that exit during reloads.
The initial PID-based monitor remains in
`.runtime/ollama-clean-cpu-monitor.jsonl` for audit; its apparent external-CPU
spikes during runner exits are ambiguous and superseded by cgroup accounting.
The corrected monitor's review thresholds are
18% of whole-host CPU for non-main work, 5% of one core for another inference
process, 1% steal/I/O wait, 12 GiB available memory, and the temporary AIgoat
pause remaining in effect. These thresholds are recorded with the samples;
they do not identify another client sharing the same main Ollama server.
The completed clean native and worker measurements are recorded above.
Monitoring covered the final CEO compatibility and direct-chat tests. Brief startup
activity outside a measured model run must be kept distinct from contention
overlapping a performance sample.

## Explicitly approved runtime interruption and temporary pause

The user explicitly approved interrupting AIgoat's current generation.
The operator verified the model runner belonged to `aigoat-ollama-1` and sent
SIGTERM only to that child. AIgoat subsequently resubmitted work, so the
operator temporarily paused that one container for the clean benchmark. The
operator also restarted only `jarvis-hermes` to close the lingering upstream
request from the acknowledged-cancelled JARVIS trial; it returned healthy.

AIgoat's container identity/start time and saved configuration/model definitions
remain unchanged. Its runtime was deliberately interrupted and temporarily
paused; it must not be described as wholly untouched or uninterrupted.
The operator initially installed a 45-minute automatic resume guard, then
extended it for final contract verification. The actual marker has been read:
`automatic_resume_at` is `1794484529.260326`, corresponding to
**11:55:29 UTC** (100 minutes from the original pause). The guard is tracked by
`.runtime/aigoat-benchmark-pause.json` and
`.runtime/aigoat-resume-guard.py`. The operator explicitly restored AIgoat at
**11:47:44.873 UTC**, before the fallback deadline: same container ID and start
time, running and unpaused, marker removed, guard stopped and version probe
exit 0. No saved configuration/source/model was changed, and success of its
interrupted external job is not claimed. See
[aigoat-restored.json](evidence/aigoat-restored.json). The automatic guard was a
fallback, and is no longer active. Read-only monitoring did not resume or stop
workloads.

## Preservation evidence

[aigoat-reference.json](evidence/aigoat-reference.json) records pre-tuning
container IDs/start times/image IDs, hashed container configurations, selected
source-file hashes, the saved model-parameter hash, model digest/template hash
and the observed runner settings. It contains no prompts or secrets. The
container hash is SHA-256 of compact sorted JSON containing Docker `Config`,
`HostConfig` and `Mounts`; only the digest is retained.

[ollama-tuning-preservation.json](evidence/ollama-tuning-preservation.json)
contains an actual 10:03:36 UTC comparison: AIgoat's three container identities,
start times, images and normalized configurations; six source-file hashes;
model manifest/parameter/template hashes; and PentAGI/main Ollama container
fingerprints match. The original eight model names and byte sizes match, the
original JARVIS parameters match, and the sole added name is the allowed
experimental alias. Other seven models lack retained individual pre-tuning
parameter/manifest hashes; their parameter equality is not invented. Current
snapshots and old manifest timestamps are retained with that limitation.

Timing contention does not invalidate these configuration comparisons. A
normal AIgoat inference can change runner activity/PID/expiry without changing
saved configuration. The comparison was captured during the earlier candidate
attempt; repeat the read-only preservation check after final tuning if later
configuration actions occur.


## Final resource and preservation receipt

The bounded [resource log](evidence/ollama-clean-resource-monitor.jsonl) and
[summary](evidence/ollama-clean-resource-summary.json) contain 335 cgroup-based
samples through 11:47:32 UTC, with a cutoff at 11:47:37 before AIgoat restoration.
Every sampled competing-inference value was zero while AIgoat was paused.
All 14 review flags remain visible; they record non-main startup/browser host
activity rather than being silently discarded. Segment header timestamps and
sample intervals expose reader rollovers. The earlier native-start interval
relies on the quiet gate and initial process-based observation; this sampled
record does not establish exclusive host/server access. Post-restoration
AIgoat inference is outside the clean window. Only the owned read-only monitor
was stopped, after command/start-time validation.

[Final delivery inspection](evidence/final-delivery-check.json) passed all ten
read-only checks, including exact main Ollama/PentAGI fingerprints, all three
AIgoat container/source fingerprints and unpaused state, preserved original
eight model names/sizes plus the one new alias, selected runtime defaults with
only `model.default` changed, two employees and human hiring approval,
authentication/health, clean upstream core repositories and real-secret text
scan. Seven original models lack individual pre-tuning parameter baselines;
parameter equality is not invented. The text scan does not claim binary OCR.
[Consolidated preservation receipt](evidence/ollama-tuning-preservation-final.json)
binds the initial and final checks by source hashes and distinguishes restored
runtime from unchanged configuration.

The copied profile is selected and the functional/operational verification is
complete. Measurements are limited to the recorded host, model, prompts and
sample sizes; generated prose still needs review. This delivery commit (see
`git log`) records the profile, tool-contract fixes, docs and evidence together.
