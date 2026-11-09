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
2. **Run the setup script:** `PACKAGE/setup.sh`. It is the only setup step. It
   makes the Python environment, installs the pinned packages, fetches the
   search model once and creates the brain at `~/.twin/brain`. If the owner wants
   the brain elsewhere, run it as `TWIN_HOME=<their folder> PACKAGE/setup.sh`.
   It is safe to run again. If it prints a problem (missing Python 3.11+, no
   internet), tell the owner in one line and wait.
3. **Check Claude Code:** `claude --version`. If it is missing, tell the owner in
   one line to install it, and wait.
4. **Hand over,** in a few lines:
   - In `PACKAGE/manager-agent`, run `claude`. That is the Twin Manager. The
     owner talks to it to add material, answer questions and fix mistakes.
   - In `PACKAGE/twin-agent`, run `claude`. That is the Twin. Other people talk
     to it. It answers as the owner from the persona the manager switched on.
   - Claude Code asks once to trust each folder; say yes.
   - First steps, in the manager: "Create a persona called Professional for
     people I work with", then "Add my CV" with a file or a link.
5. End by asking if there is anything they would like to change.

Do not add permission limits, wrapper scripts or launch flags. Each agent folder
already loads its own tools. Whatever hosts the agents decides what they may
use.

## Never

- Read the brain's raw files to the owner without being asked.
- Put the brain inside the repo.
- Run the maintainer tests or evals during the owner's setup.
