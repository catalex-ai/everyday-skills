import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_inventory import analyze  # noqa: E402
from mcp_bridge import convert, describe, normalize  # noqa: E402

FOLDER = "application/vnd.google-apps.folder"


class ShapeTests(unittest.TestCase):
    """Servers disagree about shape; all of these must yield the same records."""

    expected = [{"id": "1", "name": "a.pdf"}]

    def assert_one_record(self, payload):
        records, _ = convert(payload)
        self.assertEqual([{"id": r["id"], "name": r["name"]} for r in records], self.expected)

    def test_bare_list(self):
        self.assert_one_record([{"id": "1", "name": "a.pdf"}])

    def test_files_key(self):
        self.assert_one_record({"files": [{"id": "1", "name": "a.pdf"}]})

    def test_other_list_keys(self):
        for key in ("items", "results", "data", "entries", "documents"):
            self.assert_one_record({key: [{"id": "1", "name": "a.pdf"}]})

    def test_mcp_content_block_with_json_text(self):
        inner = json.dumps({"files": [{"id": "1", "name": "a.pdf"}]})
        self.assert_one_record({"content": [{"type": "text", "text": inner}]})

    def test_single_record_not_in_a_list(self):
        self.assert_one_record({"id": "1", "name": "a.pdf"})

    def test_nested_result_wrapper(self):
        self.assert_one_record({"result": {"files": [{"id": "1", "name": "a.pdf"}]}})

    def test_non_json_text_block_is_ignored_without_crashing(self):
        records, _ = convert({"content": [{"type": "text", "text": "No files found."}]})
        self.assertEqual(records, [])


class FieldAliasTests(unittest.TestCase):
    def test_maps_camel_and_snake_aliases_onto_drive_names(self):
        record = normalize({
            "fileId": "xyz",
            "title": "Deck.pdf",
            "mime_type": "application/pdf",
            "sizeBytes": 2048,
            "updatedAt": "2021-01-01T00:00:00Z",
            "md5": "abc",
            "webUrl": "https://example.test/xyz",
        })
        self.assertEqual(record, {
            "id": "xyz",
            "name": "Deck.pdf",
            "mimeType": "application/pdf",
            "size": "2048",
            "modifiedTime": "2021-01-01T00:00:00Z",
            "md5Checksum": "abc",
            "webViewLink": "https://example.test/xyz",
        })

    def test_size_is_stringified_and_non_numeric_size_dropped(self):
        self.assertEqual(normalize({"id": "1", "size": 10})["size"], "10")
        self.assertNotIn("size", normalize({"id": "1", "size": "big"}))

    def test_canonical_name_wins_over_alias(self):
        record = normalize({"id": "right", "fileId": "wrong", "name": "a", "title": "b"})
        self.assertEqual(record["id"], "right")
        self.assertEqual(record["name"], "a")

    def test_single_parent_is_wrapped_in_a_list(self):
        self.assertEqual(normalize({"id": "1", "parentId": "p"})["parents"], ["p"])

    def test_empty_values_are_treated_as_absent(self):
        self.assertNotIn("size", normalize({"id": "1", "size": None, "sizeBytes": ""}))


class HygieneTests(unittest.TestCase):
    def test_folders_are_dropped_unless_asked_for(self):
        payload = [{"id": "f", "name": "Folder", "mimeType": FOLDER},
                   {"id": "a", "name": "a.pdf", "mimeType": "application/pdf"}]
        records, stats = convert(payload)
        self.assertEqual([r["id"] for r in records], ["a"])
        self.assertEqual(stats["folders_skipped"], 1)
        kept, _ = convert(payload, keep_folders=True)
        self.assertEqual(len(kept), 2)

    def test_repeated_ids_from_overlapping_pages_are_dropped_once(self):
        payload = [{"id": "a", "name": "a.pdf"}, {"id": "a", "name": "a.pdf"}]
        records, stats = convert(payload)
        self.assertEqual(len(records), 1)
        self.assertEqual(stats["repeats_skipped"], 1)

    def test_records_without_id_or_name_are_ignored(self):
        records, _ = convert([{"mimeType": "application/pdf"}])
        self.assertEqual(records, [])

    def test_missing_field_counts_are_reported(self):
        records, stats = convert([{"id": "a", "name": "a.pdf"}])
        self.assertEqual(stats["missing_size"], 1)
        self.assertEqual(stats["missing_checksum"], 1)
        self.assertEqual(stats["missing_modified"], 1)

    def test_describe_warns_when_no_checksums_exist_at_all(self):
        _, stats = convert([{"id": "a", "name": "a.pdf"}])
        self.assertIn("fall back to names", describe(stats))

    def test_describe_is_quiet_when_nothing_is_missing(self):
        _, stats = convert([{"id": "a", "name": "a.pdf", "size": 1,
                             "modifiedTime": "2026-01-01T00:00:00Z", "md5Checksum": "x"}])
        self.assertEqual(describe(stats), "1 file records normalized")


class EndToEndTests(unittest.TestCase):
    def test_normalized_output_feeds_the_analyzer(self):
        payload = {"content": [{"type": "text", "text": json.dumps({"files": [
            {"fileId": "1", "title": "clip.mov", "sizeBytes": 1000,
             "updatedAt": "2020-01-01T00:00:00Z", "md5": "same"},
            {"fileId": "2", "title": "clip (1).mov", "sizeBytes": 1000,
             "updatedAt": "2020-01-02T00:00:00Z", "md5": "same"},
            {"fileId": "3", "title": "Notes",
             "mime_type": "application/vnd.google-apps.document",
             "updatedAt": "2026-09-01T00:00:00Z"},
        ]})}]}
        records, _ = convert(payload)
        report = analyze(records, older_than_days=730)
        self.assertEqual(report["file_count"], 3)
        self.assertEqual(len(report["exact_duplicate_groups"]), 1)
        self.assertEqual(report["unknown_size_count"], 1)


if __name__ == "__main__":
    unittest.main()
