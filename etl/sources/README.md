# Sources

Each source is two files: an entry in `config.py` declaring what it is, what it
costs and what its license permits, and a module here that turns the archived
bytes into county records. Nothing here touches the network directly; modules
ask `snapshot.fetch`, and the archive fetches only when it must.

## Politics, and the outage this extractor was built to survive

**Update 2026-08-17: fixed, `verified=True`.** The paragraphs below describe
the 2026-08-16 outage and the design principle it forced; they're kept
because the principle still governs this extractor, but the outage itself is
resolved — don't read this section as current status. What was actually
wrong wasn't the API-disabled incident first suspected: Harvard's API was
back, but the dataset gained a mandatory guestbook (id 458) that a bare GET
can't satisfy, so it answered `400`. `politics.py`'s
`_mit_election_signed_url()` POSTs the guestbook response and follows the
signed URL it returns. Verified live 2026-08-17: 3,111 counties scored. See
`etl/config.py`'s `mit_election` registration for the current, authoritative
state (`verified=True`, `license_verified="2026-08-17"`).

The politics extractor takes county presidential returns from the **MIT
Election Data and Science Lab**, published on Harvard Dataverse. As of
2026-08-16 Dataverse had API access disabled during an incident, by their own
banner: *"some functionality (such as access to our APIs, other than within a
browser) is limited or disabled"*. Requests answered `202` with an empty body.

The source stayed pointed there, marked `verified=False`, and politics
rendered **"not reported"** in the interface in the meantime.

That was a deliberate choice, and it is the whole design principle of this
directory in one decision: **data integrity outranks availability.** The
canonical county-level file for 2000-2024 is cleaned, versioned, DOI'd and
licensed in exactly one place. If it cannot be reached, the honest answer is
that the number is unavailable. A tool nobody can trust is worse than a tool
that admits a gap.

### Alternatives considered and rejected

Recorded so the question is not reopened every time the outage is noticed.

| Candidate | Why not |
|---|---|
| `MEDSL/county-returns` (GitHub) | Covers 2000-2016, last updated April 2020. Missing **both** cycles this extractor averages. Stale. |
| `MEDSL/2024-elections-official` | Precinct level, same lineage as the Dataverse file. Would need precinct-to-county aggregation that this project would then have to QA itself. A different project, not a shortcut. |
| `tonmcg/US_County_Level_Election_Results_08-24` | Scraped from network feeds (Fox, Politico, NYT) and says so. Not authoritative. **Retained as a validation source**, where the independent lineage is the entire point. |
| `jaytimm/PresElectionResults` | Derived from tonmcg. Inherits the provenance question without answering it. |

### The upgrade path, if county-level publication ever stops

Aggregate the MEDSL precinct-level official repos, or OpenElections. Both are
built from state-certified returns, so both are a provenance ceiling rather
than a compromise. Neither is implemented, and neither is a thing to reach for
during an outage.

### Roles

`config.py` gives every source a `role`.

- **primary** may be scored on and appears in the published license table.
- **validation** may never be scored on, under any circumstance, outage
  included. `build.py` asserts at publish time that no validation-derived value
  reaches `places.json`, because a rule nothing checks is a preference.

tonmcg carries an MIT license, confirmed by reading the `LICENSE` file in the
repository rather than trusting a badge, so redistribution would be permitted.
It is still validation-only. The disqualifier is provenance, not license.

Its value is that MEDSL derives from state-certified returns and tonmcg from
news feeds. Two datasets built the same way agreeing tells you nothing;
agreement between independently derived ones is corroboration. That is why the
cross-source gate blocks rather than warns when the comparison cannot be run at
all.

### Gates

All four block the build. A source that cannot be trusted degrades its fields
to nothing and the interface says so.

1. **Schema** — expected columns per source and per vintage. A `200` carrying
   the wrong shape is the failure that looks most like success.
2. **Coverage** — at least 3,000 counties per cycle, and every non-Alaska
   anchor county present. The count catches a parse regression; the anchor
   check catches the subtler case where plenty of counties are present but the
   ones people search for are not.
3. **Cross-source** — two-party share against tonmcg, per county per cycle.
   Over 2pp warns; over 5pp on more than 1% of counties blocks.
4. **Sanity** — shares within 0-1, and every averaged cycle present for every
   scored county.

### Two states that produce plausible wrong numbers

Both are covered by `tests/test_politics.py` rather than by comments, because
both fail silently.

**Alaska** publishes presidential returns by state house district, not by
borough, and the district identifiers *overlap* borough identifiers. District
13 is `02013` and so is Aleutians East Borough; district 20 is `02020` and so
is Anchorage Municipality. A FIPS join therefore does not drop Alaska, it files
one legislative district's votes under an entire anchor metro, and Anchorage,
Fairbanks-College, Juneau and Ketchikan are all anchors. Alaska is excluded
until a district-to-borough apportionment exists and is tested.

**Connecticut** moved to planning-region FIPS (`09110`-`09190`) while older
cycles use legacy county FIPS (`09001`-`09015`), so the two averaged cycles
share no keys there. Rather than special-casing Connecticut, a county is scored
only when *every* averaged cycle is present. Connecticut falls out of that rule
on its own, and so will the next jurisdiction that re-codes.

### Verifying, once Dataverse is back

```bash
python -m etl.verify politics
```

Runs every gate against the live endpoints and reports whether the source has
earned its flag. It deliberately does not edit `config.py`: a flag a script can
set records nothing.

### Attribution

MIT's returns are CC BY-NC. The manifest carries `attribution_required: true`
so the go-live checklist catches it. The credit itself is a front-end task and
is not done here.
