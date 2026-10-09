import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import detox  # noqa: E402


def item(identity, name, size=None, modified=None, mime="video/mp4"):
    record = {"id": identity, "name": name, "mimeType": mime}
    if size is not None:
        record["size"] = str(size)
    if modified:
        record["modifiedTime"] = modified
    return record


class DuplicateWasteTests(unittest.TestCase):
    def test_counts_every_copy_but_one(self):
        groups = [{"checksum": "a", "files": [
            item("1", "clip.mov", 100), item("2", "clip 2.mov", 100), item("3", "clip 3.mov", 100)]}]
        self.assertEqual(detox.duplicate_waste(groups), 200)

    def test_sums_across_groups(self):
        groups = [
            {"checksum": "a", "files": [item("1", "a", 100), item("2", "b", 100)]},
            {"checksum": "b", "files": [item("3", "c", 50), item("4", "d", 50)]},
        ]
        self.assertEqual(detox.duplicate_waste(groups), 150)

    def test_ignores_groups_with_unknown_sizes(self):
        groups = [{"checksum": "a", "files": [item("1", "a"), item("2", "b")]}]
        self.assertEqual(detox.duplicate_waste(groups), 0)

    def test_single_file_group_wastes_nothing(self):
        groups = [{"checksum": "a", "files": [item("1", "a", 100)]}]
        self.assertEqual(detox.duplicate_waste(groups), 0)


class KeeperTests(unittest.TestCase):
    def test_keeps_the_oldest_copy(self):
        files = [
            item("new", "clip 2.mov", 10, "2026-01-01T00:00:00Z"),
            item("old", "clip.mov", 10, "2020-01-01T00:00:00Z"),
        ]
        self.assertEqual(detox.pick_keeper(files)["id"], "old")

    def test_files_without_a_date_are_not_preferred(self):
        files = [item("dated", "a", 10, "2020-01-01T00:00:00Z"), item("undated", "b", 10)]
        self.assertEqual(detox.pick_keeper(files)["id"], "dated")


class LabelTests(unittest.TestCase):
    cutoff = "2024-10-09T00:00:00Z"

    def test_duplicate_wins_over_age(self):
        record = item("x", "a", 10, "2019-01-01T00:00:00Z")
        self.assertEqual(detox.label(record, self.cutoff, {"x"}), "DUPLICATE CANDIDATE")

    def test_old_file_is_an_archive_candidate(self):
        record = item("x", "a", 10, "2019-01-01T00:00:00Z")
        self.assertEqual(detox.label(record, self.cutoff, set()), "ARCHIVE CANDIDATE")

    def test_recent_file_is_kept(self):
        record = item("x", "a", 10, "2026-09-01T00:00:00Z")
        self.assertEqual(detox.label(record, self.cutoff, set()), "KEEP")

    def test_missing_date_is_flagged_for_review(self):
        self.assertEqual(detox.label(item("x", "a", 10), self.cutoff, set()), "REVIEW")


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.original_cloud_root = detox.CLOUD_ROOT

        def restore():
            detox.CLOUD_ROOT = self.original_cloud_root

        self.addCleanup(restore)

    def test_explicit_folder_is_used_as_given(self):
        path, is_cloud, _ = detox.resolve_target(str(self.root))
        self.assertEqual(path, self.root)
        self.assertFalse(is_cloud)

    def test_missing_folder_exits(self):
        with self.assertRaises(SystemExit):
            detox.resolve_target(str(self.root / "nope"))

    def test_auto_finds_a_single_drive_mount(self):
        detox.CLOUD_ROOT = self.root
        mount = self.root / "GoogleDrive-someone@example.com" / "My Drive"
        mount.mkdir(parents=True)
        path, is_cloud, note = detox.resolve_target("auto")
        self.assertEqual(path, mount)
        self.assertTrue(is_cloud)
        self.assertIn("My Drive", note)

    def test_auto_exits_with_advice_when_no_mount_exists(self):
        detox.CLOUD_ROOT = self.root
        with self.assertRaises(SystemExit) as caught:
            detox.resolve_target("auto")
        self.assertIn("Google Drive for desktop", str(caught.exception))

    def test_auto_refuses_to_guess_between_two_mounts(self):
        detox.CLOUD_ROOT = self.root
        for email in ("a@example.com", "b@example.com"):
            (self.root / f"GoogleDrive-{email}" / "My Drive").mkdir(parents=True)
        with self.assertRaises(SystemExit) as caught:
            detox.resolve_target("auto")
        self.assertIn("--target", str(caught.exception))

    def test_a_path_inside_the_cloud_root_is_treated_as_a_mount(self):
        detox.CLOUD_ROOT = self.root.resolve()
        mount = self.root / "GoogleDrive-x@example.com" / "My Drive"
        mount.mkdir(parents=True)
        _, is_cloud, _ = detox.resolve_target(str(mount))
        self.assertTrue(is_cloud)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            item("/d/clip.mov", "clip.mov", 1000, "2020-01-01T00:00:00Z"),
            item("/d/clip 2.mov", "clip 2.mov", 1000, "2020-01-02T00:00:00Z"),
            item("/d/notes", "notes", None, "2026-09-01T00:00:00Z",
                 mime="application/vnd.google-apps.document"),
        ]
        for record in self.items[:2]:
            record["md5Checksum"] = "samechecksum"

    def render(self, hashed=True):
        text, data = detox.report(Path("/d"), self.items, 730, hashed, [])
        return text, data

    def test_headline_counts_and_reclaimable_space(self):
        text, _ = self.render()
        self.assertIn("3 files", text)
        self.assertIn("1 group", text)
        self.assertIn("1000 B reclaimable", text)

    def test_names_the_copy_to_keep_and_the_ones_to_drop(self):
        text, _ = self.render()
        self.assertIn("keep  clip.mov", text)
        self.assertIn("dupe  clip 2.mov", text)

    def test_explains_google_native_files_with_no_size(self):
        text, _ = self.render()
        self.assertIn("report no size", text)
        self.assertIn("Google Docs/Sheets/Slides", text)

    def test_states_plainly_that_nothing_changed(self):
        text, _ = self.render()
        self.assertIn("Nothing was changed.", text)

    def test_without_hashing_it_says_duplicates_are_name_matched(self):
        text, _ = self.render(hashed=False)
        self.assertIn("matched by name", text)
        self.assertIn("SAME-NAME CANDIDATES", text)
        self.assertNotIn("reclaimable", text)


if __name__ == "__main__":
    unittest.main()
