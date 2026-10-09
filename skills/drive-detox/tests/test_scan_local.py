import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_inventory import analyze
from scan_local import scan


class ScanLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.txt").write_text("same bytes", encoding="utf-8")
        (self.root / "nested").mkdir()
        (self.root / "nested" / "a-copy.txt").write_text("same bytes", encoding="utf-8")
        (self.root / "different.txt").write_text("other bytes entirely", encoding="utf-8")
        (self.root / ".hidden.txt").write_text("hidden", encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "junk.txt").write_text("junk", encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)

    def names(self, items):
        return sorted(item["name"] for item in items)

    def test_skips_hidden_and_excluded_dirs_by_default(self):
        items, _ = scan(self.root)
        self.assertEqual(self.names(items), ["a-copy.txt", "a.txt", "different.txt"])

    def test_include_hidden_adds_dotfiles(self):
        items, _ = scan(self.root, include_hidden=True)
        self.assertIn(".hidden.txt", self.names(items))

    def test_record_shape_matches_drive_metadata(self):
        items, _ = scan(self.root)
        record = next(item for item in items if item["name"] == "a.txt")
        for key in ("id", "name", "mimeType", "size", "modifiedTime", "md5Checksum", "webViewLink"):
            self.assertIn(key, record)
        self.assertEqual(record["size"], str(len("same bytes")))
        self.assertTrue(record["modifiedTime"].endswith("Z"))

    def test_hash_cap_omits_checksum_without_failing(self):
        items, _ = scan(self.root, hash_max_bytes=1)
        self.assertTrue(all("md5Checksum" not in item for item in items))

    def test_output_feeds_analyzer_and_finds_the_duplicate_pair(self):
        items, _ = scan(self.root)
        report = analyze(items, older_than_days=730)
        self.assertEqual(report["file_count"], 3)
        self.assertEqual(len(report["exact_duplicate_groups"]), 1)
        group = report["exact_duplicate_groups"][0]["files"]
        self.assertEqual(self.names(group), ["a-copy.txt", "a.txt"])

    def test_symlinks_are_skipped_and_reported(self):
        link = self.root / "link.txt"
        link.symlink_to(self.root / "a.txt")
        items, skipped = scan(self.root)
        self.assertNotIn("link.txt", self.names(items))
        self.assertEqual([entry["reason"] for entry in skipped], ["symlink"])

    def test_scan_does_not_modify_the_folder(self):
        before = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        scan(self.root, include_hidden=True)
        after = sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*"))
        self.assertEqual(before, after)

    def test_missing_folder_raises(self):
        with self.assertRaises(NotADirectoryError):
            scan(self.root / "does-not-exist")


class NoHashTests(unittest.TestCase):
    """--no-hash must read no file contents, for cloud mounts that stream."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.txt").write_text("content", encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)

    def test_no_checksums_when_hashing_is_off(self):
        items, _ = scan(self.root, hash_files=False)
        self.assertEqual(len(items), 1)
        self.assertNotIn("md5Checksum", items[0])
        self.assertEqual(items[0]["size"], str(len("content")))

    def test_never_opens_a_file_when_hashing_is_off(self):
        import builtins
        opened = []
        real_open = builtins.open

        def spy(path, *args, **kwargs):
            opened.append(str(path))
            return real_open(path, *args, **kwargs)

        builtins.open = spy
        try:
            scan(self.root, hash_files=False)
        finally:
            builtins.open = real_open
        # mimetypes lazily reads the system MIME database; only the scanned
        # folder matters here.
        under_root = [path for path in opened if path.startswith(str(self.root))]
        self.assertEqual(under_root, [])

if __name__ == "__main__":
    unittest.main()
