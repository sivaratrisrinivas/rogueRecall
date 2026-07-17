# V1 qualification evidence

The `v1/qualification.json` file is the machine-readable release decision for
the exact V1 Corpus Candidate Record. It names the source revision, contract versions,
environments, inputs, outcomes, exceptions, and SHA-256 digests of every cited
artifact. Validate it without network access:

```bash
roguerecall validate-qualification docs/qualification/v1/qualification.json
```

Qualification fails closed when a required gate category is absent, a cited
artifact is missing or changed, metrics are inconsistent, an adapter is
missing, the Corpus Candidate Record is not exactly 50 cases, or a non-waivable gate is excepted.
Only performance or usability may carry an explicit exception. Accessibility
is a separate, non-waivable gate. Every permitted exception must name an owner,
reason, category, and future expiry.

The frozen grader evidence deliberately distinguishes deterministic conformance
fixtures from independently sampled operational data. Its confidence bounds
describe the named fixture population only and do not claim a true
false-positive rate of zero.

Grader Validation Set `1.0.1` qualifies
`code-contiguous-lexemes-1.0.1` response lexer-error barriers while retaining
the V1 book and lyrical-composition rules. It does not rewrite the frozen V1
Corpus Candidate Record; a future Evaluation Case Set must explicitly select
the new code rule and will have a distinct fingerprint.
