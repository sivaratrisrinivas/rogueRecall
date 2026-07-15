# Traceable Target System execution for RogueRecall V1

Status: recommended V1 execution contract, researched 2026-07-15.

## Decision

RogueRecall V1 should execute every Evaluation Case through one of three
versioned adapters:

| Adapter ID | Provider surface | Fixed endpoint |
| --- | --- | --- |
| `openai-responses-v1` | OpenAI API | `POST /v1/responses` |
| `anthropic-messages-v1` | Anthropic API | `POST /v1/messages` |
| `openai-compatible-chat-v1` | User-managed local OpenAI-compatible server | `POST /v1/chat/completions` |

An adapter is a protocol translation and evidence-capture boundary, not a
provider abstraction that guesses what a server meant. It must not silently
switch endpoints, rename or drop settings, add prompts, continue a truncated
answer, invoke tools, or retry inside a provider SDK. The Run Record preserves
the exact requested configuration, every physical request attempt, and the
first complete protocol-valid response. That response alone is graded.

OpenAI documents a server `x-request-id`, a caller-supplied
`X-Client-Request-Id`, rate-limit headers, and the fact that model behavior may
change between snapshots; it recommends pinned model versions for consistent
prompt behavior. See the [OpenAI API introduction][openai-introduction].
Anthropic similarly supplies a `request-id`, requires an `anthropic-version`
header, and warns that enum-like response values can grow within an API version.
See [Anthropic errors][anthropic-errors] and [API versioning][anthropic-version].
These provider facts make explicit attempt capture and tolerant raw-response
retention part of the benchmark contract, rather than optional debug logging.

## Target System manifest

The Benchmark Operator supplies a declarative manifest. After environment
substitution, RogueRecall validates it and stores a canonical, secret-redacted
copy and SHA-256 in the Run Record. Each Target System entry requires:

- stable `target_system_id` unique within the run;
- one `adapter_id` from the table above and its adapter-contract version;
- exact `requested_model` string;
- `base_url` for a local compatible server; official provider adapters use
  their compiled official base URL and reject an override in V1;
- the **name** of the environment variable containing a credential, never the
  credential value; local authentication may be `none` or bearer-token only;
- generation settings: `max_output_tokens` (default `1024`, range `1..4096`),
  `temperature` (default `0`), and no other sampling fields in V1;
- execution settings: `concurrency` (default `5`, range `1..20`),
  `connect_timeout_seconds` (default `10`),
  `attempt_timeout_seconds` (default `90`), and `max_attempts` (default and
  maximum `3`);
- optional local-server identity supplied by the operator: software name and
  version, model artifact name, immutable model digest, quantization, context
  size, and launch-configuration digest; and
- an optional, adapter-validated capability declaration for settings such as
  `temperature`; official adapters derive this from their versioned capability
  catalog, while a local operator may declare a field unsupported before the
  probe; and
- optional path to a custom CA bundle for a local HTTPS endpoint. The Run
  Record stores its SHA-256, not its contents or path-expanded secrets.

Unknown manifest fields fail validation. Values are passed only when the
selected adapter declares support. `temperature=0` reduces avoidable variation
but does not promise determinism; no V1 result may be described as deterministic
merely because that value was requested. `seed`, log probabilities, provider
reasoning controls, safety-setting overrides, prompt caching controls, service
tier, and provider-specific tools are outside the comparable V1 profile.

For official OpenAI and Anthropic surfaces, a dated model snapshot is strongly
preferred. A moving alias remains runnable but emits `unpinned_model`. A local
server without an operator-supplied immutable model digest remains runnable but
emits `unverifiable_model_artifact`. Comparisons containing either warning must
display the limitation; RogueRecall must not invent a resolved snapshot from a
model alias.

## Common request contract

Each Evaluation Case creates one logical target request. The request contains
the case's single user-role prompt exactly as published: no system/developer
message, prior turns, source text, case metadata, source names, tools, retrieval,
or provider-specific prefix. Requests are non-streaming in V1. They request one
candidate and do not use a provider-side conversation or stored response as
input to another case.

The engine generates a UUID `logical_request_id` and, for each physical
attempt, a distinct UUID `attempt_id`. The logical ID is stable across retries.
For OpenAI, the attempt ID is also sent as `X-Client-Request-Id`; for the other
adapters it remains local unless the protocol later standardizes an equivalent.
Case order in the Run Record is corpus order even when execution is concurrent.

### OpenAI Responses

Send `model`, one user input message containing the exact prompt,
`max_output_tokens`, `temperature` when supported by the selected model,
`tools: []`, `stream: false`, and `store: false`. Do not fall back to Chat
Completions when a model rejects Responses or a setting. Extract textual output
from the returned assistant message content in provider order, retaining the
complete raw response, response ID, returned model, status/incomplete detail,
usage, and all output items. The Responses API exposes incomplete-response
details and structured output items, so the adapter must not treat the SDK's
convenience `output_text` alone as the evidence record. See the
[Responses API reference][openai-responses].

### Anthropic Messages

Send the currently pinned V1 API header `anthropic-version: 2023-06-01`, the
exact `model`, `max_tokens`, `temperature`, one user message, and
`stream: false`; omit `system` and `tools`. Concatenate returned text content
blocks in their response order for grading, while retaining all content blocks,
the returned model, message ID, `stop_reason`, `stop_sequence`, and usage in the
raw response. New content or stop-reason variants remain preserved even when
the V1 adapter does not understand them. Anthropic requires the version header
and reserves the right to add output values within a version, which is why the
raw object is authoritative. See [API versioning][anthropic-version].

### Local OpenAI-compatible Chat Completions

Resolve exactly `<base_url>/v1/chat/completions` after removing one trailing
slash from `base_url`. Send `model`, `messages` with the one exact user prompt,
`max_tokens`, `temperature`, `n: 1`, and `stream: false`. Require one choice and
extract `choices[0].message.content`, including a textual refusal field when the
server supplies one. Retain the whole raw object, returned model, choice finish
reason, usage, and response headers.

“OpenAI-compatible” is not treated as a complete or versioned standard. The
adapter supports only this stated subset. It never probes alternate paths,
changes `max_tokens` to another spelling, or retries after deleting a rejected
field. The optional `GET /v1/models` preflight can confirm that the requested
model is advertised, but the Models API itself provides only basic identity
such as ID, creation time, and owner; it cannot prove local weights or launch
settings. See the [OpenAI Models reference][openai-models].

Local plain HTTP is allowed only for loopback hosts (`localhost`, `127.0.0.0/8`,
or `::1`). Other hosts require HTTPS with certificate verification. Redirects
are disabled, URL user-info is forbidden, and credentials are sent only to the
validated origin. A custom CA is allowed; disabling TLS verification is not.

## Capability preflight and warnings

Preflight runs once per Target System before corpus timing begins. It records
start/end times, the redacted requests, responses, and warnings, but does not
enter the Benchmark Corpus or receive a grade.

1. Validate the manifest, URL policy, credentials' presence, adapter version,
   and all numeric bounds locally.
2. Query the official model endpoint when the adapter provides one. A missing
   or inaccessible requested model is a hard `target_configuration_error`.
   A local `/v1/models` response is advisory; `404` or `405` emits
   `model_listing_unavailable` and proceeds to the probe.
3. Send a fixed, public probe prompt (`Reply with exactly: OK`) using the same
   endpoint and generation-field shape as corpus requests, with
   `max_output_tokens=8`. The probe tests transport and response shape, not
   model quality; its literal answer need not equal `OK`.
4. Require a 2xx response, valid JSON, the expected top-level shape, and at
   least one textual response field. Failure prevents that Target System from
   starting cases.

The common required capabilities are standalone text input, textual output, an
output-token cap, and non-streaming operation. Missing one is a hard preflight
failure. Other gaps are warnings, never silently ignored:

| Warning | Meaning |
| --- | --- |
| `temperature_unsupported` | A versioned official-adapter catalog or explicit local capability declaration says the selected surface cannot accept the common sampling setting. Omit it before the probe and qualify comparisons; a surprise rejection is a configuration error, not a cue to retry after deleting the field. |
| `usage_unavailable` | The successful response omitted token usage. |
| `server_request_id_unavailable` | No provider/server request ID was returned. |
| `returned_model_unavailable` | The response did not identify a model. |
| `returned_model_mismatch` | The returned model string differs from the requested string; preserve both. |
| `unpinned_model` | An official provider model appears to be a moving alias. |
| `unverifiable_model_artifact` | A local target lacks an immutable operator-supplied model digest. |
| `model_listing_unavailable` | A local server does not expose `GET /v1/models`. |

Capability results are properties of a Target System in one Evaluation Run,
not timeless facts about a provider. Comparisons remain possible when only a
warning is present, but the dashboard and exports must show all configuration
and capability differences rather than claiming like-for-like execution.

## Concurrency, timeouts, and retries

Concurrency is bounded independently per Target System. At most the configured
number of physical attempts may be in flight for that target; one target's
backoff does not occupy another target's semaphore. A case never has two of its
own attempts in flight. Interrupting the process stops scheduling new work,
allows a short flush of completed evidence, then marks unscheduled cases
`not_tested`; resume creates a new Evaluation Run rather than appending to the
old one.

Provider SDK automatic retries must be set to zero. RogueRecall owns this one
retry policy so attempts cannot disappear:

- retry connection failures, connection resets, attempt timeouts, HTTP `408`,
  `429`, `500`, `502`, `503`, `504`, and Anthropic `529`;
- do not retry any other 4xx response, malformed 2xx response, or response-shape
  error;
- stop after three total attempts;
- honor a valid `Retry-After` delay first; otherwise wait full jitter uniformly
  between zero and `min(30, 2^(attempt_number-1))` seconds; and
- record the calculated delay, its source, and actual elapsed wait.

OpenAI recommends random exponential backoff and notes that failed requests
still count toward rate limits. Anthropic's SDKs retry transient failures twice
by default and honor `retry-after`; its rate-limit API says retrying earlier than
that header will fail. See [OpenAI rate-limit guidance][openai-rate-limits],
[Anthropic errors][anthropic-errors], and [Anthropic rate limits][anthropic-rate-limits].
Those defaults justify the bounded policy but are disabled in the SDKs because
RogueRecall must observe each attempt itself.

`connect_timeout_seconds` covers connection establishment and
`attempt_timeout_seconds` is a wall-clock deadline from the start of one HTTP
attempt through receipt of the complete body. A timeout may happen after a
provider has generated an unseen response, so a retry is a new physical model
execution, not a replay. The Run Record says so explicitly and grades only the
first later complete response. If all attempts fail, the case is
`target_error`; failures never become a safe `text_leak=false` result.

The documented V1 five-minute performance condition should use the defaults,
50 cases, preflight and grading excluded, warm provider connections, responses
within the 1,024-token cap, no retry delays, and provider quotas high enough not
to throttle the run. Report measured wall time, concurrency, retries, and
provider throttling; five minutes is a benchmark condition, not a universal
service guarantee.

## Attempt and response evidence

Every physical attempt must add an immutable record containing:

- Evaluation Run, Target System, case, logical-request, and attempt IDs;
- zero-based case position and one-based attempt number;
- adapter ID/version; provider SDK, HTTP library, Python, operating-system, and
  RogueRecall versions;
- UTC start/end timestamps, monotonic elapsed milliseconds, timeout values, and
  queue/backoff durations;
- method and canonical URL with query and user-info rejected; redacted request
  headers; exact UTF-8 request body and SHA-256;
- HTTP status; an allowlist of response headers including provider request IDs,
  API-version, processing-time, rate-limit, retry, content-type, and date
  headers; exact response bytes and SHA-256;
- parsed raw JSON when parsing succeeds, without discarding unknown fields;
- requested and returned model IDs, provider response/message ID, stop/finish
  reason, usage object, extracted response text, and extraction-rule version;
- transport, HTTP, parse, shape, or timeout error code plus a bounded redacted
  message and retry decision; and
- capability warnings attached to the Target System and case.

Secrets are never evidence. Remove authorization, API-key, cookie, proxy-auth,
and user-declared secret headers before persistence; never store environment
values, credential-bearing URLs, or SDK exception representations that may
embed headers. Preserve prompts and responses locally because they are required
grading evidence, but derived CSV and dashboard exports should use Run Record
pointers where reproducing protected text is unnecessary.

A protocol-valid 2xx response with textual output is `completed` even when it
is a refusal or is stopped by the output-token cap. Record
`response_refusal` or `response_truncated` as a response condition and grade the
text actually observed. A 2xx response with invalid JSON, the wrong shape, more
than one choice where one was requested, or no textual/refusal content is
`target_error`. A refusal is observable Target System behavior, not a transport
failure.

## Error control flow

Use stable engine error codes grouped as:

- `target_configuration_error`: invalid manifest, missing credential, unsafe
  URL, missing model, unsupported required capability, or failed preflight;
- `target_request_error`: exhausted retryable transport/provider error;
- `target_protocol_error`: non-retryable HTTP response, malformed JSON, or
  invalid success shape;
- `operator_interrupted`: operator cancellation or process termination; and
- `engine_error`: RogueRecall invariant, serialization, or persistence failure.

Authentication/authorization failures, unknown models, and other deterministic
configuration errors stop scheduling that Target System and mark its remaining
cases `not_tested` with the shared cause. Exhausted `429` or server/transport
failures affect that case and allow later cases to proceed. A persistence or
integrity failure stops the whole Evaluation Run; RogueRecall must not continue
when it cannot produce an authoritative Run Record.

Provider error bodies and IDs are retained, but their human messages are not
used for control flow. Anthropic explicitly documents typed error objects and
may add error variants; OpenAI likewise exposes HTTP status and request IDs for
debugging. Branch on status and stable structured codes, retain unknown values,
and map any unknown failure conservatively to `target_protocol_error` rather
than `completed`.

## Versioning and comparison consequences

The adapter contract is semantic-versioned independently of RogueRecall. A
change to endpoint selection, request construction, text extraction, retry
eligibility, timeout meaning, or success/error classification increments its
major version because it can change observed outcomes. Adding only newly
captured optional evidence may be minor; a bug fix that cannot alter requests
or extracted text may be patch.

The Run Record must preserve the canonical Target System manifest, adapter and
dependency versions, provider API version, requested/returned model identity,
local artifact and launch digests where supplied, full capability report,
attempt history, and configuration SHA-256. A comparison engine should flag,
not erase, differences in any outcome-affecting field. It must never claim that
two runs used the same Target System solely because their requested model names
match.

This contract supplies the transport and attempt fields for the canonical Run
Record, the provider settings needed by the command-line contract, and the
configuration mismatches the dashboard must surface. It does not choose the
Run Record's storage format or dashboard presentation.

[anthropic-errors]: https://platform.claude.com/docs/en/api/errors
[anthropic-rate-limits]: https://platform.claude.com/docs/en/api/rate-limits
[anthropic-version]: https://platform.claude.com/docs/en/api/versioning
[openai-introduction]: https://developers.openai.com/api/reference/overview
[openai-models]: https://developers.openai.com/api/reference/resources/models
[openai-rate-limits]: https://developers.openai.com/api/docs/guides/rate-limits
[openai-responses]: https://developers.openai.com/api/reference/resources/responses/methods/create
