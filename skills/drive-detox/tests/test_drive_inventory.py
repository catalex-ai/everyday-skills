import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from analyze_inventory import analyze
from drive_inventory import ScopeError, check_scopes, list_files, to_inventory

DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
DRIVE_FULL = "https://www.googleapis.com/auth/drive"
DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"


class FakeOpener:
    """Stands in for urllib.request.urlopen and records every request made."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        body = self.responses.pop(0)
        if isinstance(body, Exception):
            raise body
        payload = json.dumps(body).encode("utf-8")

        class Response(io.BytesIO):
            def __enter__(inner):
                return inner

            def __exit__(inner, *exc):
                return False

        return Response(payload)


def page(files, next_token=None):
    body = {"files": files}
    if next_token:
        body["nextPageToken"] = next_token
    return body


class ScopeGuardTests(unittest.TestCase):
    def test_accepts_readonly_plus_identity_scopes(self):
        opener = FakeOpener([{"scope": f"{DRIVE_READONLY} openid email"}])
        self.assertEqual(
            check_scopes("tok", opener=opener),
            sorted([DRIVE_READONLY, "openid", "email"]),
        )

    def test_rejects_full_drive_scope(self):
        opener = FakeOpener([{"scope": f"{DRIVE_READONLY} {DRIVE_FULL}"}])
        with self.assertRaises(ScopeError) as caught:
            check_scopes("tok", opener=opener)
        self.assertIn(DRIVE_FULL, str(caught.exception))

    def test_rejects_drive_file_write_scope(self):
        opener = FakeOpener([{"scope": f"{DRIVE_READONLY} {DRIVE_FILE}"}])
        with self.assertRaises(ScopeError):
            check_scopes("tok", opener=opener)

    def test_rejects_token_without_any_drive_read_scope(self):
        opener = FakeOpener([{"scope": "openid email"}])
        with self.assertRaises(ScopeError) as caught:
            check_scopes("tok", opener=opener)
        self.assertIn("no Drive read scope", str(caught.exception))

    def test_rejects_empty_scope_list(self):
        with self.assertRaises(ScopeError):
            check_scopes("tok", opener=FakeOpener([{}]))

    def test_expired_token_is_reported_as_scope_failure(self):
        error = urllib.error.HTTPError("url", 400, "Bad Request", {}, io.BytesIO(b"{}"))
        with self.assertRaises(ScopeError) as caught:
            check_scopes("tok", opener=FakeOpener([error]))
        self.assertIn("expired", str(caught.exception))


class ListFilesTests(unittest.TestCase):
    def test_every_request_is_a_get_with_bearer_auth(self):
        opener = FakeOpener([page([{"id": "1", "name": "a.pdf"}])])
        list_files("tok", opener=opener)
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer tok")
        self.assertIsNone(request.data)

    def test_follows_pagination_to_the_end(self):
        opener = FakeOpener([
            page([{"id": "1", "name": "a"}], next_token="p2"),
            page([{"id": "2", "name": "b"}], next_token="p3"),
            page([{"id": "3", "name": "c"}]),
        ])
        records, pages, truncated = list_files("tok", opener=opener)
        self.assertEqual([r["id"] for r in records], ["1", "2", "3"])
        self.assertEqual(pages, 3)
        self.assertFalse(truncated)

    def test_max_pages_stops_early_and_flags_partial_coverage(self):
        opener = FakeOpener([
            page([{"id": "1"}], next_token="p2"),
            page([{"id": "2"}], next_token="p3"),
        ])
        records, pages, truncated = list_files("tok", max_pages=2, opener=opener)
        self.assertEqual(pages, 2)
        self.assertTrue(truncated)
        self.assertEqual(len(records), 2)

    def test_excludes_trash_by_default_and_scopes_to_folder(self):
        opener = FakeOpener([page([])])
        list_files("tok", folder_id="FOLDER", opener=opener)
        query = opener.requests[0].full_url
        self.assertIn("trashed+%3D+false", query)
        self.assertIn("FOLDER", query)

    def test_include_trashed_drops_the_trash_filter(self):
        opener = FakeOpener([page([])])
        list_files("tok", include_trashed=True, opener=opener)
        self.assertNotIn("&q=", opener.requests[0].full_url)

    def test_quota_project_is_sent_as_a_header(self):
        opener = FakeOpener([page([])])
        list_files("tok", quota_project="proj-1", opener=opener)
        # urllib normalises header names to Capitalized-lowercase form.
        self.assertEqual(opener.requests[0].get_header("X-goog-user-project"), "proj-1")


class InventoryShapeTests(unittest.TestCase):
    def test_folders_are_dropped(self):
        records = [
            {"id": "f", "name": "Folder", "mimeType": "application/vnd.google-apps.folder"},
            {"id": "a", "name": "a.pdf", "mimeType": "application/pdf"},
        ]
        self.assertEqual([item["id"] for item in to_inventory(records)], ["a"])

    def test_output_feeds_the_analyzer(self):
        records = [
            {"id": "a", "name": "deck.pdf", "mimeType": "application/pdf", "size": "1024",
             "modifiedTime": "2020-01-01T00:00:00Z", "md5Checksum": "same"},
            {"id": "b", "name": "deck (1).pdf", "mimeType": "application/pdf", "size": "1024",
             "modifiedTime": "2020-01-02T00:00:00Z", "md5Checksum": "same"},
            {"id": "c", "name": "Notes", "mimeType": "application/vnd.google-apps.document",
             "modifiedTime": "2026-09-01T00:00:00Z"},
        ]
        report = analyze(to_inventory(records), older_than_days=730)
        self.assertEqual(report["file_count"], 3)
        self.assertEqual(len(report["exact_duplicate_groups"]), 1)
        self.assertEqual(report["unknown_size_count"], 1)


if __name__ == "__main__":
    unittest.main()
