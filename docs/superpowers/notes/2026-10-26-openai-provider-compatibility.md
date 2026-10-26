# OpenAI Responses compatibility evidence

Verified 2026-10-27 before implementing Task 5. The inactive opt-in model snapshot is recorded only in `config/llm_routes.yaml`. The deployed defaults remain Anthropic. This is an offline compatibility profile, not evidence of account access or paid model quality.

## SDK and native transport

The official Python SDK is pinned exactly to `openai==3.39.0` in the optional OpenAI extra and development extra. The [official release](https://github.com/openai/openai-python/releases/tag/v3.39.0) was published on 2026-10-26 at 19:14 UTC; PyPI's corresponding wheel was uploaded at 19:19 UTC. These public release/package endpoints were fetched before adding the dependency. The [official SDK documentation](https://developers.openai.com/api/docs/libraries) links the maintained Python package.

After installation, package metadata explicitly requires `httpx2<3,>=2.12.0`, and `openai/_base_client.py` imports `httpx2`. The scripted transport therefore uses `httpx2.MockTransport` with the official `OpenAI` client. This was verified from the selected installed release, not inferred from Anthropic or older SDKs. Both role dependency manifests include `openai` and `httpx2`. SDK retries are forced to zero on bound clients; application retries share the original response budget.

## Selected request profile

The [selected model documentation](https://developers.openai.com/api/docs/models/gpt-5.4) establishes Responses, function calling, Structured Outputs, and effort values `none`, `low`, `medium`, `high`, `xhigh`. The [generation compatibility guide](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.4) documents temperature only at effort `none`. The adapter resolves omitted effort to `none`, rejects Anthropic thinking and unsupported effort/options, and permits temperature in 0–2 only at that effort. It translates logical `max_tokens` to `max_output_tokens`, which includes reasoning output. This profile does not automatically infer capabilities from arbitrary model names.

[Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) documents implicit prefix caching and model-specific retention support. For this selected profile, explicit cache controls are `prompt_cache_key` and `prompt_cache_retention` (`in_memory` or `24h`). The key is validated as a nonblank string up to 64 characters. Policy, skill pack, instructions, tool definitions, and preceding input items remain stable across continuation. No invented commercial prices or new pricing snapshots are introduced.

## Strict schemas and stateless continuation

[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) requires all object properties to be required and forbids additional properties. Canonically optional read-tool arguments are required nullable wire fields. Optional nulls are removed by their canonical declaration before local dispatch; required nulls and false/zero/empty strings remain available to the tool's ordinary validation. Tutor output requires diagnosis, proposals, and proposal target keys as well as message/rung, and feeds the existing semantic parser.

The [Responses reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create) and [stateless continuation guide](https://developers.openai.com/api/docs/guides/migrate-to-responses) document `store=false`, encrypted reasoning continuation, and matched `function_call_output.call_id`. Every request repeats instructions, disables automatic truncation, explicitly includes encrypted reasoning for compatibility, and replays returned output items in original order. The adapter does not use `previous_response_id`, register remote tools, generate reasoning summaries, or deliver intermediate output. Formatting/engine feedback is appended as a developer input item, retaining the original prefix.

## Usage and service conditions

The [Responses usage schema](https://developers.openai.com/api/reference/python/resources/responses/methods/create) reports inclusive input and cached subset; output includes reasoning as a subset. Normalization counts uncached input, cache reads, and output once. Invalid/unknown subsets or categories preserve known counts and incompleteness; positive cache-write categories are unsupported by this profile. Missing counters are never explicit zero. A complete response with unknown output reserves its full requested output allowance locally, while normalized billing usage remains missing.

The same reference states that returned `service_tier` reflects execution and may differ from the request. The adapter accepts explicit default/flex/priority requests, uses recognized returned conditions with provenance, records mismatches in evidence, and keeps missing/malformed execution conditions unknown. Geography is unknown without endpoint evidence. No model-name-based billing inference is made.

## Offline verification and limits

Tests use the selected official SDK at its real serialization/stream parsing boundary, with no network or production keys. They cover strict tool schemas, nullable optional argument dispatch, final structured output, distinct call IDs, encrypted continuation, engine rejection/correction, refusal/incomplete/error output, retryable API failure, malformed/empty output, partial stream disconnect/EOF, context/output/time/round limits, concurrent history isolation, and usage/condition propagation. Live endpoint/model support remains deliberately untested: paid execution was not authorized.
