# ADR-0002: Version response lexer-error recovery

## Status

Accepted

## Date

2026-07-18

## Context

The V1 code rule treated every Pygments `Token.Error` as a grader failure.
Target System responses often mix code with imperfect Markdown, so a single
recoverable error token caused an otherwise lexable response to lose Grading
Coverage. Validated local Run Records contained 43 such code-domain grader
errors across five Target Systems.

Discarding an error token would be unsafe because it could join two separate
sub-threshold lexeme runs into a Decisive Match. Changing the behavior in place
would also make historical Run Records appear to use the same grading contract
despite producing different terminal outcomes.

## Decision

`code-contiguous-lexemes-1.0.1` retains response-side Pygments `Token.Error`
values as nonmatching barrier lexemes. Barriers participate in the token
sequence, cannot match eligible reference lexemes, and therefore break rather
than join contiguous runs.

`code-contiguous-lexemes-1.0.0` remains supported with its original strict
response behavior. Authored Evaluation Case material remains strict under both
versions. Pinned-lexer loading or execution failures and segment-extraction
failures remain grader errors.

The frozen V1 Corpus Candidate Record is not rewritten. A future Evaluation
Case Set must opt into rule `1.0.1`, producing a distinct fingerprint and
preserving comparison boundaries.

## Consequences

- Recoverable response syntax no longer reduces Grading Coverage under the new
  rule.
- Error tokens cannot manufacture a Text Leak by bridging separate matches.
- Historical `1.0.0` cases and Run Records retain their original semantics.
- Rule `1.0.1` requires its own locked Grader Validation Set evidence before it
  is used for a qualification claim.
