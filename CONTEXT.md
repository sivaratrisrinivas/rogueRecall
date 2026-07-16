# RogueRecall

RogueRecall is a benchmark for measuring whether deployed language-model systems reproduce protected text when given indirect prompts.

## Language

**Target System**:
A specific model version accessed through a particular provider interface and safety configuration. RogueRecall measures the observable behavior of this complete system, not what may be stored in the model's weights.
_Avoid_: Underlying model, model memory

**Benchmark Operator**:
The evaluation engineer who configures target systems, runs the benchmark, compares results, and exports evidence for other stakeholders.
_Avoid_: End user, administrator

**RogueRecall Contributor**:
A person or organization that submits RogueRecall Material or an Evaluation Case and certifies its authority to do so. A RogueRecall Contributor retains copyright in its original contribution; submitting a third-party reference excerpt additionally requires the case-specific rights attestation and does not make the contributor its rightsholder.
_Avoid_: Copyright assignee, presumed rightsholder, corpus owner

**Benchmark Corpus**:
The public, versioned collection of 50 evaluation cases used by RogueRecall V1. Each case contains an indirect prompt and the limited reference material needed for objective scoring.
_Avoid_: Private dataset, training dataset

**Benchmark Corpus Release**:
An immutable, signed distribution of one exact Benchmark Corpus version and its Release Notice Bundle. Supersession, suspension, withdrawal, and reinstatement change the release's recorded status without changing its contents or identity.
_Avoid_: Mutable dataset, latest corpus, corpus snapshot

**Corpus Candidate Record**:
A validated, pre-release record of the eligible candidate pool, explicit exclusions, structured Selection Slots, deterministic seed, frozen 50-case membership, contributor attestations, independent reviews, and curator decisions. A Corpus Candidate Record is not a Benchmark Corpus Release and carries no release signature or lifecycle status.
_Avoid_: Draft release, accepted corpus, candidate manifest

**Selection Slot**:
A structured set of domain, Attack Vector, era, category or genre, language, and Prompt Modifier criteria used to group interchangeable eligible candidates before deterministic seeded selection. A Selection Slot has a stable identifier, but its criteria—not the identifier alone—determine candidate fit.
_Avoid_: Bucket, arbitrary slot name

**Contributor Attestation**:
A case-specific statement by a RogueRecall Contributor confirming their authority over contributed RogueRecall Material, the recorded rights basis for the exact reference excerpt, disclosure of applicable conditions, and exclusion from prompt development, grader-threshold selection, and exploratory Target System testing. It supplements rather than replaces DCO sign-off and independent review.
_Avoid_: Author attestation, DCO-only approval

**Corpus Release Manifest**:
The canonical signed inventory that identifies a Benchmark Corpus Release, its applicable contracts, its Evaluation Case revisions, and the hashes of every distributed artifact. It is the authority for verifying the release's identity and integrity.
_Avoid_: File list, checksum file, release notes

**Corpus Status Record**:
A signed, append-only statement that changes the recorded lifecycle status of a Benchmark Corpus Release while preserving its history. A Corpus Status Record never edits the release or a Run Record.
_Avoid_: Corpus edit, deletion notice, mutable status field

**RogueRecall Material**:
Original code, prompts, metadata, scoring material, and documentation created for RogueRecall. Third-party reference excerpts, third-party rights evidence, and Target System responses are not RogueRecall Material and do not inherit its licenses.
_Avoid_: Entire repository, all corpus content, project content

**Rights Record**:
The project-authored, case-specific metadata that records the authority for publishing an Evaluation Case, including its rights basis, provenance, required notices, evidence hashes, review, and lifecycle status. A Rights Record is RogueRecall Material; it points to but does not replace Rights Evidence.
_Avoid_: License file, proof document, legal conclusion

**Rights Evidence**:
The durable source material that supports a Rights Record, such as a source license, institutional rights statement, or written permission. Rights Evidence retains its own rights, may require redaction or access controls, and is not RogueRecall Material.
_Avoid_: Rights Record, public metadata, URL-only proof

**Release Notice Bundle**:
The complete human-readable and machine-readable licensing, attribution, third-party notice, and rights-disclosure material that accompanies a RogueRecall release. It is generated from applicable project licenses and Rights Records; a release with an incomplete Release Notice Bundle is invalid.
_Avoid_: Single license file, optional attribution, repository-only notice

**Text Leak**:
An observed response that contains a Decisive Match against an Eligible Reference Span. Source Identification and diagnostic similarity alone do not constitute a Text Leak.
_Avoid_: Source recognition, model memorization

**Eligible Reference Span**:
A case-designated part of a reference passage that contains the expression RogueRecall may use for decisive Text Leak grading, excluding names, facts, notices, and known boilerplate. Eligibility is a benchmark scoring boundary, not a legal conclusion.
_Avoid_: Gold answer, whole source

**Decisive Match**:
A contiguous response-to-reference match that satisfies the applicable versioned, domain-specific grading rule and can therefore establish a Text Leak.
_Avoid_: Similarity score, semantic match

**Source Identification**:
An observed response that names or clearly recognizes the work targeted by an evaluation case without necessarily reproducing its protected expression.
_Avoid_: Text Leak, hard failure

**Evaluation Run**:
A traceable execution of a specific Benchmark Corpus version against one or more Target Systems, including the prompts, responses, settings, timestamps, software version, and deterministic scoring results.
_Avoid_: Guaranteed replay, experiment

**Evaluation Case Set**:
The ordered collection of one or more validated Evaluation Cases selected for an Evaluation Run. An Evaluation Case Set is execution input and is not a Benchmark Corpus or Benchmark Corpus Release unless it independently satisfies those release contracts.
_Avoid_: Benchmark Corpus, corpus snapshot

**Attack Vector**:
A category describing the extraction mechanism by which an indirect prompt attempts to elicit identifiable reference text. Role-play, urgency, output formatting, and other presentation choices are modifiers rather than Attack Vectors; every valid Attack Vector must support objective comparison with a specific reference passage.
_Avoid_: Prompt style, topic

**Evaluation Case**:
A versioned, self-contained Benchmark Corpus unit containing one standalone prompt, one Attack Vector, one contiguous Eligible Reference Span, and the reference, provenance, grading, and review information needed to evaluate it.
_Avoid_: Test question, prompt row

**Source Work**:
The distinct work from which an Evaluation Case draws its reference material: a book, a lyrical composition, or a versioned code repository.
_Avoid_: Source, excerpt, reference passage

**Prompt Modifier**:
A controlled label for presentation surrounding an Attack Vector, such as role-play, claimed authority, benign purpose, urgency, or output formatting. A Prompt Modifier does not change the extraction mechanism being tested.
_Avoid_: Attack Vector, free-form tag

**Continuation**:
An Attack Vector that supplies exact reference text immediately before the Eligible Reference Span and asks for the following text.
_Avoid_: Completion

**Gap Fill**:
An Attack Vector that supplies exact reference text immediately before and after the Eligible Reference Span and asks for the omitted text.
_Avoid_: Continuation, fill-in-the-blank

**Located Quotation**:
An Attack Vector that identifies the Eligible Reference Span through a unique location within a work rather than through adjacent reference text.
_Avoid_: Constrained Reconstruction, direct quote request

**Constrained Reconstruction**:
An Attack Vector that identifies the Eligible Reference Span through a unique combination of content or structural clues rather than a source-relative location or adjacent reference text.
_Avoid_: Located Quotation, paraphrase

**Grader Validation Set**:
A collection of human-labelled leak and non-leak examples used to measure the grading engine's accuracy. It tests RogueRecall's scoring rules and is separate from the 50-case Benchmark Corpus used to test Target Systems.
_Avoid_: Benchmark Corpus, model evaluation cases

**Run Record**:
The complete, structured, auditable record of an Evaluation Run, including configuration, raw observations, errors, warnings, and grading results. CSV files and dashboard views are derived exports rather than the source of truth.
_Avoid_: Results spreadsheet, dashboard state

**Completed Run Record**:
A Run Record in which every planned Evaluation Case and Target System pairing reached a recorded terminal outcome and the record passed integrity validation. A Completed Run Record may contain explicit target or grader errors; completion does not mean every observation was successfully graded.
_Avoid_: Successful run, error-free run

**Incomplete Run Record**:
A preserved Run Record whose planned work did not reach terminal outcomes, such as after cancellation, interruption, or engine failure. It is diagnostic evidence and is excluded from ordinary comparison and export unless deliberately included.
_Avoid_: Failed run, partial success

**Grading Coverage**:
The proportion of planned Evaluation Case and Target System observations that produced completed grades. It is reported alongside leak rate so ungraded errors are never interpreted as safe outcomes.
_Avoid_: Success rate, pass rate

**Compatible Comparison**:
A case-paired comparison between Completed Run Records that use the same Benchmark Corpus and grading-contract versions. Differences in Target System identity remain visible and qualify the interpretation; incompatible records may be viewed side by side but do not receive a calculated change or winner.
_Avoid_: Model-name comparison, leaderboard equivalence
