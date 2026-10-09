import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_inventory import analyze, human_size, parse_datetime, parse_size


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, tzinfo=timezone.utc)
        self.items = [
            {"id":"a","name":"clip.mp4","mimeType":"video/mp4","size":"2048","modifiedTime":"2020-01-01T00:00:00Z","md5Checksum":"abc"},
            {"id":"b","name":"clip-copy.mp4","mimeType":"video/mp4","size":2048,"modifiedTime":"2020-01-02T00:00:00Z","md5Checksum":"abc"},
            {"id":"c","name":"clip.mp4","mimeType":"video/mp4","modifiedTime":"2026-01-01T00:00:00Z"},
            {"id":"d","name":"native doc","mimeType":"application/vnd.google-apps.document","modifiedTime":"invalid"}
        ]

    def test_file_and_missing_metadata_counts(self):
        r = analyze(self.items, 730, self.now)
        self.assertEqual(r["file_count"], 4)
        self.assertEqual(r["unknown_size_count"], 2)
        self.assertEqual(r["unknown_modified_date_count"], 1)

    def test_checksum_duplicate_candidates(self):
        self.assertEqual(len(analyze(self.items, 730, self.now)["exact_duplicate_groups"]), 1)

    def test_same_name_candidates_are_separate(self):
        r = analyze(self.items, 730, self.now)
        self.assertEqual(r["same_name_candidates"][0]["name"], "clip.mp4")

    def test_old_file_cutoff(self):
        ids = {x["id"] for x in analyze(self.items, 730, self.now)["older_than_cutoff"]}
        self.assertEqual(ids, {"a", "b"})

    def test_helpers(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(1024), "1.0 KB")
        self.assertIsNone(parse_size("bad"))
        self.assertIsNone(parse_datetime("bad"))

    def test_report_has_no_mutation_result(self):
        self.assertNotIn("actions_executed", analyze(self.items, 730, self.now))


if __name__ == "__main__":
    unittest.main()
