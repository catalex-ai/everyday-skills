# Digital Twin

A personal brain that answers as you. Everything runs on your computer.

You get two agents that share one folder:

- **Twin Manager.** You talk to it. Give it a CV, notes, a profile export or a
  link. It breaks them into small facts, files each one under a type, asks you a
  few questions, and takes corrections.
- **Twin.** Other people talk to it. It answers as you, in the first person, from
  the facts you have allowed for that audience. It can only read.

It is a hobby project for one person, not a product. No server, no account.

## How it works

```
 you ──> Twin Manager ──> brain folder ──> Twin ──> other people
         (reads, splits,   raw facts       (reads only the
          asks, corrects)  + personas      active persona)
```

1. You add material. The manager splits it into facts, one sentence each.
2. Each fact gets a **type** (work history, education, family...).
3. You decide, once per type, which audience may know it. "May Professional
   know about family?" You are never asked about a single fact.
4. A **persona** is one audience (professional, personal). Each persona's folder
   holds only the facts allowed for it.
5. You tell the manager which persona the twin uses.

Questions never block. Material is always kept, and what is waiting on an answer
simply waits.

## Privacy settings

Names are information. People, companies and places are stored. Contact details
and secrets follow a setting you can change at any time.

| mode | what is stored | the persona sees |
|---|---|---|
| `allow` | the value as written | the value |
| `hold` | a token such as `⟦email:3fa9c1⟧`, the value kept in the manager zone only | nothing |
| `drop` | a token such as `⟦password⟧`, the value kept nowhere | nothing |

Defaults: email, phone and address are `hold`. Password, bank account, card and
government ID are `drop`. Everything else is `allow`. `drop` cannot be undone.
See [PRIVACY.md](PRIVACY.md).

## Start

Give your coding assistant this prompt:

> Read https://raw.githubusercontent.com/catalex-ai/everyday-skills/main/skills/digital-twin/SKILL.md
> and set up the Digital Twin here.

Or by hand:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
TWIN_HOME=~/.twin/brain .venv/bin/python -m brainkit.cli init
./start-manager.sh      # you
./start-twin.sh         # other people
```

## Things to say to the manager

- "Create a persona called Professional for people I work with."
- "Add my CV." (attach a file or paste a link)
- "The twin should use Professional."
- "You said I live in Pune. It should be Mumbai."
- "Make the twin sound more casual."
- "Never keep my phone number." / "Allow my email in Personal."
- "Tidy up." / "Show me what the twin knows."

"Show me what the twin knows" writes `audit.html` in the brain folder. Open it in
a browser. It lists each persona, its facts by topic, open questions and
conflicts. It never shows held values.

## Files

- [SKILL.md](SKILL.md): setup
- [PRIVACY.md](PRIVACY.md): what is stored where
- [TESTING.md](TESTING.md): tests and evals
- `manager-agent/`, `twin-agent/`: the two agents
- `brainkit/`: the code behind them
- `templates/`: starting soul, voice, rules and contract
