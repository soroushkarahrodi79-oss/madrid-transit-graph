# Decision memo: GO / FREEZE / PIVOT (v0.5 line)

Date: 2026-11-21. Author: Claude (research engineering), for the repository owner. Status of every study here: **NEEDS_VALIDATION**.
This memo recommended FREEZE. **Decision (owner, 2026-11-21): FREEZE.** The README carries the status block.

## Recommendation: FREEZE the research claim, keep the repository as a documented demonstrator

Not GO: nothing here is validated, and no validation path exists today. Not PIVOT yet: a pivot needs a specific question that
nobody has stated (see the table).

## What stands (evidence in the repo)

- A frozen, hash-checked v0.1.0 topology of Metro de Madrid (242 stations, 277 edges, 38 interchanges) and a reproducible
  pipeline around it: CI on Linux and Windows (Python 3.12 to 3.14, all green on PR #12), a next-snapshot protocol with raw
  Overpass archiving, and a static explorer. A live snapshot two days later gave byte-identical topology files.
- Pre-registered work with negative and qualified results reported at equal weight (v0.5: PRE_REGISTRATION.md committed before the run).
- v0.4: fragmentation under station removal, replicated exactly by the public explorer layer (84 of 242 closures fragment the network).

## Why not GO

1. **The v0.5 verdict depends on the metric.** The pre-registered rule says ADDED_VALUE (rho_max 0.52), but the effect size ignores
   disconnected pairs. Among the 158 non-fragmenting closures rho with betweenness is about 0.91. The supportable statement is
   about where the rankings agree, not that simulation adds value.
2. **Planned times add little.** They rank closures almost as hop counts do (rho 0.956); time bands change nothing (rho >= 0.999).
3. **The disruption is not the operational one.** Closing a station is not closing a line section: letting trains pass cuts the mean
   effect from 25.7 s to 2.0 s. No demand, crowding, walking between different station names or replacement buses.
4. **No external check was possible.** The one readable closure notice (Line 6, November 2026) gives a replacement bus and its
   interval, with no measured travel time or ridership to compare against.
5. **Data limits.** The CRTM GTFS is expired (calendar to 2026-05-27), has no Line 3 (imputed), no transfers; waits and transfers are
   assumed. The timing-derived data cannot be redistributed (unresolved licence interplay), so the strongest layer is local-only.

## Options

| Option | What would have to be true | Cost | Main risk |
| --- | --- | --- | --- |
| **GO** (claim a result) | A documented closure with measured travel times or ridership; a pre-registered section-closure model | New data source plus a new model and pre-registration | None exists now: a GO would be unsupported |
| **FREEZE** (recommended) | Nothing more | README status block, this memo; no new analysis | Looks like a stop; it is an honest end state |
| **PIVOT** | A stated question closer to destination planning (for example structural access from stations to visitor attractions) with public data (OSM, ODbL) | New pre-registration, new data layer; the pipeline and CI are reusable | Still structural and unvalidated; scope creep. Unknown: which question you want |

## If FREEZE is chosen

Mark the README (Spanish) with status, date and reason; name the conditions to reopen (an external validation source, or a
specific question). I have not seen the HATI "ABSTAIN" README, so I would draft the wording and you would align it to that precedent.

## Unknown or unverified

Legal reading of the CRTM and ODbL interplay (technical reading only); literature on weighted vulnerability of metro networks
(none cited, none verified, no novelty claim); Lighthouse and screen-reader results for the page; any run outside Windows and the
GitHub runners.

## Decisions for the owner

1. GO, FREEZE or PIVOT. 2. If FREEZE: approve the README wording and the HATI-style format. 3. If PIVOT: the question and the data.
4. Still open: clip variant (public layer only is the default), `research/temporal_validation_v03/` (untracked), branch protection.
