# Benchmark Corpus Release curator checklist

Complete this checklist after all case-level validation and human review, and
before any Target System executes against the candidate. Warnings may be
resolved or cause candidate rejection; they may not be silently waived.

- Candidate release version:
- Deterministic seed:
- Selection algorithm: `sha256-seed-case-id-v1`
- Candidate freeze timestamp:
- Release curator:
- Rights reviewer:

## Membership and composition

- [ ] Exactly 50 distinct Source Works are selected in stable `case_id` order.
- [ ] The corpus contains 17 book, 17 lyric, and 16 code cases.
- [ ] Every domain-by-Attack-Vector cell matches the fixed matrix.
- [ ] Book and lyric language, era, category/genre, creator concentration, and
      excerpt limits pass.
- [ ] Code contains four each for Python, JavaScript, Java, and C, with every
      Attack Vector once per language.
- [ ] Twenty-five cases are unmodified and five cases use each allowed Prompt
      Modifier with the required domain and Attack Vector coverage.

## Rights, gradeability, and lifecycle

- [ ] Every contributor attestation and DCO sign-off is affirmative.
- [ ] Every Rights Record, durable Rights Evidence item, notice, and independent
      review is complete.
- [ ] All automated Evaluation Case validation passes cleanly.
- [ ] Eligible Reference Spans are unique and cross-prompt contamination checks
      pass.
- [ ] Every case is gradeable under the pinned domain rule and lexer.
- [ ] Every case has accepted, undisputed lifecycle status for this version.

## Selection independence

- [ ] Candidate-pool eligibility was frozen before Target System execution.
- [ ] No selected case was used for prompt development, grader-threshold
      selection, or exploratory Target System testing.
- [ ] The recorded seed and candidate-pool slots reproduce the selected cases.
- [ ] No Target System feedback influenced eligibility, slots, or membership.

## Warnings and decision

For every warning that remains on the selected candidate, record its code,
evidence, `resolved` disposition, and rationale. A rejected candidate belongs in
the selection exclusions and cannot remain in a valid Corpus Candidate Record.

| Code | Evidence | Disposition | Rationale |
| --- | --- | --- | --- |

- [ ] All warnings have an explicit permitted disposition.
- [ ] Corpus composition, concentration, contamination, gradeability, lifecycle,
      and warning-review gates are affirmed in the Corpus Candidate Record.
- [ ] Approve candidate for signed release assembly.

- Release-curator durable approval reference:
- Release-curator signature and date:
- Rights-reviewer durable approval reference:
- Rights-reviewer signature and date:
