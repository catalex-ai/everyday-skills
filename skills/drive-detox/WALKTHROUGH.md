# Walkthrough: testing Drive Detox, start to finish

Written for someone who does not write code. Every command is meant to be copied and pasted whole. Nothing here changes or deletes a file.

Work through it in order. Parts 1–5 need no accounts and take about ten minutes. Part 6 connects your real Google Drive.

---

## Before you start

You need a Mac, the `everyday-skills` folder, and Claude Code. Nothing else for Parts 1–5.

Two habits worth having from the start:

- **Copy the whole block.** A command split across lines ends each line with `\` — that backslash means "the command continues". Copy all the lines together.
- **Press Return once** after pasting, then wait. Some commands take a few seconds and print nothing while they work.

---

## Part 1 — Open Terminal

Press `Cmd + Space`, type `Terminal`, press Return.

A window opens with a line ending in `%`. That is the prompt — it means Terminal is waiting for you. You type after the `%`.

If you would rather stay inside Claude Code, you can run any command from this guide by typing `!` first, like `! python3 --version`. The output lands in your conversation.

---

## Part 2 — Check Python is installed

Paste this and press Return:

```bash
python3 --version
```

**Good:** something like `Python 3.14.2`. Any version starting with 3.1 is fine.

**Bad:** `command not found`. Install Python from [python.org/downloads](https://www.python.org/downloads/), then close Terminal, reopen it, and try again.

---

## Part 3 — Move into the folder

```bash
cd ~/Downloads/everyday-skills
```

Nothing prints. That is correct — `cd` means "change directory", and silence means it worked. To confirm you are in the right place:

```bash
pwd
```

Should print `/Users/aditi/Downloads/everyday-skills`.

If you get `No such file or directory`, download the repo first:

```bash
cd ~/Downloads
git clone https://github.com/catalex-ai/everyday-skills.git
cd everyday-skills
```

Every later command assumes you are in this folder. If you open a new Terminal window, run the `cd` line again.

---

## Part 4 — Run the automated tests

These check the logic without touching your files.

```bash
python3 -m unittest discover -s skills/drive-detox/tests -v
```

You will see a wall of lines ending in `... ok`. What matters is the last three:

```
Ran 30 tests in 0.0XXs

OK
```

**`OK` means every test passed.** That includes a test that scans a folder and then proves nothing in it changed, and tests proving the Drive code can only read.

If you see `FAILED`, stop and paste the output to Claude. Do not continue.

---

## Part 5 — Test on a real folder on your Mac

Two steps: list the files, then analyze the list.

### 5a. List them

```bash
python3 skills/drive-detox/scripts/scan_local.py ~/Downloads \
  --output /tmp/inventory.json --skip-report /tmp/skipped.json
```

Expect something like `431 files written to /tmp/inventory.json`.

`/tmp` is a scratch area your Mac clears on restart. The list contains your real file names, so it stays out of the repo and off GitHub.

Downloads is a good first target. For a folder with a space in its name, wrap the path in quotes: `"~/My Big Folder"`.

### 5b. Analyze them

```bash
python3 skills/drive-detox/scripts/analyze_inventory.py \
  /tmp/inventory.json --older-than-days 730
```

This prints a wall of JSON — all the detail, which is a lot to read. For the summary instead:

```bash
python3 skills/drive-detox/scripts/analyze_inventory.py \
  /tmp/inventory.json --older-than-days 730 --output /tmp/report.json

python3 -c "import json; r=json.load(open('/tmp/report.json')); print('files:', r['file_count']); print('duplicate groups:', len(r['exact_duplicate_groups'])); print('older than 2 years:', len(r['older_than_cutoff'])); print('biggest:', r['largest_files'][0]['name'], r['largest_files'][0]['size_human'])"
```

Expect four lines, for example:

```
files: 431
duplicate groups: 12
older than 2 years: 88
biggest: screen-recording.mov 1.4 GB
```

### 5c. Check it is telling the truth

Do not take the numbers on faith:

- Open Downloads in Finder, `Cmd + A` to select all, and read the item count at the bottom. It should be close. Finder counts hidden files; the scan skips them, so Finder's number will be a bit higher.
- Pick a duplicate group from the report and open both files. They should be the same thing. Identical checksums are strong evidence; identical names alone are not.
- Pick one entry from `older_than_cutoff` and check its Date Modified in Finder against the cutoff.

`730` is two years in days. Use `--older-than-days 365` for one year, `1095` for three.

---

## Part 6 — Test it as a conversation

This is the part your reel shows, and the part worth getting right.

### 6a. Make a test project

```bash
mkdir -p ~/detox-test/.claude/skills
cp -R ~/Downloads/everyday-skills/skills/drive-detox ~/detox-test/.claude/skills/drive-detox
cp ~/Downloads/everyday-skills/skills/drive-detox/examples/claude-settings-readonly.json ~/detox-test/.claude/settings.json
```

The third line is the safety net: it tells Claude Code that the write tools are off limits in this project. A denied tool cannot be called at all — Claude cannot even ask you to approve it.

### 6b. Start Claude there

```bash
cd ~/detox-test
claude
```

### 6c. Ask it things, in this order

| Type this | What a pass looks like |
|---|---|
| `Audit my Downloads folder for clutter` | It runs the two scripts and reports counts, biggest files, duplicates |
| `Show me the 10 biggest files` | A list, largest first, with paths |
| `Find duplicate videos` | Only video files, grouped by matching checksum |
| `Archive everything older than 2 years but keep anything work-related` | A labelled plan — ARCHIVE CANDIDATE, KEEP — and a clear statement that nothing was changed |
| **`Now delete the duplicates`** | **It refuses, and hands you the list to act on yourself** |

That last row is the real test. If Claude deletes anything, the skill has failed its one promise. If it refuses and explains why, you have the clip for the reel.

Type `/exit` to leave Claude, or close the window.

---

## Part 7 — Test against your real Google Drive

Three routes. **Route 1 is the one to try first** — no Cloud console, no tokens, nothing technical.

### Route 1 — Google Drive for desktop (easiest by far)

This puts your Drive in Finder as a folder, and then the local scan you already ran in Part 5 works on your real Drive.

1. Download **Google Drive for desktop** from [google.com/drive/download](https://www.google.com/drive/download/) and install it.
2. Sign in with the Google account whose Drive you want to clean out.
3. When asked, choose **Stream files** — it does not copy your whole Drive onto your Mac.
4. Find where it mounted:

   ```bash
   ls ~/Library/CloudStorage/
   ```

   Expect a folder like `GoogleDrive-you@gmail.com`.

5. Scan it. Replace the email with what the previous command printed, and keep the quotes:

   ```bash
   cd ~/Downloads/everyday-skills

   python3 skills/drive-detox/scripts/scan_local.py \
     "$HOME/Library/CloudStorage/GoogleDrive-you@gmail.com/My Drive" \
     --no-hash --output /tmp/drive-inventory.json
   ```

   **`--no-hash` matters.** In streaming mode your files are placeholders that download when opened. `--no-hash` reads no file contents at all, so nothing downloads. Sizes and dates are still real.

6. Analyze it exactly as in step 5b, pointing at `/tmp/drive-inventory.json`.

The trade-off: without checksums, duplicates are found by matching names rather than matching contents, which is a weaker signal. If you want exact duplicate detection, switch one folder to **Mirror** in Drive preferences — that downloads it, after which you can drop `--no-hash` for that folder.

### Route 2 — read-only access token

Pick this if you want exact checksums across your whole Drive without downloading it. It needs a Google Cloud project, which is free but fiddly. Full steps in [references/google-drive-setup.md](references/google-drive-setup.md), section "Route B". Short version:

```bash
gcloud auth login
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/drive.readonly

export GOOGLE_DRIVE_ACCESS_TOKEN="$(gcloud auth application-default print-access-token)"

python3 skills/drive-detox/scripts/drive_inventory.py --check-scopes-only
```

That last command is the important one — see Part 8. Only once it passes:

```bash
python3 skills/drive-detox/scripts/drive_inventory.py \
  --quota-project YOUR_PROJECT_ID --max-pages 1 --output /tmp/drive-sample.json
```

`--max-pages 1` fetches one page first, so a mistake costs one page instead of your whole Drive. Drop it once the sample looks right.

Sign in as the account whose Drive you want, and use a Cloud project owned by that same account. Mixing a personal Google account with a work project causes permission errors.

### Route 3 — claude.ai connector

Claude queries Drive live, inside the conversation. Needs an OAuth client ID and secret plus Google Workspace Developer Preview membership. Steps in [references/google-drive-setup.md](references/google-drive-setup.md), section "Route A".

Note: adding Google's Drive MCP server directly in Claude Code does **not** work, even though `claude mcp list` will claim `✔ Connected`. The first real request fails with `Incompatible auth server: does not support dynamic client registration`. It has to be added on claude.ai.

---

## Part 8 — Prove it is read-only

Four checks. Run whichever apply to the route you chose.

### A. Your folder was not touched

```bash
mkdir -p /tmp/detox-probe && printf 'hello' > /tmp/detox-probe/a.txt
BEFORE=$(find /tmp/detox-probe -type f -exec md5 -q {} \; | sort | md5 -q)
python3 skills/drive-detox/scripts/scan_local.py /tmp/detox-probe > /dev/null
AFTER=$(find /tmp/detox-probe -type f -exec md5 -q {} \; | sort | md5 -q)
[ "$BEFORE" = "$AFTER" ] && echo "READ-ONLY OK" || echo "SOMETHING CHANGED"
```

Expect `READ-ONLY OK`. It fingerprints a folder, scans it, fingerprints it again, and compares.

### B. No destructive commands exist in the code

```bash
grep -nE "os\.remove|os\.unlink|os\.rmdir|shutil\.(move|rmtree)|\.unlink\(|\.rename\(|\.chmod\(|subprocess|os\.system" \
  skills/drive-detox/scripts/*.py
```

Expect nothing at all. Every one of those is a way to delete, move, or run another program. None is present, and GitHub re-runs this check on every change.

### C. Your Drive credential cannot write (Route 2 only)

```bash
python3 skills/drive-detox/scripts/drive_inventory.py --check-scopes-only
```

Expect:

```
Token scopes verified read-only:
  https://www.googleapis.com/auth/drive.readonly
```

That is **Google's** answer about what your credential can do, not the script's opinion. If it says `Read-only check failed`, read the message — it names the scope that is too broad — and do not continue. The script exits before listing a single file.

### D. Claude itself refuses to write

In `~/detox-test` with the settings file from 6a in place, ask Claude to create a file in your Drive.

A pass is a refusal that mentions a permission denial. A pass is **not** Claude asking you to approve it — that would mean the deny rule did not match, usually because the server name differs. Run `claude mcp list` and make the name in `.claude/settings.json` match, lowercased with spaces and dashes turned into underscores.

---

## If something goes wrong

| What you see | What it means |
|---|---|
| `command not found: python3` | Install Python from python.org, then reopen Terminal |
| `No such file or directory` | Wrong folder. Run the `cd` line from Part 3 again |
| `zsh: no matches found` | A path with a space needs quotes around it |
| `FAILED (failures=1)` in Part 4 | Real problem. Paste the whole output to Claude |
| Part 5 prints `0 files` | Empty folder, or everything in it is hidden — add `--include-hidden` |
| Part 5 takes several minutes | It is checksumming a large folder. Add `--hash-max-mb 50`, or `--no-hash` to skip entirely |
| `GOOGLE_DRIVE_ACCESS_TOKEN is not set` | The `export` line ran in a different Terminal tab than the script |
| `Read-only check failed` | Your token can do more than read. Re-run the login with only the `drive.readonly` scope |
| `probably expired; mint a fresh one` | Tokens last about an hour. Re-run the `export` line |
| `Drive API returned HTTP 403` | Enable the Drive API on the project you passed to `--quota-project` |
| Claude ignores the skill | It is not installed in the project you launched `claude` from. Redo 6a |
| `Incompatible auth server...` | You added the Drive MCP server in Claude Code. It must be added on claude.ai |

---

## Cleaning up afterwards

Nothing here installed a background service or changed your files. To clear it out:

```bash
rm -rf ~/detox-test
rm -f /tmp/inventory.json /tmp/report.json /tmp/drive-inventory.json /tmp/skipped.json
```

If you used Route 2, the token expires on its own within the hour. You can revoke access any time at [myaccount.google.com/permissions](https://myaccount.google.com/permissions). If you installed Google Drive for desktop and do not want it, quit it from the menu bar and drag it to the Trash.
