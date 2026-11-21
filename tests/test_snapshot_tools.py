"""Offline tests for the next-snapshot protocol: raw-response archive and the build_graph.py write guards. No network."""
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import snapshot_tools as ST  # noqa: E402

PAYLOAD = {"version": 0.6, "osm3s": {"timestamp_osm_base": "2026-12-01T00:00:00Z"},
           "elements": [{"type": "relation", "id": 1, "tags": {"name": "Línea 1", "ref": "L1"}}]}


class Archive(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name) / "raw"

    def tearDown(self):
        self._tmp.cleanup()

    def test_archive_then_verify_is_clean(self):
        e = ST.archive_payload(self.raw, "01_discovery", "q", "https://example.test/api", PAYLOAD, "2026-12-01T00:01:00+00:00")
        self.assertEqual(e["osm_base_timestamp"], "2026-12-01T00:00:00Z")
        self.assertEqual(e["elements"], 1)
        self.assertEqual(ST.verify_raw_archive(self.raw), [])

    def test_roundtrip_preserves_the_payload_and_utf8(self):
        ST.archive_payload(self.raw, "01_a", "q", "e", PAYLOAD, "t")
        back = json.loads(gzip.decompress((self.raw / "01_a.json.gz").read_bytes()).decode("utf-8"))
        self.assertEqual(back, PAYLOAD)

    def test_canonical_form_ignores_key_order(self):
        self.assertEqual(ST.canonical({"b": 1, "a": 2}), ST.canonical({"a": 2, "b": 1}))

    def test_manifest_carries_the_odbl_notice(self):
        ST.archive_payload(self.raw, "01_a", "q", "e", PAYLOAD, "t")
        m = json.loads((self.raw / ST.RAW_MANIFEST).read_text(encoding="utf-8"))
        self.assertIn("ODbL", m["licence"])
        self.assertIn("OpenStreetMap", m["attribution"])
        self.assertIn("CRTM", m["terms"])

    def test_tampered_file_is_detected(self):
        ST.archive_payload(self.raw, "01_a", "q", "e", PAYLOAD, "t")
        (self.raw / "01_a.json.gz").write_bytes(gzip.compress(ST.canonical({**PAYLOAD, "elements": []})))
        self.assertTrue(any("hash" in p for p in ST.verify_raw_archive(self.raw)))

    def test_missing_and_unlisted_files_are_detected(self):
        ST.archive_payload(self.raw, "01_a", "q", "e", PAYLOAD, "t")
        (self.raw / "02_extra.json.gz").write_bytes(gzip.compress(b"{}"))
        self.assertTrue(any("not in the manifest" in p for p in ST.verify_raw_archive(self.raw)))
        (self.raw / "01_a.json.gz").unlink()
        self.assertTrue(any("missing" in p for p in ST.verify_raw_archive(self.raw)))

    def test_duplicate_names_are_refused(self):
        ST.archive_payload(self.raw, "01_a", "q", "e", PAYLOAD, "t")
        with self.assertRaises(ValueError):
            ST.archive_payload(self.raw, "01_a", "q", "e", PAYLOAD, "t")

    def test_empty_directory_is_reported(self):
        self.raw.mkdir()
        self.assertEqual(ST.verify_raw_archive(self.raw), ["RAW_MANIFEST.json missing"])


class BuildGraphGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import build_graph as BG  # heavy import (City2Graph); needs the project requirements
        cls.BG = BG

    def test_out_is_required(self):
        with self.assertRaises(SystemExit):
            self.BG.main([])

    def test_the_frozen_data_directory_is_refused(self):
        with self.assertRaises(SystemExit) as cm:
            self.BG.main(["--out", str(self.BG.DATA)])
        self.assertIn("refusing", str(cm.exception))

    def test_a_non_empty_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.txt").write_text("x")
            with self.assertRaises(SystemExit) as cm:
                self.BG.main(["--out", d])
            self.assertIn("refusing", str(cm.exception))

    def test_city2graph_recorder_archives_each_response(self):
        import city2graph.gtfs.sources as src
        original, old_dir, old_seq = src._request_osm, self.BG.RAW_DIR, self.BG._raw_seq
        with tempfile.TemporaryDirectory() as d:
            try:
                src._request_osm = lambda query, endpoint, timeout: PAYLOAD
                self.BG.RAW_DIR, self.BG._raw_seq = Path(d) / "raw", 0
                self.BG.install_city2graph_recorder()
                self.assertEqual(src._request_osm("q", "https://example.test", 5), PAYLOAD)
                self.assertEqual(ST.verify_raw_archive(Path(d) / "raw"), [])
                self.assertTrue((Path(d) / "raw" / "01_city2graph.json.gz").exists())
            finally:
                src._request_osm, self.BG.RAW_DIR, self.BG._raw_seq = original, old_dir, old_seq


if __name__ == "__main__":
    unittest.main()
