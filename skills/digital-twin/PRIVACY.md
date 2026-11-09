# Privacy

Everything stays on your computer. Nothing is sent anywhere except to the Claude
Code you already use to talk to the agents.

## Modes

Each kind of private detail has a mode. You set it through the manager.

| type | default |
|---|---|
| email, phone, address | `hold` |
| password, bank account, card, government ID | `drop` |
| everything else (names, dates, work numbers) | `allow` |

- `allow`: stored as written.
- `hold`: replaced in the text by a token. The real value is kept in the manager
  zone only. The twin never sees it. You can switch back to `allow` later.
- `drop`: replaced by a token and the value is kept nowhere. This cannot be
  undone. The manager warns you first.

Changing a mode re-checks everything already stored and rebuilds every persona.
Nothing needs to be added again.

Names of people, companies and places are information, not private details.
Whether a persona may know about someone is a rule per type of information.

## What is stored where

Default folder: `~/.twin/brain` (set `TWIN_HOME` to move it). It is never in the
repo.

- `raw/brain.sqlite`: every source and fact, with private values replaced by
  tokens, and the held values. Manager only.
- `privacy.yaml`: your modes.
- `personas/<name>/`: only the facts allowed for that audience. Generated. The
  twin reads only the active one.
- `questions.json`, `ledger.json`, `corrections.jsonl`, `log.jsonl`: manager only.
- `audit.html`: a report you open in a browser.

A fact that is denied or not yet approved for a persona is never written into
that persona's folder.

## Wipe it

```bash
rm -rf ~/.twin/brain     # or your TWIN_HOME
```

That deletes everything: facts, held values, personas and logs.
