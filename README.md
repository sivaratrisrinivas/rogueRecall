# RogueRecall

RogueRecall is a local benchmark for measuring whether a deployed Target System
reproduces protected text when given an indirect prompt. Issue #22 provides a
walking skeleton built around one bundled, deterministic synthetic Evaluation
Case and Target System; it does not call a provider or require credentials.

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
engine is the sole writer of canonical Run Records. A Completed Run Record is renamed
from `<run-id>.incomplete` only after its summaries, references, and integrity
inventory validate. To exercise interruption preservation:

```bash
roguerecall run-synthetic --runs-root ./runs \
  --inject-failure operator-interrupted
```

The resulting `.incomplete` directory records the cause and last known
progress. It is not displayed by the ordinary dashboard.

## Tests

```bash
pytest
```
