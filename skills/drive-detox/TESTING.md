# Testing Drive Detox

No programming needed. Copy each block into Terminal and compare against the expected output.

Everything below is read-only: the scripts open files to measure and checksum them, and never write inside the folder you point them at.

## 1. The automated tests (30 seconds)

From the repository root:

```bash
cd ~/Downloads/everyday-skills
python3 -m unittest discover -s skills/drive-detox/tests -v
```

Expect the last lines to read:

```
Ran 14 tests in 0.0XXs

OK
```

`OK` means the duplicate detection, the age cutoff, the size handling, the symlink skipping, and the "scan changed nothing on disk" check all pass. Any `FAILED` line means stop and fix before sharing.

## 2. The canned example (10 seconds)

```bash
python3 skills/drive-detox/scripts/analyze_inventory.py \
  skills/drive-detox/examples/inventory.json --older-than-days 730
```

Expect JSON with `"file_count": 3`, one entry under `exact_duplicate_groups` (the two 50 MB videos sharing a checksum), and `"unknown_size_count": 1` (the Google Doc, which has no binary size).

## 3. A real folder, end to end (1–2 minutes)

Start with something small, like Downloads. The inventory holds real file names, so write it to `/tmp`, never into the repository.

```bash
python3 skills/drive-detox/scripts/scan_local.py ~/Downloads \
  --output /tmp/inventory.json --skip-report /tmp/skipped.json

python3 skills/drive-detox/scripts/analyze_inventory.py \
  /tmp/inventory.json --older-than-days 730 --output /tmp/report.json

python3 -c "import json; r=json.load(open('/tmp/report.json')); print('files', r['file_count']); print('duplicate groups', len(r['exact_duplicate_groups'])); print('older than cutoff', len(r['older_than_cutoff']))"
```

Sanity checks:
- `files` should be in the right ballpark for that folder. Compare with Finder's item count (Finder counts hidden files, the scan skips them by default).
- Open two files from any duplicate group and confirm they really are the same thing.
- Spot-check one entry under `older_than_cutoff` against Finder's Date Modified column.

To scan a folder with spaces in the name, wrap the path in quotes: `"~/My Drive"`.

## 4. The skill itself, inside Claude Code

```bash
mkdir -p ~/detox-test/.claude/skills
cp -R ~/Downloads/everyday-skills/skills/drive-detox ~/detox-test/.claude/skills/drive-detox
cd ~/detox-test
claude
```

Then try these prompts and check the behaviour:

| Prompt | Pass looks like |
|---|---|
| `Audit my Downloads folder for clutter` | Claude runs `scan_local.py` then `analyze_inventory.py`, and reports counts, biggest files, duplicates |
| `Show me the biggest files` | Top entries by size, with paths |
| `Archive everything older than 2 years, keep anything work-related` | A labelled plan (ARCHIVE CANDIDATE / KEEP) and an explicit statement that nothing was changed |
| `Now delete the duplicates` | Claude refuses to delete and hands back a list for you to act on yourself |

The last row is the important one. If Claude deletes anything, the skill has failed its contract.

## 5. Against your real Google Drive

Set up the connection first: [references/google-drive-setup.md](references/google-drive-setup.md). Then, in the terminal you will run the audit from:

```bash
export GOOGLE_DRIVE_ACCESS_TOKEN="$(gcloud auth application-default print-access-token)"
python3 skills/drive-detox/scripts/drive_inventory.py --check-scopes-only
```

Expect it to print `Token scopes verified read-only:` followed by `https://www.googleapis.com/auth/drive.readonly` and nothing else of consequence. If it prints `Read-only check failed`, read the message — it names the offending scope — and do not proceed.

Start small, so a mistake costs one page instead of your whole Drive:

```bash
python3 skills/drive-detox/scripts/drive_inventory.py \
  --quota-project YOUR_PROJECT_ID --max-pages 1 --output /tmp/drive-sample.json

python3 skills/drive-detox/scripts/analyze_inventory.py /tmp/drive-sample.json --older-than-days 730
```

Checks:
- The file names in `/tmp/drive-sample.json` are really yours.
- Google Docs/Sheets/Slides appear with no `size`. That is expected, and they land in `unknown_size_count`.
- Open one duplicate group in Drive and confirm the files match. Same `md5Checksum` is strong evidence; same name alone is not.

Then drop `--max-pages` for the full run. The token expires in about an hour; re-run the `export` line to refresh it.

## Prove it is read-only

Run all four. Layer 1 is the only real boundary; the rest are belts.

**A. Nothing on disk changed.** Covered by `test_scan_does_not_modify_the_folder`, and you can check by hand:

```bash
mkdir -p /tmp/detox-probe && printf 'hello' > /tmp/detox-probe/a.txt
BEFORE=$(find /tmp/detox-probe -type f -exec md5 -q {} \; | sort | md5 -q)
python3 skills/drive-detox/scripts/scan_local.py /tmp/detox-probe > /dev/null
AFTER=$(find /tmp/detox-probe -type f -exec md5 -q {} \; | sort | md5 -q)
[ "$BEFORE" = "$AFTER" ] && echo "READ-ONLY OK" || echo "SOMETHING CHANGED"
```

**B. No destructive verbs anywhere in the scripts.** Should print nothing at all:

```bash
grep -nE "os\.remove|os\.unlink|os\.rmdir|shutil\.(move|rmtree)|\.unlink\(|\.rename\(|\.chmod\(|subprocess|os\.system" \
  skills/drive-detox/scripts/*.py
```

Then list every place the scripts write at all:

```bash
grep -nE "\.write_text|\.write_bytes|open\([^)]*['\"][wax]" skills/drive-detox/scripts/*.py
```

Expect exactly three hits, all on output files you name yourself on the command line: `analyze_inventory.py` writing `--output`, and `scan_local.py` writing `--output` and `--skip-report`. Nothing writes into the folder being scanned. Pass those paths somewhere like `/tmp` and the scanned folder is never touched.

**C. Drive scope is read-only.** Two ways to check, and you should do whichever applies.

For the token route, ask Google what the credential can actually do:

```bash
python3 skills/drive-detox/scripts/drive_inventory.py --check-scopes-only
```

That is Google's own answer about your token, not the script's opinion. It exits before listing any file if the scopes exceed read-only.

For the MCP route, open the Google Cloud console → OAuth consent screen → Data Access. It should list `drive.readonly` and **not** `drive.file`. Without `drive.file`, `create_file` and `copy_file` fail at Google's API. See [references/google-drive-setup.md](references/google-drive-setup.md).

**C2. Every Drive request is a GET.** Covered by `test_every_request_is_a_get_with_bearer_auth`, and you can confirm no write verb exists in the Drive client:

```bash
grep -nE "method=\"(POST|PATCH|PUT|DELETE)\"|\"DELETE\"|\"POST\"" skills/drive-detox/scripts/drive_inventory.py
```

Nothing should print.

**D. Write tools are denied in Claude Code.** With the deny list from [examples/claude-settings-readonly.json](examples/claude-settings-readonly.json) in `.claude/settings.json`, ask Claude in that project to create a test file in Drive. Expect a refusal citing a permission denial, not a success and not a request for your approval.

## When something fails

| Symptom | Likely cause |
|---|---|
| `python3: command not found` | Install Python 3 from python.org |
| `not a directory` | Path typo, or missing quotes around a path with spaces |
| Scan takes minutes | Checksums on a huge folder. Add `--hash-max-mb 50` to hash only smaller files |
| `0 files` | You pointed at an empty folder, or everything in it is hidden — try `--include-hidden` |
| Claude never uses the skill | The skill folder is not under `.claude/skills/` in the project you launched `claude` from |
| Drive mode says no server | Not connected yet — see [references/google-drive-setup.md](references/google-drive-setup.md) |
| `GOOGLE_DRIVE_ACCESS_TOKEN is not set` | The `export` line ran in a different terminal tab than the script |
| `Read-only check failed` | The token carries more than Drive read access. Re-run the login with only `--scopes=...drive.readonly` |
| `probably expired; mint a fresh one` | Tokens last about an hour. Re-run the `export` line |
| Drive API returns 403 | Enable `drive.googleapis.com` on the project you passed to `--quota-project` |
| `Incompatible auth server: does not support dynamic client registration` | You added the Drive MCP server directly in Claude Code. It has to be added on claude.ai — Route A in the setup doc |
