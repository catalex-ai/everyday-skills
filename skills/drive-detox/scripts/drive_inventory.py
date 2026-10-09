#!/usr/bin/env python3
"""Build an inventory of a real Google Drive using a read-only access token.

Standard library only. Issues HTTP GET requests to the Drive API and nothing
else: there is no code path here that can create, copy, move, rename, trash, or
delete a file.

Before listing anything, the token's scopes are checked against an allow-list
and the run aborts if the token could write. The token is read from the
GOOGLE_DRIVE_ACCESS_TOKEN environment variable and is never printed or stored.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
FILES_URL = "https://www.googleapis.com/drive/v3/files"

READ_SCOPES = frozenset({
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
})
# Identity scopes carry no Drive access, so they are harmless alongside the above.
BENIGN_SCOPES = frozenset({
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
})
FIELDS = (
    "nextPageToken,files(id,name,mimeType,size,modifiedTime,createdTime,"
    "md5Checksum,parents,webViewLink,owners(emailAddress),shared,trashed)"
)


class ScopeError(RuntimeError):
    """The token is missing read access, or carries more than read access."""


def get_json(url, params=None, token=None, quota_project=None, opener=None):
    """GET a JSON document. The only HTTP verb this module ever uses."""
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, method="GET")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if quota_project:
        request.add_header("X-Goog-User-Project", quota_project)
    fetch = opener or urllib.request.urlopen
    with fetch(request) as response:
        return json.loads(response.read().decode("utf-8"))


def check_scopes(token, opener=None):
    """Return the token's scopes, or raise ScopeError if it is not read-only."""
    try:
        info = get_json(TOKENINFO_URL, {"access_token": token}, opener=opener)
    except urllib.error.HTTPError as exc:
        raise ScopeError(
            "Google rejected the token while checking its scopes "
            f"(HTTP {exc.code}). It is probably expired; mint a fresh one."
        ) from exc
    scopes = set((info.get("scope") or "").split())
    if not scopes:
        raise ScopeError("Google reported no scopes for this token.")
    if not scopes & READ_SCOPES:
        raise ScopeError(
            "Token carries no Drive read scope. Expected one of:\n  "
            + "\n  ".join(sorted(READ_SCOPES))
            + "\nIt has:\n  "
            + "\n  ".join(sorted(scopes))
        )
    extra = scopes - READ_SCOPES - BENIGN_SCOPES
    if extra:
        raise ScopeError(
            "Refusing to run: this token carries scopes beyond read-only Drive "
            "access, so it could be used to change your files.\nUnexpected "
            "scopes:\n  " + "\n  ".join(sorted(extra))
            + "\nMint a token with only drive.readonly and try again."
        )
    return sorted(scopes)


def list_files(token, folder_id=None, include_trashed=False, max_pages=None,
               page_size=1000, quota_project=None, opener=None):
    """Page through Drive metadata. Returns (records, pages_read, truncated)."""
    clauses = []
    if not include_trashed:
        clauses.append("trashed = false")
    if folder_id:
        clauses.append(f"'{folder_id}' in parents")
    params = {
        "pageSize": page_size,
        "fields": FIELDS,
        "spaces": "drive",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    if clauses:
        params["q"] = " and ".join(clauses)
    records, pages, token_page = [], 0, None
    while True:
        if token_page:
            params["pageToken"] = token_page
        payload = get_json(FILES_URL, dict(params), token=token,
                           quota_project=quota_project, opener=opener)
        records.extend(payload.get("files", []))
        pages += 1
        token_page = payload.get("nextPageToken")
        if not token_page:
            return records, pages, False
        if max_pages is not None and pages >= max_pages:
            return records, pages, True


def to_inventory(records):
    """Drop folders, keep the fields analyze_inventory.py reads."""
    return [item for item in records
            if item.get("mimeType") != "application/vnd.google-apps.folder"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="write inventory JSON here instead of stdout")
    parser.add_argument("--folder-id", help="limit to one folder's direct children")
    parser.add_argument("--include-trashed", action="store_true")
    parser.add_argument("--max-pages", type=int, help="stop early; coverage is then partial")
    parser.add_argument("--quota-project", help="Google Cloud project to bill the API call to")
    parser.add_argument("--check-scopes-only", action="store_true",
                        help="print the token's scopes and exit without listing files")
    args = parser.parse_args()

    token = os.environ.get("GOOGLE_DRIVE_ACCESS_TOKEN", "").strip()
    if not token:
        sys.exit("GOOGLE_DRIVE_ACCESS_TOKEN is not set. See references/google-drive-setup.md")

    try:
        scopes = check_scopes(token)
    except ScopeError as exc:
        sys.exit(f"Read-only check failed.\n{exc}")
    print("Token scopes verified read-only:", file=sys.stderr)
    for scope in scopes:
        print(f"  {scope}", file=sys.stderr)
    if args.check_scopes_only:
        return

    try:
        records, pages, truncated = list_files(
            token,
            folder_id=args.folder_id,
            include_trashed=args.include_trashed,
            max_pages=args.max_pages,
            quota_project=args.quota_project,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        hint = ""
        if exc.code == 403:
            hint = ("\nIf this says the Drive API is not enabled, enable it on the "
                    "project you passed to --quota-project.")
        sys.exit(f"Drive API returned HTTP {exc.code}.\n{detail}{hint}")

    inventory = to_inventory(records)
    payload = json.dumps(inventory, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        print(f"{len(inventory)} files written to {args.output}", file=sys.stderr)
    else:
        print(payload)
    print(f"{pages} page(s) read, {len(records) - len(inventory)} folders skipped",
          file=sys.stderr)
    if truncated:
        print("WARNING: stopped at --max-pages, so coverage is partial.", file=sys.stderr)


if __name__ == "__main__":
    main()
