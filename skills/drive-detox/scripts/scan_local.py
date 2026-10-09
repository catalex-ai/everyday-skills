#!/usr/bin/env python3
"""Build a read-only inventory of a local folder in Drive-metadata shape.

Standard library only. Opens files for reading to compute checksums and never
creates, moves, renames, or deletes anything inside the scanned folder.
"""
import argparse
import hashlib
import json
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_EXCLUDES = (
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".Trash",
    "Library",
    ".cache",
)
HASH_CHUNK = 1024 * 1024


def iso_utc(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def md5_of(path, chunk=HASH_CHUNK):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def should_skip_dir(name, excludes, include_hidden):
    if name in excludes:
        return True
    return name.startswith(".") and not include_hidden


def scan(root, hash_max_bytes=None, excludes=DEFAULT_EXCLUDES, include_hidden=False, follow_symlinks=False):
    """Walk root and yield one metadata dict per regular file, plus skip notes."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"not a directory: {root}")
    excludes = set(excludes)
    items, skipped = [], []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d, excludes, include_hidden)]
        for filename in filenames:
            if filename.startswith(".") and not include_hidden:
                continue
            full = Path(dirpath) / filename
            if full.is_symlink() and not follow_symlinks:
                skipped.append({"path": str(full), "reason": "symlink"})
                continue
            try:
                stat = full.stat()
            except OSError as exc:
                skipped.append({"path": str(full), "reason": f"stat failed: {exc.strerror}"})
                continue
            if not full.is_file():
                continue
            mime = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
            record = {
                "id": str(full),
                "name": full.name,
                "mimeType": mime,
                "size": str(stat.st_size),
                "modifiedTime": iso_utc(stat.st_mtime),
                "parentPath": str(full.parent),
                "webViewLink": full.as_uri(),
            }
            if hash_max_bytes is None or stat.st_size <= hash_max_bytes:
                try:
                    record["md5Checksum"] = md5_of(full)
                except OSError as exc:
                    skipped.append({"path": str(full), "reason": f"unreadable: {exc.strerror}"})
            items.append(record)
    return items, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="folder to scan, e.g. ~/Downloads")
    parser.add_argument("--output", type=Path, help="write inventory JSON here instead of stdout")
    parser.add_argument("--hash-max-mb", type=float, default=512.0,
                        help="skip checksums above this size; 0 means hash everything")
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--follow-symlinks", action="store_true")
    parser.add_argument("--skip-report", type=Path, help="write the list of skipped paths here")
    args = parser.parse_args()
    if args.hash_max_mb < 0:
        parser.error("--hash-max-mb must be non-negative")
    hash_max_bytes = None if args.hash_max_mb == 0 else int(args.hash_max_mb * 1024 * 1024)
    items, skipped = scan(
        args.folder,
        hash_max_bytes=hash_max_bytes,
        include_hidden=args.include_hidden,
        follow_symlinks=args.follow_symlinks,
    )
    payload = json.dumps(items, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"{len(items)} files written to {args.output}")
    else:
        print(payload)
    if skipped:
        message = f"{len(skipped)} paths skipped (symlinks, permissions, or stat errors)"
        if args.skip_report:
            args.skip_report.write_text(json.dumps(skipped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            message += f"; details in {args.skip_report}"
        print(message)


if __name__ == "__main__":
    main()
