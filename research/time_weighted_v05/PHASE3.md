# Phase 3 report: disruption explorer (v0.5 visual layer)

**Status: NEEDS_VALIDATION.** Structural/scheduled model. Not real-time, not demand, not observed. This phase adds a visual
layer; it computes no new hypothesis test. Storyline for a screen capture: [STORYLINE.md](STORYLINE.md).

## 1. What was built

| Item | Where | Notes |
| --- | --- | --- |
| Public data layer | `data/explorer/disruption_topology.json` (473 KiB, ODbL) | Topology only (ride count, hop mode) from the frozen v0.1.0 snapshot. No CRTM data, no times. |
| Local time layer | `research/time_weighted_v05/local/explorer_time.json` (1.7 MiB, **git-ignored**) | Planned times joined with OSM ids. Built by `build_explorer.py --time`. Not distributed (decision of the owner, recorded in `NOTICE.md`). |
| Builder | `build_explorer.py` | `python build_explorer.py`, `--check`, `--time --workers N`. |
| Page | `index.html` (Spanish) | One static file, Leaflet 1.9.4 with SRI, no server. |
| Checks | `validate.py` (+5 checks, 51/51), `test_build_explorer.py` (9 tests) | |
| Storyline | `STORYLINE.md` | 50 s, shot list, two variants (see 4). |

Page features: click or search a station; closure or interchange disabled (38 interchanges); pairs disconnected out of the
eligible total; stations cut off from the main piece; mean increase over pairs that stay connected; map coloured by effect
per destination (square-root classes, ColorBrewer OrRd) or by reach from the station (isochrone classes, Blues); two
separate lists (closures that disconnect pairs, closures that do not) with degree, line count and the betweenness position
beside each row; Spearman correlation recomputed in the browser; band selector, assumption range (162 cells) and
through-running value when the local layer is present. A sticky banner states "Modelo estructural/programado. No es tiempo
real ni demanda." and the status NEEDS_VALIDATION. Attribution: © OpenStreetMap contributors, Powered by CRTM, no endorsement.

**Deliberately absent:** one global "vulnerability ranking". Phase 2 showed the pooled order is produced by the effect-size
definition (see REPORT.md section 1), so the page shows the two groups separately and prints the post-hoc limit.

## 2. Evidence

Commands run on Windows 11, Python 3.14.5. Trimmed outputs.

```
$ python build_explorer.py && python build_explorer.py --check
wrote data\explorer\disruption_topology.json (473 KiB)
public file matches a fresh build

$ python validate.py | tail -1
51/51 checks passed          # includes: explorer replicates v0.4 (84 closures; 240 / 1,180 / 4,296; 1 interchange, 1,410)

$ python -m unittest discover -s research/time_weighted_v05
Ran 48 tests ... OK         # 39 earlier + 9 new
```

- **G1 without any CRTM input.** The public layer reproduces v0.4 exactly: 84 fragmenting closures, smallest 240, median
  1,180, largest 4,296 unordered pairs; one interchange disabling disconnects 1,410 pairs (6 stations cut off).
- **Internal consistency.** For a closure, the mean of the per-destination increases equals the pair-level mean increase
  (checked for one station on the local layer: 250.7 s both ways). The in-browser Spearman values (0.51 / 0.89 on the time
  layer; 0.50 / 0.87 on hops) match the post-hoc numbers in REPORT.md and `posthoc_summary.json`.
- **Browser checks** (built-in browser, Chromium-based, localhost). No console errors when both layers load. With the local
  file absent the page degrades to topology only (message shown, time controls disabled); the only console entry is the 404 of
  the optional file, which is requested only on `localhost`.
- **Accessibility, equivalent partial checks** (not a Lighthouse run): 291 text elements measured against the WCAG 2.x
  contrast formula, minimum 4.65:1, none below the threshold (4.5:1; 3:1 for large text). Every input, select and button has
  a name; no positive `tabindex`; skip link lands on the panel; heading order H1, H2, H3, H4; `lang="es"`, title and viewport
  present; map region has a text alternative and every station is reachable by keyboard through the search box and the lists.
  No horizontal overflow at 375 px; the banner is sticky.
- **Colour-blind safety by construction, not by simulation.** Both ramps are ColorBrewer sequential schemes that are
  lightness-ordered; class size and the dark-with-ring marker for isolated stations repeat the colour cue.

## 3. What failed or needed a fix during the phase

- The local time layer crashed once with `OpenBLAS ... Memory allocation failed` at 7 workers; rerun with 3 workers and one
  BLAS thread each succeeded (167 cells).
- A disabled interchange reaches both of its pieces, so "the largest component" is ambiguous. The builder now uses the best
  connected *other* station as the reference piece (`exclude=`), and a unit test fixes the behaviour.
- With a negligible effect the legend showed classes such as "0,00–0,00"; it now prints a single "sin cambio apreciable" line.
- Line-pill text failed contrast for mid-tone OSM colours (down to 2.82:1); the text colour is now the better of near-black and
  white by contrast ratio.
- A linear colour scale was flattened by a few extreme destinations (about 58 min mean increase at the far end of one line);
  it is now square-root classes, stated in the legend.
- Hop effects were rounded to 2 decimals, which made the in-browser Spearman 0.53 instead of 0.50; they are stored with 4 decimals.

## 4. Decisions that are the owner's

1. **Which layer may appear in the clip.** The public page shows no CRTM-derived value. A clip recorded with the local layer
   would publish a few of them (see STORYLINE.md, Variants A and B). Default: Variant A.
2. **GitHub Pages.** After the merge the page and `data/explorer/disruption_topology.json` go public if Pages serves `main`.
   The page itself does not load the local layer outside `localhost`.
3. **NOTICE.md reading.** Still a technical reading, not legal advice; the CRTM "same type of licence" and "always up to date"
   wording stays a doubt.
4. `research/temporal_validation_v03/` remains untracked.

## 5. Unknown, assumed, not done

- **Not run:** Lighthouse itself (not installed; installing it needs a download and a local Chrome). Reproduce with
  `npx lighthouse http://localhost:8000/index.html --only-categories=accessibility,performance,best-practices`. Also not done:
  screen-reader testing, a colour-vision simulation tool, Firefox, Safari, touch devices (the 375 px check is an emulated
  viewport), any Linux or macOS run.
- **Performance** was not measured meaningfully: the local load time (about 0.2 s) says nothing about the public site, where
  Leaflet and the tiles come from the network. The public JSON is 473 KiB before compression.
- **Assumed:** band clock times, transfer time, Line 3 headway and the imputed Line 3 speed, all swept in Phase 2; the map view
  of the destination effect uses the weekday-peak central parameters only.
- **Limits that remain:** a station is closed, not a line section; no demand, crowding, walking between different station
  names, replacement buses or recovery; isochrones are for the intact network and show reach, not accessibility; the mobile
  layout puts the map above the panel, so selecting from a list scrolls the map out of view.
- **Literature:** none cited and none verified for this phase (`[X]`).

## 6. Reproduce

```powershell
.venv\Scripts\python build_explorer.py            # public layer
.venv\Scripts\python build_explorer.py --check
.venv\Scripts\python validate.py
.venv\Scripts\python -m unittest discover -s research/time_weighted_v05
.venv\Scripts\python -m http.server 8000          # open http://localhost:8000/
# local time layer (needs Phase 1 outputs):
.venv\Scripts\python gtfs_ingest.py fetch ; .venv\Scripts\python gtfs_ingest.py build
.venv\Scripts\python build_explorer.py --time --workers 3
```
