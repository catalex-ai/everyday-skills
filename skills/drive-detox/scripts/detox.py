#!/usr/bin/env python3
"""One command: find the target, inventory it, analyze it, print a plain report.

Standard library only, and read-only throughout. Nothing here creates, moves,
renames, or deletes a file. The only thing written is a report file, and only
when --save is passed.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_inventory import analyze, human_size, parse_size  # noqa: E402
from scan_local import scan  # noqa: E402

CLOUD_ROOT = Path.home() / "Library" / "CloudStorage"
GOOGLE_NATIVE = "application/vnd.google-apps."


def find_drive_mounts():
    """Google Drive for desktop mounts appear under ~/Library/CloudStorage."""
    if not CLOUD_ROOT.is_dir():
        return []
    mounts = []
    for entry in sorted(CLOUD_ROOT.iterdir()):
        if not entry.name.startswith("GoogleDrive-"):
            continue
        my_drive = entry / "My Drive"
        mounts.append(my_drive if my_drive.is_dir() else entry)
    return mounts


def resolve_target(requested):
    """Return (path, is_cloud_mount, note) or exit with advice."""
    if requested and requested != "auto":
        path = Path(requested).expanduser()
        if not path.is_dir():
            sys.exit(f"Not a folder: {path}")
        is_cloud = CLOUD_ROOT in path.resolve().parents or path.resolve() == CLOUD_ROOT
        return path, is_cloud, ""
    mounts = find_drive_mounts()
    if len(mounts) == 1:
        return mounts[0], True, f"Found your Google Drive at {mounts[0]}"
    if len(mounts) > 1:
        listing = "\n".join(f"  {m}" for m in mounts)
        sys.exit("More than one Google Drive is mounted. Pass one with --target:\n" + listing)
    sys.exit(
        "No Google Drive found on this Mac.\n"
        "Either install Google Drive for desktop and sign in, or point this at a\n"
        "local folder instead, for example:  --target ~/Downloads"
    )


def diagnose():
    """Report what is available, so setup questions are answered by facts."""
    print("Drive Detox setup check")
    print(f"  python           {sys.version.split()[0]}")
    mounts = find_drive_mounts()
    if mounts:
        for mount in mounts:
            print(f"  Drive mount      {mount}")
    else:
        print("  Drive mount      not found (install Google Drive for desktop to audit Drive)")
    token = "set" if os.environ.get("GOOGLE_DRIVE_ACCESS_TOKEN") else "not set"
    print(f"  Drive API token  {token} (only needed for the API route)")
    print("\nReady to audit:", "your Google Drive" if mounts else "any local folder")


def meaningful_duplicates(groups):
    """Drop groups a person cannot act on: empty files, and files of unknown size.

    Every zero-byte file shares one checksum, so they group together and waste
    nothing. Reporting them as duplicates is noise.
    """
    kept = []
    for group in groups:
        sizes = [parse_size(item.get("size")) for item in group["files"]]
        known = [size for size in sizes if size is not None and size > 0]
        if len(known) > 1:
            kept.append(group)
    return kept


def duplicate_waste(groups):
    """Bytes that would come back if every group kept exactly one copy."""
    total = 0
    for group in groups:
        sizes = [parse_size(item.get("size")) for item in group["files"]]
        known = [size for size in sizes if size is not None]
        if len(known) > 1:
            total += max(known) * (len(known) - 1)
    return total


def pick_keeper(files):
    """Keep the oldest copy: it is likeliest to be the original."""
    def key(item):
        return item.get("modifiedTime") or "9999"
    return sorted(files, key=key)[0]


def label(item, cutoff_iso, duplicate_ids):
    identity = item.get("id")
    if identity in duplicate_ids:
        return "DUPLICATE CANDIDATE"
    modified = item.get("modifiedTime") or ""
    if modified and modified < cutoff_iso:
        return "ARCHIVE CANDIDATE"
    if not modified:
        return "REVIEW"
    return "KEEP"


def plural(count, singular, suffix="s"):
    return f"{count:,} {singular}{'' if count == 1 else suffix}"


def display(path, item):
    """Shorten an absolute path for reading, keeping the folder context."""
    identity = item.get("id") or item.get("name") or "(unnamed)"
    try:
        return str(Path(identity).relative_to(path))
    except (ValueError, TypeError):
        return item.get("name") or identity


def apply_size_floor(items, min_size_mb):
    """Keep files at or above the floor, plus any whose size is unknown."""
    if not min_size_mb:
        return items
    floor = int(min_size_mb * 1024 * 1024)
    kept = []
    for item in items:
        size = parse_size(item.get("size"))
        if size is None or size >= floor:
            kept.append(item)
    return kept


def report(target, items, older_than_days, hashed, skipped, contents_read=True):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=older_than_days)
    cutoff_iso = cutoff.isoformat().replace("+00:00", "Z")
    data = analyze(items, older_than_days=older_than_days, now=now)

    native = sum(1 for item in items if str(item.get("mimeType", "")).startswith(GOOGLE_NATIVE))
    all_groups = data["exact_duplicate_groups"]
    groups = meaningful_duplicates(all_groups)
    empty_groups = len(all_groups) - len(groups)
    waste = duplicate_waste(groups)
    duplicate_ids = set()
    for group in groups:
        keeper = pick_keeper(group["files"])
        for item in group["files"]:
            if item.get("id") != keeper.get("id"):
                duplicate_ids.add(item.get("id"))

    lines = []
    out = lines.append
    out("=" * 62)
    out(f"DRIVE DETOX  ·  {target}")
    out("=" * 62)
    out("")
    measured = human_size(data["known_size_total_bytes"])
    out(f"{plural(data['file_count'], 'file')}  ·  {measured} measured")
    if data["unknown_size_count"]:
        extra = ""
        if native:
            which = ("1 is a Google Doc/Sheet/Slide" if native == 1
                     else f"{native:,} are Google Docs/Sheets/Slides")
            extra = f" ({which}, and those never report a size)"
        verb = "reports" if data["unknown_size_count"] == 1 else "report"
        out(f"{plural(data['unknown_size_count'], 'file')} {verb} no size{extra}")
    if not hashed:
        out("Contents were not read, so duplicates below are matched by name, not by content.")
    if skipped:
        out(f"{plural(len(skipped), 'path')} skipped (symlinks or permission errors)")
    out("")

    out("BIGGEST FILES")
    if data["largest_files"]:
        for index, entry in enumerate(data["largest_files"], 1):
            age = (entry.get("modifiedTime") or "")[:10] or "date unknown"
            out(f"  {index:2}. {entry['size_human']:>10}  {entry['name']}   (modified {age})")
    else:
        out("  no files reported a size")
    out("")

    if hashed:
        out(f"DUPLICATES  ·  {plural(len(groups), 'group')}  ·  {human_size(waste)} reclaimable")
        if empty_groups:
            noun = "group" if empty_groups == 1 else "groups"
            more = "" if len(groups) == 0 else "more "
            out(f"  ({empty_groups:,} {more}{noun} of empty or sizeless files, worth nothing)")
        for group in sorted(groups, key=lambda g: -(parse_size(g["files"][0].get("size")) or 0))[:10]:
            files = group["files"]
            size = human_size(parse_size(files[0].get("size")))
            keeper = pick_keeper(files)
            copies = f"{len(files):,} copies" if len(files) != 1 else "1 copy"
            out(f"  {copies} × {size}  {keeper.get('name')}")
            out(f"       keep  {display(target, keeper)}")
            for item in files:
                if item.get("id") != keeper.get("id"):
                    out(f"       dupe  {display(target, item)}")
        if len(groups) > 10:
            out(f"  ... and {len(groups) - 10} more groups")
    else:
        same = data["same_name_candidates"]
        out(f"SAME-NAME CANDIDATES  ·  {plural(len(same), 'group')}"
            " (weaker signal than matching contents)")
        for group in same[:10]:
            out(f"  {plural(len(group['files']), 'file')} named {group['name']}")
    out("")

    stale = data["older_than_cutoff"]
    stale_bytes = sum(entry["size_bytes"] or 0 for entry in stale)
    out(f"UNTOUCHED SINCE {cutoff.date()}  ·  {plural(len(stale), 'file')}"
        f"  ·  {human_size(stale_bytes)}")
    for entry in sorted(stale, key=lambda e: -(e["size_bytes"] or 0))[:5]:
        out(f"  {entry['size_human']:>10}  {entry['name']}   (modified {(entry['modifiedTime'] or '')[:10]})")
    if len(stale) > 5:
        out(f"  ... and {len(stale) - 5} more")
    out("")

    tally = {}
    for item in items:
        tally[label(item, cutoff_iso, duplicate_ids)] = tally.get(
            label(item, cutoff_iso, duplicate_ids), 0) + 1
    out("RECOMMENDATION")
    for name in ("DUPLICATE CANDIDATE", "ARCHIVE CANDIDATE", "REVIEW", "KEEP"):
        if tally.get(name):
            out(f"  {name:<22} {plural(tally[name], 'file'):>12}")
    out("")
    if not contents_read:
        out("Nothing was changed. Only metadata was read: no file was downloaded, "
            "moved, renamed or deleted.")
    elif hashed:
        out("Nothing was changed. Files were read only to checksum them; none was "
            "moved, renamed or deleted.")
    else:
        out("Nothing was changed. No file was read for content, moved, renamed or deleted.")
    out("Deleting stays yours to do: archiving does not free space, only emptying trash does.")
    return "\n".join(lines), data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="auto",
                        help="folder to audit, or 'auto' to find Google Drive for desktop")
    parser.add_argument("--from-inventory", type=Path,
                        help="report on an existing inventory JSON instead of scanning a folder. "
                             "Use for Drive data gathered over MCP or the Drive API")
    parser.add_argument("--label", default=None,
                        help="what to call the audited source in the report header")
    parser.add_argument("--older-than-days", type=int, default=730)
    parser.add_argument("--hash", dest="hash_mode", choices=("auto", "on", "off"), default="auto",
                        help="auto reads contents for local folders but not for a cloud mount, "
                             "where hashing would download every file")
    parser.add_argument("--hash-max-mb", type=float, default=512.0)
    parser.add_argument("--include-hidden", action="store_true")
    parser.add_argument("--min-size-mb", type=float, default=0.0,
                        help="ignore files smaller than this. Useful on folders full of tiny "
                             "app-bundle files, where thousands of duplicates are worth nothing")
    parser.add_argument("--save", help="also write the report to this path")
    parser.add_argument("--json", action="store_true", help="print the raw analysis as JSON")
    parser.add_argument("--diagnose", action="store_true", help="report what is set up, then exit")
    args = parser.parse_args()

    if args.diagnose:
        diagnose()
        return
    if args.older_than_days < 0:
        parser.error("--older-than-days must be non-negative")

    if args.from_inventory:
        try:
            items = json.loads(args.from_inventory.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            sys.exit(f"Cannot read inventory: {exc}")
        if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
            sys.exit("Inventory must be a JSON list of objects. "
                     "For raw MCP output, run it through mcp_bridge.py first.")
        items = apply_size_floor(items, args.min_size_mb)
        hashed = any("md5Checksum" in item for item in items)
        source = args.label or "Google Drive"
        text, data = report(Path(source), items, args.older_than_days, hashed, [],
                            contents_read=False)
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(text)
        if args.save:
            Path(args.save).write_text(text + "\n", encoding="utf-8")
            print(f"\nReport saved to {args.save}", file=sys.stderr)
        return

    target, is_cloud, note = resolve_target(args.target)
    if note:
        print(note, file=sys.stderr)
    hashed = args.hash_mode == "on" or (args.hash_mode == "auto" and not is_cloud)
    if is_cloud and hashed:
        print("Reading contents on a cloud mount will download every file it hashes.",
              file=sys.stderr)
    print(f"Scanning {target} ...", file=sys.stderr)

    items, skipped = scan(
        target,
        hash_max_bytes=int(args.hash_max_mb * 1024 * 1024) if args.hash_max_mb else None,
        include_hidden=args.include_hidden,
        hash_files=hashed,
    )
    items = apply_size_floor(items, args.min_size_mb)
    text, data = report(target, items, args.older_than_days, hashed, skipped)
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print(text)
    if args.save:
        Path(args.save).write_text(text + "\n", encoding="utf-8")
        print(f"\nReport saved to {args.save}", file=sys.stderr)


if __name__ == "__main__":
    main()
