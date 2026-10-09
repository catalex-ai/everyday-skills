#!/usr/bin/env python3
"""Normalize whatever a Google Drive MCP tool returned into inventory records.

MCP servers disagree about shape. One returns a bare list, another wraps it in
{"files": [...]}, another returns MCP content blocks whose text is itself JSON,
and field names vary (fileId vs id, updatedAt vs modifiedTime). This maps all of
that onto the same records analyze_inventory.py and detox.py already read, and
says out loud which fields were missing so coverage gaps are never silent.

Read-only: parses JSON, writes only the --output file.
"""
import argparse
import json
import sys
from pathlib import Path

FOLDER_MIME = "application/vnd.google-apps.folder"

# First match wins, so put the canonical Drive API name first.
FIELD_ALIASES = {
    "id": ("id", "fileId", "file_id", "driveId", "resourceId"),
    "name": ("name", "title", "fileName", "file_name", "filename"),
    "mimeType": ("mimeType", "mime_type", "mimetype", "type", "contentType"),
    "size": ("size", "sizeBytes", "size_bytes", "fileSize", "file_size", "quotaBytesUsed"),
    "modifiedTime": ("modifiedTime", "modified_time", "modifiedDate", "modified",
                     "updatedAt", "updated_at", "lastModified", "lastModifiedTime"),
    "createdTime": ("createdTime", "created_time", "createdDate", "createdAt"),
    "md5Checksum": ("md5Checksum", "md5_checksum", "md5", "checksum", "sha256Checksum"),
    "webViewLink": ("webViewLink", "web_view_link", "webUrl", "link", "url", "alternateLink"),
    "parents": ("parents", "parentIds", "parent_ids", "parentId", "parent"),
}
LIST_KEYS = ("files", "items", "results", "data", "entries", "documents")
RECORD_MARKERS = ("id", "fileId", "file_id", "name", "title", "fileName")


def unwrap(payload, depth=0):
    """Yield candidate record dicts from any of the shapes servers return."""
    if depth > 8:
        return
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith(("{", "[")):
            try:
                yield from unwrap(json.loads(text), depth + 1)
            except json.JSONDecodeError:
                return
        return
    if isinstance(payload, list):
        for entry in payload:
            yield from unwrap(entry, depth + 1)
        return
    if not isinstance(payload, dict):
        return
    # An MCP content block: the payload is in .text, often as JSON.
    if "text" in payload and isinstance(payload["text"], str) and "name" not in payload:
        yield from unwrap(payload["text"], depth + 1)
        return
    for key in ("content", "structuredContent", "result", "toolResult", "response"):
        if key in payload:
            yield from unwrap(payload[key], depth + 1)
            return
    for key in LIST_KEYS:
        if isinstance(payload.get(key), list):
            yield from unwrap(payload[key], depth + 1)
            return
    if any(marker in payload for marker in RECORD_MARKERS):
        yield payload


def pick(record, field):
    for alias in FIELD_ALIASES[field]:
        if alias in record and record[alias] not in (None, ""):
            return record[alias]
    return None


def normalize(record):
    out = {}
    for field in FIELD_ALIASES:
        value = pick(record, field)
        if value is None:
            continue
        if field == "size":
            try:
                out["size"] = str(int(value))
            except (TypeError, ValueError):
                pass
        elif field == "parents":
            out["parents"] = value if isinstance(value, list) else [value]
        else:
            out[field] = value
    return out


def convert(payload, keep_folders=False):
    """Return (records, stats). Records are deduplicated by id."""
    seen, records, duplicates, folders = set(), [], 0, 0
    for raw in unwrap(payload):
        record = normalize(raw)
        if not record.get("id") and not record.get("name"):
            continue
        if not keep_folders and record.get("mimeType") == FOLDER_MIME:
            folders += 1
            continue
        key = record.get("id") or f"name:{record.get('name')}"
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        records.append(record)
    stats = {
        "records": len(records),
        "folders_skipped": folders,
        "repeats_skipped": duplicates,
        "missing_size": sum(1 for r in records if "size" not in r),
        "missing_modified": sum(1 for r in records if "modifiedTime" not in r),
        "missing_checksum": sum(1 for r in records if "md5Checksum" not in r),
        "missing_id": sum(1 for r in records if "id" not in r),
    }
    return records, stats


def describe(stats):
    lines = [f"{stats['records']} file records normalized"]
    if stats["folders_skipped"]:
        folders = stats["folders_skipped"]
        lines.append(f"  {folders} folder{'' if folders == 1 else 's'} skipped")
    if stats["repeats_skipped"]:
        repeats = stats["repeats_skipped"]
        lines.append(f"  {repeats} repeated id{'' if repeats == 1 else 's'} skipped "
                     "(overlapping pages)")
    if stats["records"]:
        for field, key in (("size", "missing_size"), ("modified date", "missing_modified"),
                           ("checksum", "missing_checksum"), ("id", "missing_id")):
            count = stats[key]
            if count:
                share = 100 * count / stats["records"]
                noun = "record has" if count == 1 else "records have"
                lines.append(f"  {count} {noun} no {field} ({share:.0f}%)")
        if stats["missing_checksum"] == stats["records"]:
            lines.append("  no checksums at all: duplicate detection will fall back to names")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path,
                        help="JSON file of MCP tool output; omit to read stdin")
    parser.add_argument("--output", type=Path, help="write inventory JSON here instead of stdout")
    parser.add_argument("--keep-folders", action="store_true")
    args = parser.parse_args()

    text = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        sys.exit(f"Input is not valid JSON: {exc}")

    records, stats = convert(payload, keep_folders=args.keep_folders)
    if not records:
        sys.exit("No file records found. Check that the MCP tool output was captured whole.")
    print(describe(stats), file=sys.stderr)
    payload_out = json.dumps(records, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(payload_out + "\n", encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(payload_out)


if __name__ == "__main__":
    main()
