# Benchmark Corpus source research for issue #26

Status: Internet-source feasibility research, 2026-07-16. This is not legal
advice and does not record any human approval.

## Conclusion

Issue #26 cannot be completed from Internet research alone without inventing
evidence. Primary-source discovery can produce a credible pool for the 16 code
cases and can help with some modern books and lyrical compositions, but it cannot produce the
required contributor attestations, independent rights reviews, release-curator
approval, or a contamination declaration. I also did not find a primary-source
catalog from which six English lyrical compositions first published in
1950–1999 can be shown to meet RogueRecall's exact `CC-BY-4.0` /
`CC-BY-SA-4.0` allowlist, worldwide scope, exact-text, publication-date, and
durable-revision requirements.

The defensible course is therefore to keep #26 blocked at corpus intake, not to
turn search-engine license labels into accepted Rights Records. Commission or
solicit the missing 1950–1999 works under RogueRecall's written-permission form,
then have people other than the contributors perform the required reviews.

## What Internet sources can and cannot establish

| Source | Useful first-party fields | Material limitation for #26 |
| --- | --- | --- |
| [GitHub repository contents API](https://docs.github.com/en/rest/repos/contents) and [license API](https://docs.github.com/en/rest/licenses/licenses) | Raw file bytes, blob SHA, repository/path, ref, and the detected license file; a full commit SHA can pin the source and license together. | GitHub says Licensee merely attempts to match a repository `LICENSE` against known licenses and does not account for dependencies or other license statements. Each chosen file still needs manual scope/conflict review and stored `LICENSE`/`NOTICE` evidence. Download URLs themselves expire. |
| [OAPEN metadata and OAI-PMH exports](https://www.oapen.org/article/metadata) and [DOAB metadata harvesting](https://www.doabooks.org/en/resources/metadata-harvesting-and-content-dissemination) | Creator, language, publication metadata, identifiers, rights metadata, and full-text download links; metadata feeds are CC0. OAPEN offers JSON, CSV, ONIX, MARCXML, REST, and OAI-PMH. | A repository handle is stable, but these catalogs do not promise that a bitstream is an immutable revision. The license on the metadata is not the license on each book. Pin acquired bytes by SHA-256, preserve the book's own license page, and independently verify title-level rights. The catalog is promising for post-2000 nonfiction, not evidence by itself for the required 1950–1999 allocation. |
| [OpenStax title pages](https://openstax.org/books/introduction-intellectual-property/pages/preface-and-foreword) | The title page can state authors/contributors, publication date, and title-specific license, while the book is downloadable. | OpenStax announced that its library moved from mixed licensing to CC BY-NC-SA ([first-party licensing update](https://openstax.org/blog/openstax-licensing)); NC is outside RogueRecall's allowlist. An older CC BY copy may remain usable because Creative Commons says its licenses are irrevocable, but only if RogueRecall stores the exact previously licensed bytes and contemporaneous evidence. [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) permits commercial sharing and adaptation with attribution. |
| [Jamendo tracks API](https://developer.jamendo.com/v3.0/tracks) | Track ID, artist, release date, Creative Commons URL, downloadable audio, and optionally lyrics. It can filter CC conditions and include `licenses` and `lyrics`. | It supplies no immutable lyric revision, and its catalog record is not proof that the displayed release date is the composition's original publication date. Many documented examples use CC 3.0 or NC/ND licenses, none of which pass the current exact allowlist. It is useful for discovery of post-2000 candidates only after exact lyric-text and rights verification. |
| [Openverse audio API](https://api.openverse.org/) | Aggregated creator, source, provider, license/version/URL, audio URL, genre, and attribution fields. | It indexes audio rather than a versioned lyric text and does not expose an original publication-date or immutable lyric revision field. It is a lead generator, not Rights Evidence. |
| [ccMixter](https://www.ccmixter.org/about) | The service states that uploaders own their music and automatically share uploads under Creative Commons licenses; its public API exposes the uploads. | That statement concerns uploaded music generally. It does not establish that a particular lyric text is covered, was first published in 1950–1999, uses CC BY 4.0/CC BY-SA 4.0, or has an immutable revision. Sample/remix rights can also be layered. |
| Project Gutenberg and Standard Ebooks | Downloadable English text, detailed bibliographic metadata, and version-control-friendly files. | They are unsuitable as automatic worldwide-rights authorities. Standard Ebooks explicitly warns that its public-domain research is U.S.-specific and that works can remain protected elsewhere ([first-party example](https://standardebooks.org/artworks/william-orpen/the-signing-of-peace-in-the-hall-of-mirrors-versailles-28-june-1919)). RogueRecall's policy rejects merely U.S.-public-domain works. |

No source in the table simultaneously exposes exact compatible license,
immutable textual revision, creator, original publication date, and downloadable
English lyric text. GitHub comes closest for code because a commit and blob are
content-addressed; the literary and music catalogs require a local evidence
snapshot and human rights review.

## Era-specific finding

Creative Commons licenses can be applied retrospectively to an older work, but
they were not a contemporaneous 1950–1999 publication mechanism. Creative
Commons explains that CC licenses are irrevocable and that a licensor must own
or control the copyright ([official licensing guidance](https://creativecommons.org/cc-license-your-work/)). Thus an old work is eligible only when the actual
rightsholder later made an identifiable grant (or signs direct permission); an
aggregator's CC badge cannot substitute for that chain of authority.

### Books

- OAPEN/DOAB is the strongest discovery source for openly licensed books, and
  post-2000 English CC BY/CC BY-SA candidates should be obtainable there.
- A title-level OAPEN record can explicitly identify a book as English and CC BY
  4.0 (for example, [*Oral and Maxillofacial Surgery for the Clinician*](https://library.oapen.org/handle/20.500.12657/47307)), but that example is a
  modern work and only demonstrates the source shape.
- No six-work 1950–1999 English candidate set with exact allowlisted rights was
  verified in this research. Bibliographic search hits containing a 1950–1999
  year often refer to a cited work inside a newly published CC BY book, not to
  the publication date of the licensed book itself. Such hits must not be used.
- Pre-1950 public-domain candidates require work-by-work worldwide analysis;
  U.S.-only repositories cannot supply the required conclusion.

### Lyrics

- Jamendo is the only reviewed first-party API that combines a creator, a
  release date, a CC URL, audio download, and optional lyrics. It still lacks an
  immutable lyric revision and an assured original-publication-date field.
- Openverse and ccMixter may broaden discovery, but neither establishes the
  exact text/version/date/rightsholder chain that the Rights Record requires.
- Consequently, zero of the required six 1950–1999 lyric slots were verified
  against all gates. The gap should be filled by direct rightsholder permission
  for exact lyric text, not by lowering the license allowlist or treating audio
  licensing as automatically covering a transcription.

## Defensible acquisition strategy

1. **Code (16 cases):** query public GitHub repositories by primary language,
   then pin a full commit SHA and record the target file's blob SHA. Fetch and
   hash the source file, `LICENSE`, and any `NOTICE` at that same commit. Select
   four distinct repositories each for Python, JavaScript, Java, and C from only
   MIT, BSD-2-Clause, BSD-3-Clause, ISC, or Apache-2.0 after manual scope review.
   Do not infer file-level rights from GitHub's detected SPDX key alone.
2. **Modern books:** harvest OAPEN/DOAB metadata, restrict to English title-level
   CC BY 4.0 or CC BY-SA 4.0, download the exact PDF/EPUB, and preserve its hash,
   title page, license page, and catalog record. Favor works whose publisher or
   author is visibly the licensor and whose embedded third-party exclusions do
   not touch the excerpt.
3. **Pre-1950 books and lyrics:** use only a rightsholder-applied CC0/PDM record
   or a documented worldwide-public-domain analysis. Do not equate an old date
   with worldwide public domain.
4. **1950–1999 books and lyrics:** run a permission campaign. The grant must cover
   the exact excerpt, worldwide public redistribution and commercial use,
   indefinite versioned archival use, prompts/references/hashes/scores, and all
   conditions. Preserve the signed grant outside the public repository and a
   redacted evidence copy plus hash inside it.
5. **2000 onward lyrics:** Jamendo can generate leads only. Confirm that the
   provided lyric text, not merely the sound recording, is under CC BY 4.0 or CC
   BY-SA 4.0 and preserve the page/API response and exact bytes. If that cannot
   be established, obtain written permission.

## Acceptance criteria that remain human-only

The following issue #26 gates cannot truthfully be generated by crawling or by
an implementation agent:

- Contributor Attestation for every case;
- an independent review by someone other than the contributor;
- named rights-reviewer acceptance and review date;
- release-curator confirmation of composition, concentration, contamination,
  gradeability, and lifecycle gates;
- confirmation that candidates were excluded from prompt development, grader
  threshold selection, and exploratory Target System testing; and
- freeze-before-feedback confirmation for the final membership and deterministic
  seed.

The local policy already requires durable evidence rather than a URL and says
that no case is releaseable until someone other than its contributor records a
rights review ([RogueRecall lawful-corpus policy](../research/lawful-public-corpus-boundaries.md)). An Internet-only implementation can prepare
Corpus Candidate Records and evidence snapshots; it cannot mark these fields accepted.

## Release recommendation

Do not commit a purported default 50-case release yet. A credible preparatory
change may add an **unaccepted intake manifest** and acquisition tooling, but
must not populate reviewer names, attestations, or approvals. Issue #26 becomes
implementable only after (at minimum) six eligible 1950–1999 English book works,
six eligible 1950–1999 English lyric works, the remaining era pools, and the
human evidence package are supplied. The 1950–1999 lyric set is the clearest
current source blocker.
