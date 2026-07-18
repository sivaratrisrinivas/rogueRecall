# ADR-0002: Version response lexer-error recovery

## Status

Accepted

## Date

2026-07-18

## Context

The V1 code rule treated every Pygments `Token.Error` as a grader failure.
Target System responses often mix code with imperfect Markdown, so a single
recoverable error token caused an otherwise lexable response to lose Grading
Coverage. Earlier local benchmark evidence contained 43 such code-domain grader
errors across five Target Systems.

Discarding an error token would be unsafe because it could join two separate
sub-threshold lexeme runs into a Decisive Match. Changing the behavior in place
would also blur the grading contract despite producing different terminal
outcomes.

## Decision

`code-contiguous-lexemes-1.0.1` retains response-side Pygments `Token.Error`
values as nonmatching barrier lexemes. Barriers participate in the token
sequence, cannot match eligible reference lexemes, and therefore break rather
than join contiguous runs.

`code-contiguous-lexemes-1.0.0` remains supported with its original strict
response behavior. Authored Evaluation Case material remains strict under both
versions. Pinned-lexer loading or execution failures and segment-extraction
failures remain grader errors.

The fixed Benchmark Corpus is not rewritten by this decision. A future corpus
version must opt into rule `1.0.1`, producing a distinct fingerprint and
preserving comparison boundaries.

## Consequences

- Recoverable response syntax no longer reduces Grading Coverage under the new
  rule.
- Error tokens cannot manufacture a Text Leak by bridging separate matches.
- Historical `1.0.0` cases retain their original semantics.
- Rule `1.0.1` requires its own locked validation evidence before it is adopted
  for a future fixed corpus version.

## Reconciliation with the benchmark-only MVP

GitHub issue #31 replaces the former Run Record architecture with one
self-contained `results.json` artifact. This ADR remains a grading-rule
versioning decision: a result records the fixed corpus fingerprint and grades
under the rule selected by that corpus version. It does not restore Run Records,
qualification workflows, or a configurable Evaluation Case Set interface.
