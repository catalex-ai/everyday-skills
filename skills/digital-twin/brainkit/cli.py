"""Command line: python -m brainkit.cli <cmd> [json-args | positionals] [--flag value].

Every manage tool is a command (underscores become dashes). Output is JSON.
"""
from __future__ import annotations

import json
import sys

from . import mcp_manage as M

COMMANDS = {
    "init": M.init, "status": M.status, "add-source": M.add_source, "add-items": M.add_items,
    "define-category": M.define_category, "define-relation": M.define_relation,
    "add-alias": M.add_alias, "create-persona": M.create_persona, "set-rule": M.set_rule,
    "set-active": M.set_active, "set-privacy": M.set_privacy, "sync": M.sync, "replace-item": M.replace_item, "check-mixed": M.check_mixed,
    "next": M.next_questions, "next-questions": M.next_questions, "answer": M.answer,
    "record-correction": M.record_correction, "tidy": M.tidy, "audit": M.audit,
    "gate-scan": M.gate_scan, "list-items": M.list_items,
}


def _coerce(v: str):
    if v.lstrip("-").isdigit():
        return int(v)
    return v


def ask(q: str) -> dict:
    from . import mcp_read
    return {"question": q, "answer": mcp_read.search(q)}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(json.dumps({"commands": sorted(COMMANDS) + ["ask"]}))
        return 0
    cmd, rest = argv[0].replace("_", "-"), argv[1:]
    try:
        if cmd == "ask":
            out = ask(" ".join(rest))
        elif cmd in COMMANDS:
            fn = COMMANDS[cmd]
            args, kw = [], {}
            i = 0
            while i < len(rest):
                a = rest[i]
                if a.startswith("--") and i + 1 < len(rest):
                    kw[a[2:].replace("-", "_")] = _coerce(rest[i + 1])
                    i += 2
                    continue
                if a[:1] in "{[":
                    j = json.loads(a)
                    if isinstance(j, dict):
                        kw.update(j)
                    else:
                        args.append(j)
                else:
                    args.append(_coerce(a))
                i += 1
            if cmd in ("answer",) and "qid" in kw:
                kw["question_id"] = kw.pop("qid")
            out = fn(*args, **kw)
        else:
            out = {"error": f"unknown command: {cmd}", "commands": sorted(COMMANDS) + ["ask"]}
    except (ImportError, TypeError, json.JSONDecodeError) as e:
        out = {"error": f"{type(e).__name__}: {e}"}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 1 if isinstance(out, dict) and "error" in out else 0


if __name__ == "__main__":
    sys.exit(main())
