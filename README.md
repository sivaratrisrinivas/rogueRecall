# RogueRecall

RogueRecall is a local benchmark for observing whether a deployed language model reproduces protected text after an indirect prompt. It measures the behavior of a configured **Target System**, not a model's weights or training data.

## Quickstart

Set the credential named in your manifest and run the one public workflow:

```bash
export ROGUERECALL_TOKEN='…'
roguerecall benchmark --manifest ./targets.json --results ./results.json
```

`--results` must name a new path. RogueRecall never overwrites it; use a new path for each invocation. The command first grades its local controls against every case. If they fail, it writes `controls_failed`, makes no provider request, and exits nonzero. Otherwise it processes Target Systems and cases sequentially in manifest order, updating `results.json` atomically after every observation.

## Target System manifest

The manifest is JSON with a non-empty, ordered `target_systems` list. RogueRecall supports OpenAI-compatible Chat Completions only. The credential value stays in the environment; the manifest records only its variable name.

```json
{
  "schema_version": "1.0.0",
  "target_systems": [
    {
      "target_system_id": "local-model-a",
      "requested_model": "model-a",
      "base_url": "https://models.example.test",
      "credential": {
        "kind": "bearer",
        "environment_variable": "ROGUERECALL_TOKEN"
      }
    }
  ]
}
```

Every request uses the same fixed contract: temperature `0`, a maximum of `256` output tokens, one bounded retry for transient failures, and a request timeout. Plain HTTP is accepted only for loopback hosts; redirects are rejected.

## Fixed Benchmark Corpus and results

The installed RogueRecall version supplies one fixed 50-case **Benchmark Corpus**: 17 book cases, 17 lyrics cases, and 16 code cases. Cases contain the exact user message and the limited reference and source-audit data needed for deterministic grading. `results.json` records the RogueRecall and corpus versions, corpus fingerprint, fixed settings, control outcomes, configured Target System identities, raw responses or explicit errors, grades, decisive-match evidence, aggregate counts, timestamps, and status.

Read each Target System row using its explicit denominators:

- **Text Leaks** is `leaks / graded observations`; it is not a safety score.
- **Grading Coverage** is `graded observations / planned observations`.
- Target and grader errors are separate from non-leaking grades. An ungraded observation is never evidence of safety.

`complete` means each Target System reached a terminal observation for every planned case; it does not mean there were no errors. A non-complete artifact remains useful evidence, but is not a complete comparison. RogueRecall reports observations only: it does not rank Target Systems or declare a winner.

## Development

Use Python 3.12. Run the full test suite and strict type check before changing benchmark code or data:

```bash
uv run --python 3.12 --with pytest==8.4.1 pytest -s
uv run --python 3.12 --with mypy==1.17.1 mypy --strict src
```
