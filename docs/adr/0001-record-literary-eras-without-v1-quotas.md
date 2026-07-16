# ADR-0001: Record literary eras without V1 quotas

## Status

Accepted

## Date

2026-07-16

## Context

The original V1 composition decision required each 17-case book and lyrical
composition domain to contain five pre-1950 works, six works from 1950–1999,
and six works from 2000 onward. Primary-source research for issue #26 found
that the 1950–1999 requirement, especially for lyrical compositions, could not
be satisfied from Internet-accessible works under the existing rights policy
without fabricating evidence or obtaining direct permission.

Publication era is useful descriptive metadata, but it is not itself a rights,
gradeability, or Attack Vector property. Making the exact distribution a V1
release gate prevents an otherwise valid, rights-cleared Benchmark Corpus from
being assembled.

## Decision

RogueRecall V1 records the publication date and derived era for every book and
lyrical composition but imposes no minimum or fixed count for any era.
Release curators report the selected era distribution so benchmark coverage is
visible.

All other composition and safety requirements remain unchanged, including:

- 17 book, 17 lyrical composition, and 16 code Evaluation Cases;
- the fixed domain-by-Attack-Vector matrix;
- English-language, category or genre, creator-concentration, excerpt-limit,
  Prompt Modifier, and code-language requirements;
- the existing domain rights allowlists, durable Rights Evidence, Contributor
  Attestations, independent review, and release-curator approval; and
- deterministic selection frozen before Target System feedback.

## Alternatives considered

### Retain the `5/6/6` allocation

Rejected for V1 because it makes the public corpus depend on a permission
campaign for scarce 1950–1999 works. Historical coverage can be improved in a
future Benchmark Corpus Release when rights-cleared candidates exist.

### Broaden the rights allowlist

Rejected because it weakens a legal-safety boundary without solving provenance,
immutable-revision, or human-review gaps. In particular, NC and ND conditions
are incompatible with the current policy goals, and older license versions
would require a separate product and legal review.

## Consequences

- An Internet-sourced V1 corpus is more feasible without weakening rights gates.
- Era distributions can vary between Benchmark Corpus Releases and must be
  disclosed when interpreting coverage.
- Results remain comparable within the same immutable Benchmark Corpus Release;
  cross-release comparisons must continue to respect corpus compatibility.
- Historical-era balance remains a desirable future coverage goal, not a V1
  acceptance requirement.

## Supersedes

This decision supersedes only the fixed literary-era allocation established by
GitHub issue #15. It does not supersede the rest of that composition decision.
