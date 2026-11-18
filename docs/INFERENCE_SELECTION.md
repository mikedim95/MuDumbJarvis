# Local inference selection and provenance

Phase 14 found repeated reasoning/tool mistakes with the existing 3.8B Mistral
profile: prose in place of delegation, a dependency inside task text, unsupported
research claims, mistyped UUID paths and failed tests. These failures remain in
JAR-44/JAR-45/JAR-46 history and were not accepted as completed work. A separate
terminal integration issue retained a shell cwd; the plugin now supplies the
current authenticated issue directory on every terminal call.

The installed `pentagi-whiterabbitneo:7b` definition supports tools. An operator
probe produced a grounded three-framework comparison and a valid structured
delegation selection. This was generated text/tool selection only, not task
execution. Its existing four-thread configuration was preserved. Ollama's
OpenAI-compatible endpoint ignored the requested temporary thread override;
actual runner arguments remained `-t 4`.

One new JARVIS-only alias, `jarvis-hermes-qwen24:7b`, reuses those installed 7.6B
weights and tool template. It sets 24 threads, batch 1024, context 65536 and a
768-token output ceiling. No weights were downloaded. All nine original model
names, sizes and manifest digests remain identical. AIGoat/PentAGI containers and
configuration checksums remain identical. The source model's four-thread
parameters remain unchanged.

The same probe measured comparison latency 230.066 → 73.359 seconds and identical
139-token structured tool-selection output 81.389 → 20.415 seconds. Context size
and cold-loading conditions differ; these are probe measurements, not a causal
CPU benchmark or a complete employee-task speed claim. The actual alias runner
uses 24 threads and one parallel sequence. See the two
`phase14-model-probe-*.json` receipts and `phase14-qwen-profile-created.json`.

All active JARVIS clients select one common alias: CEO, Research, Software and
separate direct chat. One model runner serializes their inference calls. Role
contexts and tools stay separate. Never select different aliases concurrently
and then claim their per-model `-np 1` limits form a single shared slot.
Other applications' configurations are outside JARVIS control.

The model selection is operator configuration, separate from hiring authority.
The existing frozen employee templates, tool/credential/resource boundaries,
profile hashes and native human hiring approval are preserved. A signed
model-only record stores company, local model/digest, context, CPU policy and
selection time in native agent metadata. Its signature uses a separate domain
under the existing server-side signing key. It grants no tool, host, external
or hiring permission.

Employees hold only their existing derived proof keys and an immutable copy of
the public inference selection in container environment. Their authenticated
native record must match that copy. Version 3 execution receipts record the
actual selected model and inference record, alongside the frozen base-profile
model/hash. The CEO validates the operator signature, native selection history,
actual worker run and attachment bytes. Historical base-model receipts remain
valid; selecting a new model does not rewrite old results. The HUD displays the
effective model, and approval details retain the baseline profile separately.

An operator selection is prepared with:

```sh
python3 deploy/select_inference_model.py jarvis-hermes-qwen24:7b
```

`--apply` refuses active/queued work, backs up private configuration and native
metadata, pauses the eligible existing employees, changes only the two original
Hermes model defaults, records the selection natively and leaves employees
paused. No task, hire or inference is created. Stop the existing operator timer
while applying a reviewed change:

```sh
XDG_RUNTIME_DIR=/run/user/1000 systemctl --user stop jarvis-employee-runtimes.timer
python3 deploy/select_inference_model.py jarvis-hermes-qwen24:7b --apply
python3 deploy/staffing.py --apply --refresh-idle-runtimes
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d --no-deps hermes hermes-ceo jarvis
docker restart jarvis-hermes-tls
```

Managed workers resume only after authenticated health and native adapter checks
pass. Verify CEO/direct-chat authenticated health, test the CEO native adapter,
then resume the paused CEO through Paperclip and restart the operator timer.
Do not resume after a failed check. The deployment receipts distinguish health
from real execution; Phase 14 workflows must still pass before full acceptance.

For rollback, use the same selection procedure with
`jarvis-hermes-aigoat24:3b`, after owned work finishes. This preserves inference
configuration history and authenticates both old and newer completed results.
Do not overwrite old native approvals or restore metadata by deleting history.
Private emergency backups are under `.runtime/backups/phase14/inference-*`;
model-default YAML backups are beside the original files. Retain task history,
workspaces, artifacts and both aliases; do not replay completed tasks.

Read-only preservation audit after the explicitly recorded alias addition:

```sh
python3 tests/live_preservation.py --run --phase 14 \
  --allow-added-model jarvis-hermes-qwen24:7b
```

It requires every original manifest to match exactly and allows only the named
new JARVIS alias. It does not silently accept arbitrary additions.
