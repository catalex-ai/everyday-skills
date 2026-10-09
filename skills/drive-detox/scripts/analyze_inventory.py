#!/usr/bin/env python3
"""Analyze an exported Drive metadata inventory. Standard library only; read-only."""
import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def parse_datetime(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_size(value):
    try:
        size = int(value)
        return size if size >= 0 else None
    except (ValueError, TypeError):
        return None


def human_size(size):
    if size is None:
        return "unknown"
    number = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{int(number)} B" if unit == "B" else f"{number:.1f} {unit}"
        number /= 1024


def analyze(items, older_than_days=730, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() - older_than_days * 86400
    types = Counter(item.get("mimeType") or "unknown" for item in items)
    sized = [(parse_size(item.get("size")), item) for item in items]
    known = [(size, item) for size, item in sized if size is not None]
    checksums, names = defaultdict(list), defaultdict(list)
    old, missing_size, missing_date = [], [], []
    for item in items:
        size = parse_size(item.get("size"))
        modified = parse_datetime(item.get("modifiedTime"))
        if size is None: missing_size.append(item)
        if modified is None: missing_date.append(item)
        elif modified.timestamp() < cutoff: old.append(item)
        checksum = item.get("md5Checksum")
        if isinstance(checksum, str) and checksum.strip():
            checksums[checksum.strip().lower()].append(item)
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names[name.casefold()].append(item)
    duplicates = [{"checksum": key, "files": group} for key, group in checksums.items() if len(group) > 1]
    same_names = [{"name": group[0].get("name"), "files": group} for group in names.values() if len(group) > 1]
    largest = sorted(known, key=lambda x: x[0], reverse=True)[:10]
    return {
        "file_count": len(items),
        "type_counts": dict(sorted(types.items())),
        "known_size_total_bytes": sum(size for size, _ in known),
        "unknown_size_count": len(missing_size),
        "unknown_modified_date_count": len(missing_date),
        "largest_files": [{"name": item.get("name", "(unnamed)"), "id": item.get("id"),
                           "size_bytes": size, "size_human": human_size(size),
                           "modifiedTime": item.get("modifiedTime"), "webViewLink": item.get("webViewLink")}
                          for size, item in largest],
        "older_than_cutoff": [{"name": item.get("name", "(unnamed)"), "id": item.get("id"),
                               "modifiedTime": item.get("modifiedTime"), "size_bytes": parse_size(item.get("size")),
                               "size_human": human_size(parse_size(item.get("size"))), "webViewLink": item.get("webViewLink")}
                              for item in old],
        "exact_duplicate_groups": duplicates,
        "same_name_candidates": same_names,
        "older_than_days": older_than_days,
        "note": "Metadata-only analysis. Same names are not proof of duplicates; unknown sizes are not zero."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--older-than-days", type=int, default=730)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.older_than_days < 0:
        parser.error("--older-than-days must be non-negative")
    try:
        data = json.loads(args.inventory.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read valid JSON inventory: {exc}")
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        parser.error("inventory must be a JSON list of objects")
    report = json.dumps(analyze(data, args.older_than_days), indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
