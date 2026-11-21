# Screen-capture storyline (about 50 s) for Premiere / After Effects

Purpose: a short portfolio clip of `index.html`, the structural/scheduled disruption explorer (v0.5, **NEEDS_VALIDATION**).
The clip must carry the same limits as the page: **structural/scheduled model, not real-time, not demand**. It shows what
the explorer does and what it did not prove. It does not present any station as "the most vulnerable".

## Decision needed before recording: which layer may appear

| Variant | What is on screen | Licensing |
| --- | --- | --- |
| **A. Public layer only (default)** | Hops, fragmentation, isolated stations, isochrones in hops. No seconds. | Topology only (OSM, ODbL). Nothing from CRTM. Safe to publish. |
| **B. With the local time layer** | Adds seconds, bands, assumption ranges. | Shows CRTM-derived planned times. `NOTICE.md` says the per-station table is not distributed because the CRTM and ODbL share-alike terms are not reconciled. A few on-screen values are a smaller publication of the same derived data. **Owner's decision**, not mine; this is a technical reading, not legal advice. |

The shot list below is written for Variant A. Lines marked **[B]** replace or add to it for Variant B.

## Recording set-up

1. `python -m http.server 8000`, open `http://localhost:8000/index.html` in a Chromium browser at 1920 × 1080,
   100 % zoom, light theme. [B] first run `gtfs_ingest.py fetch`, `build` and `build_explorer.py --time`.
2. Hide bookmarks bar and extensions. Keep the **yellow banner visible in every frame** (it is sticky).
3. Record at 60 fps. Move the cursor slowly; leave 0.5 s of stillness after each click.
4. Do not zoom into the OSM tiles beyond what is needed (tile usage policy: no bulk or prefetch; normal browsing only).

## Shot list

| Time | Screen action | On-screen text (Spanish, as in the UI) | Voice-over / caption (English) |
| --- | --- | --- | --- |
| 0:00–0:04 | Full page, map of the network, banner visible. Slow push-in on the banner. | «Modelo estructural/programado. No es tiempo real ni demanda.» | "A structural model of Madrid's Metro. Not real-time. Not demand." |
| 0:04–0:12 | Type "Legazpi" in the search box, Enter. Map flies in, stations turn orange to red along the southern line. Card appears: pairs disconnected 0; mean increase. [B] switch to *Tiempo programado*; card shows the seconds and the range. | Legend: «Aumento medio hacia cada destino…» | "Close one station. The colour shows how much longer trips to each destination get, among the trips that survive." |
| 0:12–0:20 | Switch *Perturbación* to *Correspondencia deshabilitada*, then back. [B] change *Franja horaria*: the numbers barely move. | | "Closing a station and disabling only its interchange are different questions. And the time of day barely changes the order." |
| 0:20–0:30 | Select Pueblo Nuevo. Dark stations appear (isolated). Card: 4.296 pares desconectados, red warning box. Hold 2 s on the warning. | «Este cierre desconecta pares. El aumento medio no los cuenta, así que subestima el efecto…» | "Some closures cut the network apart. My own effect size ignores disconnected pairs, so it flatters exactly these stations." |
| 0:30–0:38 | Scroll the sidebar to the two tabs. Click *Desconectan pares (84)*, then *No desconectan (158)*. Hold on a row with the baseline line "intermediación: puesto …". | «No hay un único orden…» | "So there is no single ranking. Two lists, each next to what plain betweenness would say." |
| 0:38–0:46 | Scroll to *Qué se probó y qué no*. Slowly reveal the four bullets. | «Ese veredicto depende de la medida…» | "The pre-registered test said simulation adds value. A post-hoc check shows that depends on how disconnected pairs are counted." |
| 0:46–0:50 | Cut to a static end card (After Effects): dark background, three lines. | «NEEDS_VALIDATION · © OpenStreetMap contributors · Powered by CRTM · sin respaldo del CRTM» | "Status: needs validation. No external check was possible." |

## Motion and colour notes (After Effects)

- Use the page's own palette: banner `#fff1c9` on text `#4a3300`; legend ramp `#fdcc8a #fc8d59 #e34a33 #b30000`; isolated stations
  `#1d2126` with a white ring. Do not recolour the map to a rainbow.
- Highlights: a 3 px `#1d4e89` rounded rectangle around the card or list while it is discussed; no glow, no screen shake.
- Captions at least 28 px, white on a 70 % black bar, kept inside the safe margin. Burn captions in (the clip may be viewed muted).
- Keep every number exactly as it is on screen. Do not round or restyle a value in post.
- Keep a still of the banner in the end card: it is part of the claim.

## What the clip must not say

- "Most vulnerable", "critical", "resilient" or "robust" for any station or for the network.
- That the simulation beats betweenness, or that times were measured.
- That the project is endorsed by the CRTM or Metro de Madrid.
