# RogueRecall

RogueRecall is a fixed, local benchmark for observing protected-text reproduction by deployed language-model systems.

## Language

**Benchmark Operator**: The person who configures Target Systems and runs the fixed benchmark locally.
_Avoid_: End user, administrator

**Benchmark Corpus**: The versioned, in-repository collection of exactly 50 fixed Evaluation Cases used by one RogueRecall version. Its canonical fingerprint identifies the case content used by a result.
_Avoid_: Private dataset, training dataset

**Target System**: One configured model endpoint, identified by its requested model, base URL, credential-variable name, and manifest position. RogueRecall measures this observable configuration, not underlying model memory.
_Avoid_: Underlying model, model memory

**Evaluation Case**: One fixed Benchmark Corpus unit with an exact user message, an indirect prompt design, an Eligible Reference Span, and the grading and minimal source-audit data required for deterministic evaluation.
_Avoid_: Test question, prompt row

**Eligible Reference Span**: The case-designated reference expression that its grading rule may use to establish a Text Leak. It is a benchmark scoring boundary, not a legal conclusion.
_Avoid_: Gold answer, whole source

**Attack Vector**: The extraction mechanism used by an Evaluation Case's indirect prompt, such as continuation or gap fill.
_Avoid_: Prompt style, free-form tag

**Source-Audit Material**: Case-specific provenance, rights, attribution, and notice information supporting the fixed reference material. It is retained for inspection but is not a separate operator workflow.
_Avoid_: Release bundle, contributor workflow

**Text Leak**: A graded response containing a Decisive Match against that case's Eligible Reference Span. It is a benchmark outcome, not a legal conclusion or evidence about training data.
_Avoid_: Source recognition, model memorization

**Decisive Match**: A contiguous response-to-reference match that satisfies the Evaluation Case's versioned domain-specific grading rule and establishes a Text Leak.
_Avoid_: Similarity score, semantic match

**Grading Coverage**: The count of completed grades over the count of planned observations for a Target System. Report it with Text Leaks so ungraded errors are never interpreted as safe outcomes.
_Avoid_: Success rate, pass rate

**RogueRecall Material**: Original code, prompts, metadata, scoring material, and documentation created for RogueRecall. Third-party reference excerpts, Source-Audit Material, and Target System responses are not RogueRecall Material.
_Avoid_: Entire repository, all corpus content
