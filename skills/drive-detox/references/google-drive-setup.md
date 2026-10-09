# Connecting Google Drive, read-only

Two routes. Both end with a Drive audit; they differ in what they need from you.

| | Route A — claude.ai connector | Route B — token + script |
|---|---|---|
| What you get | Claude talks to Drive directly, inside the conversation | A script pulls your file list, Claude analyzes it |
| Needs | OAuth client ID + secret, Workspace Developer Preview membership | A `drive.readonly` access token |
| Read-only proof | Consent screen scopes + permission deny list | The script refuses to run on a token that can write |
| Setup time | ~15 minutes, once | ~5 minutes, token expires in an hour |

Verified on 2026-10-09 against Google's own docs, linked at the bottom.

## What does not work

Adding Google's Drive MCP server straight into Claude Code fails:

```bash
claude mcp add --transport http drive https://drivemcp.googleapis.com/mcp/v1 --scope user
```

`claude mcp list` then reports `✔ Connected`, which only means the URL answered. The first real tool call returns:

```
Incompatible auth server: does not support dynamic client registration
```

Google's server requires a pre-registered OAuth client, so the connection has to be made on claude.ai, where that client ID and secret can be stored. That is Route A.

## Route A — claude.ai custom connector

Google requires a Claude Pro, Max, Team, or Enterprise plan, a Google Cloud project, and membership in the [Google Workspace Developer Preview Program](https://developers.google.com/workspace/preview). If you already have a working Gmail connector at `gmailmcp.googleapis.com`, you have all of this.

1. In the Google Cloud console, enable both `drive.googleapis.com` (Drive API) and `drivemcp.googleapis.com` (Drive MCP API).
2. Open the OAuth consent screen → **Data Access**. Add **only**:
   ```
   https://www.googleapis.com/auth/drive.readonly
   ```
   Do **not** add `https://www.googleapis.com/auth/drive.file`. See "Lock it to read-only" below for why that one line is the whole guarantee.
3. **Google Auth Platform → Clients → Create Client**, type **Web application**. Under Authorized redirect URIs add:
   ```
   https://claude.ai/api/mcp/auth_callback
   ```
   Create, then copy the client ID and secret into your password manager.
4. On claude.ai → **Settings → Connectors → Add custom connector**. Name it `Google Drive`, URL:
   ```
   https://drivemcp.googleapis.com/mcp/v1
   ```
   Put the client ID and secret under **Advanced settings**. Add, then complete the Google sign-in.
5. Back in your terminal:
   ```bash
   claude mcp list
   ```
   A line containing `drivemcp.googleapis.com` means it is wired up. Connectors enabled on claude.ai appear in Claude Code with a `claude.ai` prefix.

Never paste the client secret into a chat message. The repo `.gitignore` already blocks `client_secret*.json`, `credentials.json`, and `token.json`.

## Route B — read-only token plus `drive_inventory.py`

This route uses the plain Drive API, which is generally available, so it needs no preview program. `scripts/drive_inventory.py` only ever issues HTTP GET requests, and it checks the token's scopes before it lists anything.

1. Enable the Drive API (`drive.googleapis.com`) on a Google Cloud project you own.
2. Mint a token carrying only Drive read access:
   ```bash
   gcloud auth application-default login \
     --scopes=https://www.googleapis.com/auth/drive.readonly
   ```
   Sign in as the Google account whose Drive you want to audit — not necessarily the account gcloud normally uses.
3. Put the token in an environment variable, so it stays out of your shell history and out of any file:
   ```bash
   export GOOGLE_DRIVE_ACCESS_TOKEN="$(gcloud auth application-default print-access-token)"
   ```
4. Confirm what that token can actually do, before using it:
   ```bash
   python3 skills/drive-detox/scripts/drive_inventory.py --check-scopes-only
   ```
   It prints the scopes Google reports for the token. If anything beyond `drive.readonly`, `drive.metadata.readonly`, and identity scopes shows up, the script exits without listing a single file.
5. Pull the inventory and analyze it:
   ```bash
   python3 skills/drive-detox/scripts/drive_inventory.py \
     --quota-project YOUR_PROJECT_ID --output /tmp/drive-inventory.json

   python3 skills/drive-detox/scripts/analyze_inventory.py \
     /tmp/drive-inventory.json --older-than-days 730
   ```
   Write the inventory to `/tmp`, never into the repo — it lists your real file names.

Notes:
- The token expires in about an hour. Re-run step 3 to refresh it. There is nothing to clean up afterwards.
- Revoke access any time at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
- `--quota-project` sends the `X-Goog-User-Project` header. If the Drive API returns 403, the script prints Google's own message, which names the project and links to the enable page. Reported quirk: the quota project is sometimes ignored for the Drive API, and the workaround is to log in with a **desktop-type** OAuth client of your own via `gcloud auth application-default login --client-id-file=...`.
- Start with `--folder-id` or `--max-pages 1` on a large Drive to see the shape of the output before pulling everything.

## Lock it to read-only

Four layers. The first two are real boundaries; the rest are checks.

### Layer 1 — OAuth scope. This is the actual boundary.

Grant `drive.readonly` and nothing else. Google's Drive MCP server exposes eight tools:

| Tool | Reads | Writes |
|---|---|---|
| `search_files` | yes | |
| `list_recent_files` | yes | |
| `get_file_metadata` | yes | |
| `get_file_permissions` | yes | |
| `read_file_content` | yes | |
| `download_file_content` | yes | |
| `create_file` | | yes |
| `copy_file` | | yes |

There is no delete tool at all. The two that write need `drive.file`; withhold that scope and they fail at Google's API, not at Claude's discretion. Google's docs do not promise this mapping tool by tool, which is why Layer 2 exists too.

### Layer 2 — deny the write tools in Claude Code

In the project you run audits from, `.claude/settings.json`:

```json
{
  "permissions": {
    "deny": [
      "mcp__google_drive__create_file",
      "mcp__google_drive__copy_file",
      "Bash(rm:*)",
      "Bash(mv:*)",
      "Bash(trash:*)"
    ]
  }
}
```

A denied tool cannot be called at all — Claude cannot even ask you to approve it. Replace `google_drive` with the server name as `claude mcp list` prints it, lowercased with spaces and dashes turned into underscores. A copy to paste is at [`examples/claude-settings-readonly.json`](../examples/claude-settings-readonly.json); this repo ships it as its own `.claude/settings.json`.

If the name is wrong the rule silently does nothing, which is why you also run the Layer 4 check.

### Layer 3 — the script refuses write-capable credentials

Route B's scope guard is not advisory. `drive_inventory.py` calls Google's tokeninfo endpoint first, compares the scopes against an allow-list, and exits before any file listing if the token carries more than read access. `tests/test_drive_inventory.py` covers that: a token with `drive` or `drive.file` added is rejected, and every outgoing request is asserted to be a GET with no body.

### Layer 4 — verify, don't assume

The checks are in [`TESTING.md`](../TESTING.md), section "Prove it is read-only". The one that matters most: with the deny list in place, ask Claude to create a file in your Drive. A pass is a refusal citing a permission denial. A pass is *not* Claude asking you to approve it.

## What this cannot do

- It cannot delete anything or empty your trash, by design. Deleting stays something you do yourself in Drive, after reading the plan.
- Drive totals will not match your Google storage bar, which also counts Gmail and Photos.
- Google Docs, Sheets, and Slides usually report no size, so they land under "unknown size" rather than zero.

## Sources

- [Configure the Drive MCP server](https://developers.google.com/workspace/drive/api/guides/configure-mcp-server)
- [Configure the Google Workspace MCP servers](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Drive API `files.list`](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list)
- [OAuth 2.0 scopes for Google APIs](https://developers.google.com/identity/protocols/oauth2/scopes#drive)
- [Claude Code settings reference](https://docs.claude.com/en/docs/claude-code/settings)
