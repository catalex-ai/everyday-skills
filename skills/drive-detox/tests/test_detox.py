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
        self.assertIn("reports no size", text)
        self.assertIn("Google Doc/Sheet/Slide", text)
        self.assertIn("never report a size", text)

    def test_states_plainly_that_nothing_changed(self):
        text, _ = self.render()
        self.assertIn("Nothing was changed.", text)

    def test_metadata_only_wording_when_contents_were_not_read(self):
        text, _ = detox.report(Path("/d"), self.items, 730, True, [], contents_read=False)
        self.assertIn("Only metadata was read", text)
        self.assertNotIn("read only to checksum", text)

    def test_plural_google_native_wording(self):
        items = self.items + [
            item("/d/sheet", "sheet", None, "2026-09-01T00:00:00Z",
                 mime="application/vnd.google-apps.spreadsheet")]
        text, _ = detox.report(Path("/d"), items, 730, True, [])
        self.assertIn("2 are Google Docs/Sheets/Slides", text)

    def test_without_hashing_it_says_duplicates_are_name_matched(self):
        text, _ = self.render(hashed=False)
        self.assertIn("matched by name", text)
        self.assertIn("SAME-NAME CANDIDATES", text)
        self.assertNotIn("reclaimable", text)


class NoiseFilterTests(unittest.TestCase):
    """Thousands of tiny or empty duplicates are noise, not findings."""

    def test_zero_byte_groups_are_dropped(self):
        groups = [{"checksum": "e", "files": [item("1", "a", 0), item("2", "b", 0)]}]
        self.assertEqual(detox.meaningful_duplicates(groups), [])

    def test_unknown_size_groups_are_dropped(self):
        groups = [{"checksum": "u", "files": [item("1", "a"), item("2", "b")]}]
        self.assertEqual(detox.meaningful_duplicates(groups), [])

    def test_real_groups_survive(self):
        groups = [{"checksum": "r", "files": [item("1", "a", 100), item("2", "b", 100)]}]
        self.assertEqual(len(detox.meaningful_duplicates(groups)), 1)

    def test_report_says_empty_groups_are_worth_nothing(self):
        items = [item("1", "a.txt", 0, "2026-01-01T00:00:00Z"),
                 item("2", "b.txt", 0, "2026-01-02T00:00:00Z")]
        for record in items:
            record["md5Checksum"] = "d41d8cd98f00b204e9800998ecf8427e"
        text, _ = detox.report(Path("/d"), items, 730, True, [])
        self.assertIn("0 groups", text)
        self.assertIn("worth nothing", text)

    def test_size_floor_keeps_big_files_and_unknown_sizes(self):
        items = [item("1", "big", 2 * 1024 * 1024), item("2", "small", 1024), item("3", "doc")]
        kept = detox.apply_size_floor(items, 1)
        self.assertEqual([record["id"] for record in kept], ["1", "3"])

    def test_size_floor_of_zero_changes_nothing(self):
        items = [item("1", "small", 1)]
        self.assertIs(detox.apply_size_floor(items, 0), items)


class ReclaimableTableTests(unittest.TestCase):
    cutoff = "2024-10-09T00:00:00Z"

    def buckets(self, items, duplicate_ids=frozenset()):
        return detox.categorize(items, set(duplicate_ids), self.cutoff)

    def test_each_file_lands_in_exactly_one_bucket(self):
        items = [
            item("dup", "clip 2.mov", 100, "2019-01-01T00:00:00Z"),
            item("installer", "Docker.dmg", 200, "2019-01-01T00:00:00Z"),
            item("stale", "old.pdf", 50, "2019-01-01T00:00:00Z", mime="application/pdf"),
            item("fresh", "new.mov", 10, "2026-09-01T00:00:00Z"),
        ]
        buckets = self.buckets(items, {"dup"})
        self.assertEqual([i["id"] for i in buckets["duplicate"]], ["dup"])
        self.assertEqual([i["id"] for i in buckets["redownloadable"]], ["installer"])
        self.assertEqual([i["id"] for i in buckets["stale"]], ["stale"])
        self.assertEqual([i["id"] for i in buckets["keep"]], ["fresh"])
        self.assertEqual(sum(len(v) for v in buckets.values()), len(items))

    def test_duplicate_beats_installer_so_nothing_is_double_counted(self):
        items = [item("x", "Claude (1).dmg", 100, "2019-01-01T00:00:00Z")]
        buckets = self.buckets(items, {"x"})
        self.assertEqual(len(buckets["duplicate"]), 1)
        self.assertEqual(buckets["redownloadable"], [])

    def test_recent_installer_is_still_reclaimable(self):
        items = [item("x", "Docker.dmg", 100, "2026-09-01T00:00:00Z")]
        self.assertEqual(len(self.buckets(items)["redownloadable"]), 1)

    def test_table_is_ordered_by_space_and_skips_empty_categories(self):
        items = [
            item("i", "a.dmg", 500, "2026-01-01T00:00:00Z"),
            item("d", "b.mov", 100, "2026-01-01T00:00:00Z"),
        ]
        table = detox.reclaimable_table(self.buckets(items, {"d"}), "2024-10-09")
        self.assertEqual([row[0] for row in table],
                         ["Installers you can download again", "Duplicate copies"])
        self.assertEqual([row[2] for row in table], [500, 100])

    def test_report_prints_the_table_with_a_total(self):
        items = [
            item("/d/a.dmg", "a.dmg", 1000, "2026-01-01T00:00:00Z"),
            item("/d/b.mov", "b.mov", 500, "2020-01-01T00:00:00Z"),
            item("/d/b 2.mov", "b 2.mov", 500, "2020-01-02T00:00:00Z"),
        ]
        for record in items[1:]:
            record["md5Checksum"] = "same"
        text, _ = detox.report(Path("/d"), items, 730, True, [])
        self.assertIn("WHAT YOU CAN RECLAIM", text)
        self.assertIn("Installers you can download again", text)
        self.assertIn("Duplicate copies", text)
        self.assertIn("Total if you act on all of it", text)
        self.assertIn("Keeping", text)

    def test_report_says_so_when_there_is_nothing_to_reclaim(self):
        items = [item("/d/a.mov", "a.mov", 10, "2026-09-01T00:00:00Z")]
        text, _ = detox.report(Path("/d"), items, 730, True, [])
        self.assertIn("Nothing stands out", text)


if __name__ == "__main__":
    unittest.main()
