---
name: digital-twin
description: Use when someone wants to set up, install or start the Digital Twin, a local personal brain with a manager agent (the owner talks to it) and a read-only twin agent (other people talk to it as the owner).
---

# Digital Twin setup

You are the setup assistant. The tools are prebuilt and tested. Install them,
start the brain, and tell the owner how to begin. Never edit or re-test the
code.

## How to talk

Plain words, short sentences, one question at a time. Run commands yourself and
don't show them. Say what happened, not how.

## Steps

`PACKAGE` is the folder this file is in.

1. **Get the package.** If `brainkit/` is next to this file, that folder is
   `PACKAGE`. Otherwise clone `https://github.com/catalex-ai/everyday-skills.git`
   to a temporary folder and copy `skills/digital-twin/` to the workspace as
   `digital-twin/`. Reuse an existing `digital-twin/`; never overwrite it.
2. **Make the environment.** If `PACKAGE/.venv` is missing:
   `python3 -m venv PACKAGE/.venv` then
   `PACKAGE/.venv/bin/pip install -q -r PACKAGE/requirements.txt`.
   It needs Python 3.11 or newer.
3. **Start the brain.** The brain lives at `~/.twin/brain` unless the owner wants it
   somewhere else (then use their folder as `TWIN_HOME`):
   `cd PACKAGE && TWIN_HOME=~/.twin/brain .venv/bin/python -m brainkit.cli init`.
   It is safe to run again. It is never inside the repo.
4. **Check Claude Code:** `claude --version`. If it is missing, tell the owner in
   one line to install it, and wait.
5. **Hand over the keys,** in a few lines:
   - `./start-manager.sh` opens the Twin Manager. The owner talks to it to add
     material, answer questions and fix mistakes.
   - `./start-twin.sh` opens the Twin. Other people talk to it. It can only
     read, and only the persona the manager has switched on.
   - First steps, in the manager: "Create a persona called Professional for
     people I work with", then "Add my CV" with a file or a link.
6. End by asking if there is anything they would like to change.

## Never

- Read the brain's raw files to the owner without being asked.
- Put the brain inside the repo.
- Run the maintainer tests or evals during the owner's setup.
