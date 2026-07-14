# Lawful public-corpus boundaries for RogueRecall V1

Status: recommended V1 policy, researched 2026-07-15. This is a conservative
product and release policy, not legal advice. Counsel should review the final
corpus and permission form before the first public release.

## Decision

RogueRecall V1 should be a **permissioned-public Benchmark Corpus**. A case may
be published only when RogueRecall can show affirmative authority to reproduce
and redistribute its exact reference excerpt. V1 must not depend on a
case-specific fair-use judgment.

This is intentionally stricter than the maximum use copyright law might permit.
Fair use is fact-specific, considers both the quantity and qualitative
importance of what was copied, and has no reliable word, line, page, or
percentage safe harbor. Novels and songs are also highly creative works, which
makes an unlicensed public corpus a poor foundation for a repeatable product
policy. See the U.S. Copyright Office's [Fair Use Index][fair-use] and
[17 U.S.C. section 107][section-107].

### Eligible rights bases

Every case must use exactly one of these rights bases:

1. **Worldwide public domain or rightsholder CC0 dedication.** Prefer a
   rightsholder-applied CC0 dedication or a reliable cultural institution's
   worldwide Public Domain Mark. A U.S.-only expiry calculation is insufficient
   for a corpus distributed globally; public-domain status can vary by country,
   and some foreign works had U.S. copyright restored. Record the investigation,
   not merely the conclusion. Creative Commons distinguishes [CC0 from the
   Public Domain Mark][cc-public-domain], and the Copyright Office publishes a
   guide to [investigating copyright status][circular-22].
2. **Compatible public license.** The license must affirmatively allow public
   copying and redistribution of the excerpt for commercial and noncommercial
   users. The release must satisfy every attribution, notice, modification, and
   share-alike condition.
3. **Written permission from the rightsholder or authorized agent.** Permission
   must cover the exact excerpt (or a clearly bounded class of excerpts), public
   repository and release distribution, indefinite archival/versioned use,
   evaluation by commercial and noncommercial users, and publication of prompts,
   reference material, hashes, and derived scores. It must identify any expiry,
   territory, attribution, or withdrawal term.

The following do **not** establish eligibility: public web access; a purchased
copy or subscription; a library scan; an unattributed quotation; a search result
or license-filter badge; Source Identification by a model; a contributor's bare
assurance; or an assertion that the excerpt is “short enough” for fair use.
License and public-domain claims must be verified at the primary source because
aggregators can be wrong; Creative Commons itself advises [independent license
verification][cc-terms].

### Domain allowlists

| Domain | Allowed in V1 | Excluded without counsel-approved written permission |
| --- | --- | --- |
| Books | CC0; verified worldwide public domain; CC BY 4.0; CC BY-SA 4.0; direct permission | NC or ND licenses; orphan works; merely U.S.-public-domain works in a globally distributed corpus; all-rights-reserved works |
| Lyrics | CC0; verified worldwide public domain; CC BY 4.0; CC BY-SA 4.0; direct permission covering the lyric text | Modern commercial lyrics obtained from lyric sites, recordings, liner notes, or fan transcriptions; NC or ND licenses; implied permission |
| Code | CC0; MIT; BSD-2-Clause; BSD-3-Clause; ISC; Apache-2.0; direct permission | Copyleft, source-available, bespoke, unknown, or license-conflicted code in V1 |

CC licenses should not be used as software-license evidence; Creative Commons
recommends checking the code's own software license. The V1 code allowlist is a
deliberately small compliance surface, not a claim that other OSI-approved
licenses are unlawful. OSI's [approved-license list][osi-licenses] establishes
the broader universe. MIT and BSD require preservation of copyright and
permission notices, while Apache-2.0 adds license, changed-file, attribution, and
NOTICE obligations; see the official [MIT][mit], [BSD-3-Clause][bsd], and
[Apache-2.0][apache] texts.

CC BY-SA material remains under its original license inside the collection; the
Benchmark Corpus's own license does not replace it. CC explains that collections
may contain CC-licensed works while each original keeps its license, and that
attribution should identify the creator, license, source, retained notices, and
modifications such as excerpting. See the [Creative Commons FAQ][cc-faq].

## Excerpt limits

There is no legal “safe” excerpt length. The license or written permission is the
authority; these product caps minimize redistribution and keep each case tied to
objective scoring:

| Domain | Default V1 maximum per case |
| --- | --- |
| Books | 200 words and no more than 1% of the work, whichever is less |
| Lyrics | 8 lines and no more than 80 words or 20% of the complete lyric, whichever is least |
| Code | 80 nonblank lines and no more than 10% of one source file, whichever is less |

Use only the smallest contiguous or explicitly identified passage needed for the
case's deterministic matching rules. A rights grant may impose a lower limit;
exceeding a V1 cap requires a recorded exception approved by both the corpus
maintainer and legal reviewer. Repeated cases must not combine to reconstruct a
materially larger portion of one work. Public-domain and CC0 cases still follow
the caps so the Benchmark Corpus remains compact and non-substitutive.

## Required provenance and rights record

Each case must carry machine-readable metadata, versioned beside the case:

- stable case ID and domain;
- work title, creator(s), publisher or project, original publication date, and
  relevant country of origin;
- canonical source URL, retrieval date, edition/version, and immutable locator:
  page/chapter for books, stanza/line source for lyrics, or repository, commit,
  path, and line span for code;
- SHA-256 of the acquired source file and exact normalized reference excerpt;
- rights-basis enum: `worldwide-public-domain`, `cc0`, `open-license`, or
  `written-permission`;
- exact license/tool name, version and canonical URL or SPDX identifier;
- versioned evidence path, evidence SHA-256, reviewer, and review date;
- required attribution text, copyright notice, license text, NOTICE content,
  modification/excerpt notice, and non-endorsement note;
- permission scope, territories, expiry, withdrawal terms, and authorized agent,
  where applicable;
- excerpt word/line counts, percentage calculation, and any approved exception;
- acceptance status and the Benchmark Corpus release versions containing it;
- removal, replacement, or dispute status without reproducing disputed text.

Evidence must be durable: save a PDF, plaintext license, repository license and
NOTICE files at the pinned commit, institutional rights statement, or signed
permission. A URL alone is not evidence. Public evidence should be redacted of
signatures, home addresses, private email, and contract terms not needed to
prove scope; the unredacted original belongs in restricted project records, with
its hash recorded publicly.

No case is releaseable until someone other than its contributor performs and
records a rights review. Unknown, conflicting, expired, unverifiable, or
territory-limited rights status fails closed.

## Public disclosure

Every release and corpus landing page should say, in substance:

> RogueRecall is a public benchmark for measuring observable Target System
> behavior. Its collection-level license covers RogueRecall's original prompts,
> metadata, and scoring material only. Third-party reference excerpts retain the
> rights and license recorded per case. Inclusion does not imply endorsement by
> any creator, publisher, project, or rightsholder. Operators are responsible for
> complying with applicable law and case-specific terms. Report rights concerns
> to `<published rights contact>` with the case ID and basis of the claim.

Do not label the whole Benchmark Corpus “public domain” or place every file under
one blanket project license. Generated Target System responses can reproduce
protected text and therefore must not be automatically republished as freely
licensed corpus content.

## Rights-concern and removal process

RogueRecall should accept ordinary rights concerns without requiring a formal
DMCA notice. Publish a monitored email address and private-capable intake form;
ask for the claimant's contact details, work, case ID or URL, rights basis, and
requested action.

1. Acknowledge within two business days and create a private case record.
2. If the claim is facially plausible, immediately mark the case disputed,
   remove it from the default downloadable corpus and dashboard catalog, and
   suspend new releases containing it while reviewing the evidence.
3. Within five business days, compare the claim with the stored rights record
   and contact the contributor or permission grantor when useful. Escalate
   ambiguous ownership, fair-use, contract, or counter-notice questions to
   counsel; maintainers must not improvise legal conclusions.
4. If substantiated, remove the excerpt from the repository's current tree,
   downloadable artifacts, package indexes, caches under project control, and
   documentation. Because deleting the head revision does not erase Git history,
   assess history rewriting and host-level purge with counsel and the claimant.
   Mark every affected corpus version withdrawn and publish a replacement
   version with a new case ID; never silently mutate a released version.
5. Publish a content-free resolution entry containing dates, affected case and
   release IDs, disposition, and replacement. Preserve access-controlled
   evidence needed for the dispute without keeping the excerpt publicly live.

Formal notices must be routed promptly to the hosting platform and any project
DMCA agent. The Copyright Office lists the required elements of a notice and says
a qualifying service provider must respond expeditiously to preserve section 512
safe-harbor protection; see its [DMCA designated-agent guidance][dmca]. Whether
RogueRecall itself qualifies, should designate an agent, or should send a
counter-notice is a counsel decision, not a maintainer checklist.

## Contributor rules

Corpus changes must arrive through a reviewable pull request using a structured
case form. The contributor must:

- provide every provenance and rights field above plus durable evidence;
- certify that they created the original prompt/metadata or may contribute it
  under the project license, and that the reference excerpt is submitted under
  the recorded rights basis;
- certify that the contribution is public, versioned, and redistributable for
  the uses described above, and disclose all conditions or conflicts they know;
- avoid secrets, personal data, unpublished manuscripts, leaked source code,
  access-controlled material, fabricated provenance, and material acquired by
  bypassing technical restrictions;
- use `Signed-off-by` to accept the project's DCO plus a corpus-specific rights
  attestation; and
- respond to provenance questions and rights disputes, while understanding that
  maintainers may quarantine or remove a case without waiting for them.

The [Developer Certificate of Origin 1.1][dco] is a useful baseline because it
records the contributor's right to submit and the public, durable nature of the
contribution. It is not enough by itself for third-party excerpts, so the
corpus-specific rights attestation is mandatory.

Maintainers must reject incomplete submissions rather than merge them as drafts.
The project also needs a chosen license for its original prompts, metadata,
scoring rules, and code before accepting outside contributions; that project
license must explicitly exclude third-party excerpts and evidence from its scope.

## Consequences for the V1 specification

- The case schema needs the provenance, rights, attribution, excerpt-count, and
  lifecycle fields above.
- The case validator must fail closed on a missing/unknown rights basis, absent
  evidence hash, unapproved license, cap violation, missing notice, or missing
  independent review.
- The corpus build must generate a per-release attribution and third-party-notice
  bundle from case metadata.
- Released corpus versions are immutable. A rights removal withdraws the affected
  release and creates a replacement; it never rewrites the same version.
- The dashboard and exports must display case-level rights status and must not
  imply that Target System responses inherit the Benchmark Corpus license.

[apache]: https://opensource.org/license/apache-2-0
[bsd]: https://opensource.org/license/BSD-3-clause
[cc-faq]: https://creativecommons.org/faq/
[cc-public-domain]: https://creativecommons.org/public-domain/
[cc-terms]: https://creativecommons.org/terms/
[circular-22]: https://www.copyright.gov/circs/circ22.pdf
[dco]: https://developercertificate.org/
[dmca]: https://www.copyright.gov/dmca-directory/
[fair-use]: https://copyright.gov/fair-use/
[mit]: https://opensource.org/license/mit
[osi-licenses]: https://opensource.org/licenses
[section-107]: https://copyright.gov/title17/92chap1.html#107
