# RogueRecall

RogueRecall is a local benchmark for checking whether a deployed language model reproduces protected text after an indirect prompt.

It measures observable behavior only. It does not claim to know what is stored in a model or how the model was trained.

## Surface

The installed package exposes one public workflow:

```bash
roguerecall benchmark --manifest ./targets.json --results ./results.json
```

The command runs the fixed Benchmark Corpus against the declared target systems in manifest order, then prints a non-ranked summary and writes a `results.json` file.

### Inputs

- `--manifest`: strict target-system manifest in JSON form.
- `--results`: required, new path for the self-contained result JSON.

### Behavior

- The benchmark always uses the installed 50-case Benchmark Corpus.
- Generation is fixed and deterministic.
- Credentials are named by environment variable and never written into output.
- Existing result files are never overwritten.
- The summary reports explicit denominators so missing grades stay visible.

## Dataset and grading

The repository includes the fixed Benchmark Corpus and deterministic graders for the supported domains.

- Books use a contiguous-word threshold.
- Lyrics use a contiguous-line and coverage rule.
- Code uses exact contiguous lexemes.

## Development

Run the benchmark test suite with:

```bash
uv run --python 3.12 --with pytest==8.4.1 pytest
```

For type checking:

```bash
uv run --python 3.12 --with mypy==1.17.1 mypy --strict src
```
