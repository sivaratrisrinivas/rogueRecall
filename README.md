# RogueRecall

RogueRecall is a local benchmark for measuring whether a deployed Target System
reproduces protected text when given an indirect prompt.

## What this repository provides

The first executable slice is a complete local Evaluation Run walking skeleton:

- an exact-version Python 3.12 `roguerecall` CLI;
- one bundled synthetic Evaluation Case and deterministic synthetic Target
  System, requiring no provider connection or credentials;
- deterministic grading that produces a Text Leak result from known fixture
  evidence;
- canonical Completed and Incomplete Run Records with timestamps, versioned
  contracts, progress, summaries, and content-addressed raw artifacts;
- an independent validator for canonical references, observation structure,
  reproducible summaries, byte lengths, and SHA-256 digests; and
- a loopback-only, read-only dashboard with a direct evidence view.

The synthetic slice is intentionally small. It proves the local execution and
evidence boundaries before real provider adapters and the full Benchmark Corpus
are introduced.

## Why it is structured this way

RogueRecall treats the Run Record—not a dashboard or CSV—as the source of truth.
The Python engine is the only canonical writer. A record becomes a Completed Run
Record only after all planned observations reach terminal outcomes and the
record validates. Cancellation or finalization failure remains visible as an
Incomplete Run Record rather than silently losing partial evidence.

This establishes the boundary:

```text
Python engine writes → immutable Run Record preserves → local dashboard reads
```

Credentials are outside that evidence flow. The synthetic Target System uses
none, and regression tests scan every generated canonical file to ensure secret
values from the environment are not persisted.

## How it works

`roguerecall run-synthetic` snapshots the bundled Evaluation Case and Target
System manifest, records the planned observation, captures request/response and
normalized grading artifacts, selects the deterministic response, grades it,
and derives the stored summary. Every canonical file and raw artifact except
`integrity.json` is then inventoried with its logical path, media type, byte
length, and SHA-256 digest. The inventory itself receives a Run Record
fingerprint.

Finalization validates schemas, references, observation identities and terminal
states, artifact metadata, summary reproduction, and the integrity inventory.
Only then is `<run-id>.incomplete` atomically renamed to `<run-id>`.

The dashboard independently runs the same validation before displaying a
Completed Run Record. It binds only to `127.0.0.1`/localhost/`::1`, accepts no
mutating HTTP methods, cannot execute a Target System, and links summaries to
their selected response, grade, and artifact pointer.

## Development install

RogueRecall 0.1.0 targets Python 3.12. Build the current checkout, then install
the exact wheel into an isolated tool environment:

```bash
uv build --wheel
uv tool install --python 3.12 dist/roguerecall-0.1.0-py3-none-any.whl
roguerecall --help
```

## Run and inspect the synthetic Evaluation Run

```bash
roguerecall run-synthetic --runs-root ./runs
roguerecall validate ./runs/<run-id>
roguerecall dashboard --runs-root ./runs --port 7411
```

The dashboard binds only to loopback and accepts only read requests. The Python
engine is the sole writer of canonical Run Records. To exercise interruption
preservation before execution or during finalization:

```bash
roguerecall run-synthetic --runs-root ./runs \
  --inject-failure operator-interrupted

roguerecall run-synthetic --runs-root ./runs \
  --inject-failure finalization-interrupted
```

The resulting `.incomplete` directory records the cause and last known
progress. It is not displayed by the ordinary dashboard.

## Tests

```bash
uv run --python 3.12 --with pytest==8.4.1 pytest
uv run --python 3.12 --with mypy==1.17.1 mypy --strict src
```

The automated suite covers installation metadata, successful execution,
interruption at two progress points, integrity tampering, secret exclusion,
unsupported schema majors, completion invariants, required selected-response
evidence, loopback binding, and read-only HTTP behavior.
