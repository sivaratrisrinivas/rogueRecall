# RogueRecall V1 Corpus Candidate Record

`candidate.json` is the frozen, pre-execution 50-case candidate for release
version `1.0.0`. It contains 17 book, 17 lyrical-composition, and 16 code cases.

Each `evidence/<case_id>/` directory contains:

- `source.txt`, the exact UTF-8 source bytes used to derive the case;
- every downloaded `rights-*.bin` Rights Evidence response; and
- `rights-evidence.json`, which binds the source and Rights Evidence URLs,
  paths, and SHA-256 hashes.

The human role assignments, completion times, and relayed approval statements
are preserved in the
[issue #26 review record](https://github.com/sivaratrisrinivas/rogueRecall/issues/26#issuecomment-4990637483).
The record explicitly discloses that Srinivas posted statements received from
Sachin, Tharun, and Vikram through WhatsApp.

Validate from the repository root with:

```bash
roguerecall validate-corpus-candidate docs/corpus/candidate-v1/candidate.json
```

This is a validated Corpus Candidate Record. It is not itself a signed
Benchmark Corpus Release and must not be used against a Target System before
release assembly preserves the recorded selection freeze.
