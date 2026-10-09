# Connecting Google Drive, read-only

Verified against Google's own docs on 2026-10-09. Check the links before trusting any step — Google changes this area often.

## Step 0 — do you already have it?

In Claude Code, run:

```bash
claude mcp list
```

A connected Drive server shows up as a line containing `drivemcp.googleapis.com` or a name like `Google Drive`. If it is there, skip to "Lock it to read-only".

## Step 1 — the easy path first

Open **claude.ai → Settings → Connectors** and look for a ready-made **Google Drive** connector. If it is listed, enable it, sign in with Google, then run `claude mcp list` again — connectors enabled there appear in Claude Code too.

Only if there is no Google Drive entry do you need Step 2.

## Step 2 — custom connector to Google's official Drive MCP server

Requirements Google states: a Claude Pro, Max, Team, or Enterprise plan, a Google Cloud project, and membership in the Google Workspace Developer Preview Program.

Server URL:

```
https://drivemcp.googleapis.com/mcp/v1
```

1. In the Google Cloud console, enable both `drive.googleapis.com` (Drive API) and `drivemcp.googleapis.com` (Drive MCP API).
2. Configure the OAuth consent screen. Under **Data Access**, add **only**:
   ```
   https://www.googleapis.com/auth/drive.readonly
   ```
   Do **not** add `https://www.googleapis.com/auth/drive.file`. That is the scope the write tools need, and leaving it out is the strongest guarantee you have.
3. **Google Auth Platform → Clients → Create Client**, type **Web application**. Under Authorized redirect URIs add:
   ```
   https://claude.ai/api/mcp/auth_callback
   ```
   Create it, then copy the client ID and client secret.
4. In claude.ai (or Claude Desktop) → **Settings → Connectors → Add custom connector**. Name it `Google Drive`, paste the server URL, and put the client ID and secret under **Advanced settings**. Click Add and complete the Google sign-in.
5. Keep the client secret in your password manager. Never paste it into a chat message and never commit it. The repo `.gitignore` already blocks `client_secret*.json`, `credentials.json`, and `token.json`.

## Lock it to read-only

Three layers. Use all three; the first is the only real boundary.

### Layer 1 — OAuth scope (the actual boundary)

Grant `drive.readonly` and nothing else, as in Step 2. Google's Drive MCP server exposes eight tools:

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

Without `drive.file`, the two write tools fail at Google's API, not at Claude's discretion. Google's docs do not promise this mapping tool-by-tool, so also do Layer 2.

### Layer 2 — deny the write tools in Claude Code

Create or edit `.claude/settings.json` in whichever project you run the audit from, and paste:

```json
{
  "permissions": {
    "deny": [
      "mcp__google_drive__create_file",
      "mcp__google_drive__copy_file"
    ]
  }
}
```

Replace `google_drive` with the server name exactly as `claude mcp list` prints it, lowercased with spaces and dashes turned into underscores. A denied tool cannot be called at all, not even with your approval.

A copy ready to paste lives at [`examples/claude-settings-readonly.json`](../examples/claude-settings-readonly.json).

### Layer 3 — verify, don't assume

Run the checks in [`TESTING.md`](../TESTING.md), section "Prove it is read-only".

## What this cannot do

- It cannot delete or empty trash, by design. Deleting stays a manual step you do in Drive after reading the plan.
- Drive totals will not match your Google storage bar, which also counts Gmail and Photos.
- Google Docs, Sheets, and Slides usually report no size, so they appear under "unknown size".

## Sources

- [Configure the Drive MCP server](https://developers.google.com/workspace/drive/api/guides/configure-mcp-server)
- [Configure the Google Workspace MCP servers](https://developers.google.com/workspace/guides/configure-mcp-servers)
- [Claude Code settings reference](https://docs.claude.com/en/docs/claude-code/settings)
