"""Tests for gtfs_ingest.py on synthetic feeds with known answers (no network, no CRTM data needed).

Run: python -m unittest discover -s research/time_weighted_v05
The last class checks the real derived artefacts only when they exist locally.
"""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import gtfs_ingest as G  # noqa: E402

H = 3600
NODES = {
    "A": {"name": "Alfa", "lines": ["L1"], "lonlat": (-3.70, 40.40)},
    "B": {"name": "Beta", "lines": ["L1", "L3"], "lonlat": (-3.69, 40.40)},
    "C": {"name": "Gamma", "lines": ["L1", "L3"], "lonlat": (-3.68, 40.40)},
    "D": {"name": "Delta", "lines": ["L3"], "lonlat": (-3.67, 40.40)},
}
EDGES = {frozenset("AB"): {"L1"}, frozenset("BC"): {"L1", "L3"}, frozenset("CD"): {"L3"}}


def stop(i, name, lon):
    return {"stop_id": i, "stop_name": name, "stop_lat": "40.40", "stop_lon": str(lon)}


def rows(tid, seq):
    return [{"trip_id": tid, "arrival_time": a, "departure_time": a, "stop_id": s, "stop_sequence": str(i)}
            for i, (s, a) in enumerate(seq)]


def feed():
    return {
        "routes": [{"route_id": "r1", "route_short_name": "1"}, {"route_id": "r3", "route_short_name": "3"}],
        "trips": [
            {"trip_id": "t0", "route_id": "r1", "service_id": "wk", "direction_id": "0"},
            {"trip_id": "t1", "route_id": "r1", "service_id": "wk", "direction_id": "1"},
            {"trip_id": "ts", "route_id": "r1", "service_id": "sat", "direction_id": "0"},
        ],
        "stops": [stop("sa", "ALFA", -3.70), stop("sb", "BETA", -3.69), stop("sc", "GAMMA", -3.68)],
        "stop_times": (rows("t0", [("sa", "07:00:00"), ("sb", "07:01:40"), ("sc", "07:04:10")])
                       + rows("t1", [("sc", "07:00:00"), ("sb", "07:02:30"), ("sa", "07:04:10")])
                       + rows("ts", [("sa", "06:00:00"), ("sb", "06:01:40")])),
        "frequencies": [
            {"trip_id": "t0", "start_time": "07:00:00", "end_time": "10:00:00", "headway_secs": "600", "exact_times": ""},
            {"trip_id": "t1", "start_time": "07:00:00", "end_time": "10:00:00", "headway_secs": "300", "exact_times": ""},
            {"trip_id": "ts", "start_time": "06:00:00", "end_time": "24:00:00", "headway_secs": "900", "exact_times": ""},
        ],
        "calendar": [
            {"service_id": "wk", "monday": "1", "tuesday": "1", "wednesday": "1", "thursday": "1", "friday": "0",
             "saturday": "0", "sunday": "0", "start_date": "20250101", "end_date": "20251231"},
            {"service_id": "sat", "monday": "0", "tuesday": "0", "wednesday": "0", "thursday": "0", "friday": "0",
             "saturday": "1", "sunday": "0", "start_date": "20250101", "end_date": "20251231"},
        ],
        "feed_info": [],
        "_files": [],
    }


MATCH = {"sa": "A", "sb": "B", "sc": "C"}


class Helpers(unittest.TestCase):
    def test_hms_handles_service_day_overflow(self):
        self.assertEqual(G.hms("25:30:05"), 25 * H + 30 * 60 + 5)

    def test_union_length_merges_overlaps(self):
        self.assertEqual(G._union_len([(0, 100), (50, 200), (300, 400)], [(0, 1000)]), 300)
        self.assertEqual(G._union_len([(0, 100)], [(50, 70)]), 20)

    def test_read_gtfs_reads_from_zip_and_tolerates_missing_tables(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.zip"
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("routes.txt", "﻿route_id,route_short_name\nr1,1\n")
            g = G.read_gtfs(p)
            self.assertEqual(g["routes"][0]["route_short_name"], "1")
            self.assertEqual(g["stop_times"], [])


class Matching(unittest.TestCase):
    def test_name_and_line_match_and_unmatched_far_stop(self):
        f = feed()
        f["stops"].append(stop("sx", "NOWHERE", -3.0))
        f["stop_times"] += rows("t0", [("sx", "07:10:00")])
        m = G.match_stops(f, NODES)
        self.assertEqual(m["match"], MATCH)
        tiers = {r["stop_id"]: r["tier"] for r in m["report"]}
        self.assertEqual(tiers["sa"], "name+line")
        self.assertEqual(tiers["sx"], "unmatched")

    def test_distance_fallback_when_name_differs(self):
        f = feed()
        f["stops"][0]["stop_name"] = "TOTALLY OTHER NAME"
        m = G.match_stops(f, NODES)
        self.assertEqual(m["match"]["sa"], "A")
        self.assertEqual({r["stop_id"]: r["tier"] for r in m["report"]}["sa"], "distance (name differs)")


class Legs(unittest.TestCase):
    def test_leg_seconds_are_exact_and_directional(self):
        r = G.derive_legs(feed(), MATCH, EDGES)
        self.assertEqual(r["legs"][("L1", "A", "B")], [100, 100])  # t0 and the Saturday trip
        self.assertEqual(r["legs"][("L1", "B", "C")], [150])
        self.assertEqual(r["legs"][("L1", "C", "B")], [150])
        self.assertEqual(r["legs"][("L1", "B", "A")], [100])

    def test_non_positive_legs_are_reported_not_used(self):
        f = feed()
        f["stop_times"] += rows("t2", [("sa", "08:00:00"), ("sb", "08:00:00"), ("sa", "07:59:00")])
        f["trips"].append({"trip_id": "t2", "route_id": "r1", "service_id": "wk", "direction_id": "0"})
        r = G.derive_legs(f, MATCH, EDGES)
        self.assertEqual(len(r["bad_times"]), 2)  # zero and negative
        self.assertEqual(r["legs"][("L1", "A", "B")], [100, 100])  # unchanged

    def test_non_edge_pair_with_positive_time_is_a_contradiction(self):
        f = feed()
        f["stop_times"] = rows("t0", [("sa", "07:00:00"), ("sc", "07:05:00")])
        r = G.derive_legs(f, MATCH, EDGES)
        self.assertEqual(r["contradictions"], [("L1", "A", "C")])
        self.assertEqual(len(r["legs"]), 0)


class Headways(unittest.TestCase):
    def test_peak_headway_and_served_fraction(self):
        h = G.derive_headways(feed(), MATCH)["headways"]
        # t0 runs 07-10 at 600 s: 18 trains in a 6 h band -> 3/h -> headway 1200 s; served 3 h of 6 h
        v = h[("A", "L1", "0", "weekday_peak")]
        self.assertEqual((v["trains_per_hour"], v["headway_s"], v["served_fraction"]), (3.0, 1200.0, 0.5))

    def test_window_is_shifted_by_the_stop_offset(self):
        f = feed()
        f["stop_times"] = rows("t0", [("sa", "07:00:00"), ("sb", "08:00:00")])
        h = G.derive_headways(f, MATCH)["headways"]
        # at B the window is 08:00-11:00: only 2 h fall in 07-10 -> 12 trains / 6 h = 2/h
        self.assertEqual(h[("B", "L1", "0", "weekday_peak")]["trains_per_hour"], 2.0)
        self.assertEqual(h[("A", "L1", "0", "weekday_peak")]["trains_per_hour"], 3.0)

    def test_day_pattern_selects_the_service(self):
        h = G.derive_headways(feed(), MATCH)["headways"]
        sat = h[("A", "L1", "0", "saturday")]
        self.assertEqual((sat["headway_s"], sat["served_fraction"]), (900.0, 1.0))
        self.assertNotIn(("A", "L1", "0", "sunday"), h)
        self.assertNotIn(("A", "L1", "0", "evening"), h)  # the weekday window ends at 10:00

    def test_exact_times_rows_are_counted(self):
        f = feed()
        f["frequencies"][0]["exact_times"] = "1"
        self.assertEqual(G.derive_headways(f, {})["exact_times_rows"], 1)

    def test_directions_are_collapsed_by_mean(self):
        h = G.derive_headways(feed(), MATCH)["headways"]
        rows_ = {(r["node"], r["line"], r["band"]): r for r in G.node_headways(h)}
        # B: windows shifted by the stop offsets (100 s dir0, 150 s dir1), so slightly under 07-10 overlap:
        # dir0 21600/(10700/600) = 1211.2 s; dir1 21600/(10650/300) = 608.5 s; mean 909.8 (rounded values -> 909.9)
        self.assertAlmostEqual(rows_[("B", "L1", "weekday_peak")]["headway_s"], 909.9, delta=0.2)


class Imputation(unittest.TestCase):
    ROWS = [
        {"NUMEROLINEAUSUARIO": "3", "SENTIDO": 1, "NUMEROORDEN": 1, "DENOMINACION": "BETA",
         "LONGITUDTRAMOANTERIOR": None, "VELOCIDADTRAMOANTERIOR": None},
        {"NUMEROLINEAUSUARIO": "3", "SENTIDO": 1, "NUMEROORDEN": 2, "DENOMINACION": "GAMMA",
         "LONGITUDTRAMOANTERIOR": 1000.0, "VELOCIDADTRAMOANTERIOR": 36.0},
        {"NUMEROLINEAUSUARIO": "3", "SENTIDO": 1, "NUMEROORDEN": 3, "DENOMINACION": "DELTA",
         "LONGITUDTRAMOANTERIOR": 500.0, "VELOCIDADTRAMOANTERIOR": 36.0},
    ]

    def test_length_over_speed(self):
        r = G.arcgis_legs(self.ROWS, NODES)
        self.assertAlmostEqual(r[("L3", "B", "C")]["seconds"], 100.0)  # 1000 m at 10 m/s
        self.assertAlmostEqual(r[("L3", "C", "D")]["seconds"], 50.0)
        self.assertEqual(len(r), 2)

    def test_rows_without_speed_are_skipped(self):
        rows_ = [dict(self.ROWS[0]), dict(self.ROWS[1], VELOCIDADTRAMOANTERIOR=None)]
        self.assertEqual(G.arcgis_legs(rows_, NODES), {})

    def test_validation_ratio_against_gtfs(self):
        imp = {("L1", "A", "B"): {"seconds": 110.0, "length_m": 1.0, "speed_kmh": 1.0}}
        res = G.validate_imputation(imp, {("L1", "A", "B"): [100, 100]})
        self.assertEqual((res["L1"]["median_ratio"], res["L1"]["n_legs"]), (1.1, 1))


class RideTable(unittest.TestCase):
    def test_gtfs_preferred_mean_of_directions_imputation_fallback_and_missing(self):
        legs = {("L1", "A", "B"): [100], ("L1", "B", "A"): [120]}
        imp = {("L3", "C", "D"): {"seconds": 50.0, "length_m": 500.0, "speed_kmh": 36.0}}
        rides, missing = G.build_ride_table(EDGES, legs, imp)
        by = {(r["line"], r["a"], r["b"]): r for r in rides}
        self.assertEqual(by[("L1", "A", "B")]["seconds"], 110.0)
        self.assertEqual(by[("L1", "A", "B")]["source"], "gtfs")
        self.assertEqual(by[("L3", "C", "D")]["source"], "imputed_arcgis_length_speed")
        self.assertEqual({(m["line"], m["a"], m["b"]) for m in missing}, {("L1", "B", "C"), ("L3", "B", "C")})
        self.assertTrue(all(r["seconds"] > 0 for r in rides))


class RealArtefacts(unittest.TestCase):
    """Only when `gtfs_ingest.py build` has been run locally."""

    @classmethod
    def setUpClass(cls):
        p = ROOT / "data" / "gtfs_derived"
        if not (p / "ride_times.json").exists():
            raise unittest.SkipTest("data/gtfs_derived not present (run gtfs_ingest.py fetch && build)")
        cls.rides = json.loads((p / "ride_times.json").read_text(encoding="utf-8"))
        cls.man = json.loads((p / "gtfs_manifest.json").read_text(encoding="utf-8"))

    def test_every_ride_time_is_positive_and_sourced(self):
        self.assertTrue(all(r["seconds"] > 0 for r in self.rides))
        self.assertTrue(all(r["source"] in ("gtfs", "imputed_arcgis_length_speed") for r in self.rides))

    def test_counts_match_manifest(self):
        self.assertEqual(len(self.rides), self.man["rides"]["total_ride_edges"] - self.man["rides"]["without_any_time"])
        self.assertEqual(self.man["rides"]["without_any_time"], 0)

    def test_only_lines_without_gtfs_trips_are_imputed(self):
        lines = {r["line"] for r in self.rides if r["source"] != "gtfs"}
        self.assertTrue(lines <= set(self.man["routes"]["graph_lines_without_gtfs_times"]))


if __name__ == "__main__":
    unittest.main()
