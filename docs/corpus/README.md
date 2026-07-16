# Corpus Candidate Record intake

These documents support the human evidence required before RogueRecall can
assemble its default 50-case Benchmark Corpus Release. They are workflow
templates, not approvals, Rights Evidence, or accepted Evaluation Cases.

## Intake sequence

1. A contributor prepares an Evaluation Case, durable Rights Evidence, and the
   [contributor attestation](CONTRIBUTOR_ATTESTATION.md).
2. A different person completes the
   [independent case review](CASE_REVIEW_CHECKLIST.md).
3. Written permission, when needed, uses the
   [permission record](WRITTEN_PERMISSION.md); retain the signed original in
   restricted storage and commit only a redacted evidence copy and its hash.
4. The rights reviewer accepts each Rights Record.
5. The release curator completes the
   [corpus-wide checklist](RELEASE_CURATOR_CHECKLIST.md).
6. Export the frozen Corpus Candidate Record and validate it before release
   assembly:

   ```bash
   roguerecall validate-corpus-candidate candidate.json
   ```

The command fails closed unless the record contains exactly 50 releaseable
Evaluation Cases in stable `case_id` order, the fixed composition matrix,
affirmative Contributor Attestations, independent approvals, all curator gates, and
a reproducible pre-execution selection freeze.

## Selection record

The candidate JSON uses schema version `1.0.0`. Its `selection` object records:

- `algorithm`: `sha256-seed-case-id-v1`;
- a non-empty `seed`;
- a timezone-aware `frozen_at` timestamp;
- `target_system_feedback_used: false`; and
- a `candidate_pool` entry for every eligible candidate; and
- explicit `exclusions` for ineligible or contaminated candidates.

Each eligible pool entry contains a complete validated Evaluation Case,
source-supported category or genre evidence, evidence classifying every
non-code Source Work credit as a primary creator or other contributor, and a
structured Selection Slot. The slot records its canonical SHA-256-derived ID,
quota, domain, Attack Vector, era, category or genre, source language, and
Prompt Modifier criteria; those criteria must match the case. A criteria set is
represented by one slot, and its quota records repeated allocations. Eligible
cases are ranked within their slot by the hexadecimal SHA-256 digest of
`seed + "\\0" + case_id`; the lowest digests fill the quota. All slot quotas
must sum to 50, and the selected cases must reproduce those winners exactly.

Every exclusion separately records its case ID, one or more allowed reasons,
and a durable evidence reference. A case cannot be both eligible and excluded.

Allowed exclusion reasons are `prompt_development`,
`grader_threshold_selection`, `exploratory_target_testing`,
`rights_ineligible`, `validation_failed`, and `withdrawn`.

The Corpus Candidate Record also binds a durable, affirmative independent-review
reference and Contributor Attestation to every eligible case. The validator
records process evidence; it cannot establish that a permission
is genuine or that a human actually performed a review. Reviewers and the
release curator remain responsible for those assertions.
