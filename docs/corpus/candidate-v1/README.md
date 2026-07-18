# RogueRecall V1 Corpus Candidate Record

`candidate.json` is the frozen, pre-execution 50-case candidate record that
informed the packaged Benchmark Corpus. It contains 17 book, 17
lyrical-composition, and 16 code cases.

Each `evidence/<case_id>/` directory contains:

- `source.txt`, the exact UTF-8 source bytes used to derive the case;
- every downloaded `rights-*.bin` Rights Evidence response; and
- `rights-evidence.json`, which binds the source and Rights Evidence URLs,
  paths, and SHA-256 hashes.

The human role assignments, completion times, and relayed approval statements
are preserved in the
[issue #26 review record](https://github.com/sivaratrisinivas/rogueRecall/issues/26#issuecomment-4990637483).
The record explicitly discloses that Srinivas posted statements received from
Sachin, Tharun, and Vikram through WhatsApp.

This directory is archival provenance for the frozen Benchmark Corpus. The
`validate-corpus-candidate` command was removed with the benchmark-only MVP;
the packaged Benchmark Corpus is the runtime source of truth.
