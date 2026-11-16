# Direct chat provider binding and error handling

**Historical local-provider repair:** the user subsequently requested Codex for
direct chat. The active configuration is now `openai-codex / gpt-6.1-sol`,
enforced on every request and validated against the completed runtime. See
[current minimal AI configuration](MINIMAL_AI.md). Do not apply the local model
binding below to the active demo. The safe error and retry behavior remains.

The reported `Hermes stream error: {"session_id": ...}` was a failed runtime
envelope, not an assistant reply. Two provider identities had diverged:

- The persistent `jarvis-main` session was locked to provider `custom`.
- The direct-chat profile had been changed to `custom:jarvis-local-ollama`.

In the installed Hermes version, resolving the bare stored provider against
that named profile rejected the Docker Ollama endpoint and reported missing
credentials. Rebinding the session to the named alias reached Ollama, but
Hermes then rejected the answer because the actual agent provider normalized
to `custom`, which differed from the confirmed named lock.

The supported compatible configuration aligns the profile, session lock, and
actual runtime on **`custom`**, with the explicit existing local endpoint:

```yaml
model:
  provider: custom
  base_url: http://ollama-models:11434/v1
  # Existing model/default/context settings are retained.
providers:
  jarvis-local-ollama:
    # Existing endpoint and local credential placeholder are retained.
    extra_body:
      max_tokens: 768
```

Only `.runtime/hermes/config.yaml` was changed. The same session
`api_1794464162_4c830cc5` was rebound through the authenticated supported endpoint:

```http
POST /api/sessions/api_1794464162_4c830cc5/model
Content-Type: application/json

{"provider":"custom","model":"jarvis-hermes-aigoat24:3b","model_options":{}}
```

No session was deleted or replaced. Its original 13 messages were retained;
subsequent test turns remain ordinary additional history. Private backups are
under `.runtime/direct-chat-fix/20261116T103124Z/`. The installed model, Ollama
model definitions, 24-thread setting, 65536 context, 768-token bound and shared
inference slot were preserved. The named provider entry remains because Hermes
uses its endpoint match to apply the existing request overrides.

The Paperclip CEO remains on its separate Codex/Hermes profile. Neither task
assignment, employee permissions, nor its issue-scoped execution sessions
changed. PentAGI and AIGoat are unrelated to this repair and were untouched.

## Error display and retry safety

The existing FastAPI client now reports a short safe error plus a reference ID.
Raw stream/runtime objects, provider request details, arbitrary exception text,
and upstream HTTP bodies never become chat replies. Logs retain a reference,
failure class, and selected non-secret diagnostic IDs.

Typed chat accepts success only after a complete, non-interrupted, non-empty
assistant reply. Partial output followed by failure is not accepted as a final
answer. A session is recreated only for an actual HTTP 404 from the session
endpoint; a `404` somewhere inside an execution error cannot trigger replay or
discard history. Other failed or uncertain requests are never retried
automatically. The browser prevents overlapping sends and retains a draft typed
while the previous reply is pending.

## Verification

```sh
# Two actual HUD direct-chat turns, including a contextual follow-up.
# This uses the original session and does not create Paperclip tasks.
python3 deploy/check_direct_chat_fix.py
```

`tests/test_direct_chat_failures.py` covers model-route errors, safe HTTP
failures, partial/interrupted output, redaction, and the exact 404 retry boundary.
Live browser evidence is in `docs/evidence/direct-chat-fixed.json` and its
screenshot. The original failed request and in-place session repair receipts
remain private; no provider envelope is published as a successful response.

The verified HUD test returned `4` in 4.156 seconds and repeated the answer in
4.111 seconds using the same session. Real Hermes runs were
`run_bee7d2c5661a4b6e9c4b8f5da2a4bf42` and
`run_760a8ae35d13444785f653fd3c66f190`. The original history remains; session
message count is now 21 after the diagnostic and successful test turns. The
browser created no Paperclip task and blocked the attempted overlapping send.
343 tests pass on the full working checkout; 326 pass on the exact selected
commit, which leaves earlier unfinished Phase 14 changes outside this repair.

The unrelated pre-existing `/v1/skills` compatibility error is not part of
this fix. It does not route chat or provide inference.

For the historical local configuration, preserve the direct-chat profile's
bare `custom` identity. Changing it back to a named provider can reintroduce the
confirmed Sessions API lock mismatch in this installed version. Worker
`/v1/runs` adapters and the Codex CEO use separate profiles and are unchanged.
