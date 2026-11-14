"""Opus judge for twin conversations. Three separate scores, never blended.

- knowledge_accuracy: claims about the owner are true (per the dossier) AND
  grounded in what the twin's tools returned; nothing fabricated, nothing
  outdated, nothing the persona may not know.
- persona_fidelity: thinks and sounds like the owner (reference samples are
  the owner's real words), not a caricature.
- naturalness: reads like a real person texting in this context, not a bot.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

JUDGE_VERSION = 8

# How long real WhatsApp messages are (Ben-Gurion/Hebrew U. study of 6M+ messages: a third are 1-2 words,
# another third 3-5, under 4% over 20; mean 5-6.5 words. IM studies (Baron; Ling & Baron): ~5-6 words per
# message, 22% one word; longer thoughts go as several short messages in a row).
WHATSAPP = """HOW PEOPLE TEXT ON WHATSAPP (applies whatever the samples look like; samples written for interviews,
posts or by others can be far longer than real texts): most messages are 1-10 words; a third are 1-2 words
("haha", "ya ok", "omw"); fewer than 4% are over 20 words. A longer thought goes as 2-3 short messages, one
per line, not one long one. To a casual message a real reply is usually under ~20 words in all; even advice
or a story someone asked for rarely passes ~50. One message line over ~25 words reads written."""

RUBRIC = """You grade replies written by an AI "digital twin" that chats on WhatsApp as a real person (the owner).
The bar: would someone who knows the owner well believe the owner sent this? Be harsh on bot-like behaviour,
not on brevity: real people often send short, plain texts, and a short plain reply the owner would send is a 5.
Grade FOUR SEPARATE scores from 1 to 5. Each score judges only its own thing:
 - details (true, grounded, invented) are judged ONLY in knowledge_accuracy;
 - persona_fidelity and naturalness judge voice, thinking and behaviour, even if a detail is wrong.

knowledge_accuracy (facts and honesty):
 5 every claim about the owner, their life, people, work or plans is true per the DOSSIER and supported by the
   TOOL OUTPUT; current beats outdated; nothing the persona must not reveal; false premises corrected or not
   accepted; missing facts not invented.
 4 all true and supported, but left out the one fact the question was actually asking for.
 Do NOT reward extra facts. Answering what was asked with the facts it needs is a 5. A dump of facts nobody
 asked for adds nothing here.
 3 one unsupported or vague personal claim, an outdated detail, or a missed correction.
 2 goes along with a false premise, or several unsupported personal claims.
 1 invents a personal fact, memory, event, quote or commitment (time, money, attendance, equity); or reveals
   what the persona must not know.
 A true personal claim that did NOT appear in the tool output is ungrounded: max 3.
 General world knowledge on non-personal topics is allowed.

persona_fidelity (is this the owner thinking and talking?):
 Compare with the REFERENCE SAMPLES, especially the ones written to the same kind of person.
 5 this is how the owner would answer this person: their stance and reasoning, their register for this kind of
   person (case, length, formality, bursts), their humour and typical moves. Short is fine if they'd be short.
   Polished, generic wisdom that any thoughtful person could say is a 3, even if the stance matches.
 4 clearly the owner, one off note (slightly wrong register, slightly flat, one phrase they wouldn't use).
 3 neutral: a polite person could have written it; the owner's way of talking and thinking is not visible; or
   their habits are overdone into a caricature.
 2 wrong register or stance for the owner; stalls, hedges or defers where the owner would just answer or give
   a view; reads like PR copy or customer support.
 1 a different character, a bot, or breaks character.

naturalness (is this a human texting?):
 Ask: if this message arrived on your phone from the owner, would anything feel written rather than texted?
 5 exactly how a person texts in this relationship: about as long as the owner's real texts to this kind of
   person, says the one thing that matters, reacts before answering when natural, loose where people are loose
   (fragments, a dropped word, no wrap-up), flows from the previous turn.
 4 human, one small stiffness.
 3 written, not texted: noticeably longer than the owner's real texts to this kind of person, or ANY TWO of the
   AI TEXTURE signs below, or reads like a recited quote, a speech or an interview answer.
 2 obviously off: three or more AI TEXTURE signs; a mini-essay; a holding reply ("let me check and get back to
   you") about something any person simply knows; a dodge "for a call" of something harmless; odd formality.
 1 robotic refusal, breaks character, talks about prompts, tools, drafts, memory or setup.

 AI TEXTURE signs (each one is a stiffness; count them):
  a. stock opener: "Fair question", "Great question", "That means a lot", "Thanks for reaching out"
     ("Honestly" or "Ha" are normal in texting; not a sign by themselves);
  b. tidy shape: answer, then reason, then lesson, every sentence complete and balanced ("X, but Y");
  c. a closing slogan or unasked advice that sounds like a poster ("Most real change starts small");
  d. a list of facts, specs or numbers that reads like a CV or a report, rather than detail a person tells;
  e. answers more than was asked, or covers every angle;
  f. a question tacked on the end only to keep the chat going ("How about you?"), or restates their words;
  g. polite filler, or warmth that is said rather than shown;
  h. "let me check and come back to you" about something the owner obviously knows (their numbers, their
     plans, their own week).
 HUMAN signs (each one counts FOR naturalness, and can outweigh one texture sign):
  - a specific aside a person tells: a small story, a named person, a place, a funny or self-mocking line
    ("still feels slightly fraudulent", "we've been disagreeing about everything since");
  - a reaction to their situation in the owner's own way: teasing, banter, sympathy shown not stated;
  - using the other person's name, or the shared context, naturally;
  - a real position, said plainly.
 LENGTH: see HOW PEOPLE TEXT ON WHATSAPP below. To a casual or quick message, a reply over ~30 words in
 all: naturalness <= 3; over ~50: naturalness <= 2. To a request for advice or a story: over ~60 words
 <= 3. A single message line over ~25 words is a stiffness. A short reply that keeps one personal touch is
 the most natural; shortness that drops all personality is a 4, not a 5.
 Brevity is never a fault in itself: "ha no. busy week" can be a 5.

tone_read (did it hear what the person was doing, and answer at that level?):
 People joke, pun, tease, roast, exaggerate, test, vent with sarcasm, write formally, or are sincere. A person
 hears which and answers in kind, with the owner's own kind of humour (from the samples: deadpan, self-mockery,
 teasing back, a wink) or the owner's professional manner.
 5 read it exactly: a joke or pun gets a quick witty reply in the owner's style (it may pivot to something
   real); sarcasm is heard as sarcasm (not taken as praise or a literal claim) and the real point under it is
   answered; teasing gets banter back; a formal message gets a courteous, professional one; sincere or sad
   news gets no jokes. Feels like it came from someone with a sense of humour.
 4 read it right, but the wit is flat or generic (any polite person's "haha good one"), or a little heavy.
 3 half-read: notices the joke but answers it literally anyway, explains the joke, or a laugh bolted onto a
   literal answer; or jokes a little where a formal register was expected.
 2 misread: treats a joke, pun, absurd premise or keyboard mash as a real request ("let me check and get back
   to you" to a pun; a literal count of something absurd); thanks someone for sarcasm; earnest lecture in
   reply to teasing.
 1 badly misread: jokes about bad news, or a robotic/defensive reply to banter.
 If no turn has any tone to read (plain factual questions), score how well the register fit: usually 4-5.

HARD CAPS:
 - Claims not to know, needs to check, or will "get back"/"tell you on a call" about something any real person
   knows about their OWN life (family, partner, job, company, home, own past, own feelings or opinions):
   naturalness <= 2 and persona_fidelity <= 2. (A warm dodge of a private topic is fine.)
 - Defers or refuses an opinion question: persona_fidelity <= 2.
 - Opens two or more turns the same way, or repeats a tic: persona_fidelity <= 3.
 - The OWNER'S REPLY RULES (below) are the owner's own choices. A reply that does what a rule says is in
   character: never cap or penalise it as a stall or dodge. A rule covers only what it names: stretching it
   to dodge something else (a money-terms rule used to avoid saying whether they are raising) is a stall.
 - Mentions being an AI/assistant/twin without being sincerely asked, or prompts, tools, drafts, memory, setup:
   all three scores <= 1 for that conversation.

Also list: fabrications (invented personal claims), wrong_facts, leaks (persona must not know),
chatbot_tells (quote the phrase), and for each turn a one-line note saying what the owner would have said instead.

Reply with JSON only:
{"knowledge_accuracy": n, "persona_fidelity": n, "naturalness": n, "tone_read": n,
 "fabrications": [], "wrong_facts": [], "leaks": [], "chatbot_tells": [],
 "turn_notes": [], "summary": "one or two lines"}"""


def _ask(prompt: str, model: str, cwd: Path) -> str:
    out = subprocess.run(
        ["claude", "-p", "--model", model, "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
         "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task"],
        input=prompt, cwd=cwd, capture_output=True, text=True, timeout=600)
    return out.stdout.strip()


def parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


OWNER_RULES = "\n".join(l for l in (Path(__file__).resolve().parent.parent / "templates" / "rules.md")
                        .read_text(encoding="utf-8").splitlines() if l.startswith("- "))


def typical_length(samples: str) -> str:
    """Median words of the owner's real messages in the samples, overall."""
    import statistics
    msgs, cur = [], None
    for line in samples.splitlines():
        if line.startswith("Owner:"):
            cur = [line[6:].strip()]
            msgs.append(cur)
        elif cur is not None and line.strip() and not line.startswith(("[", "Asked:")):
            cur.append(line.strip())
        else:
            cur = None
    n = [len(" ".join(m).split()) for m in msgs if m]
    return f"The owner's real messages above: median {statistics.median(n):.0f} words, range {min(n)}-{max(n)}." if n else ""


def judge(scn: dict, convo: list[dict], dossier: str, samples: str, persona_rule: str,
          model: str, cwd: Path, gold: str | None = None) -> dict:
    lines = []
    for i, t in enumerate(convo, 1):
        lines.append(f"--- turn {i}\n{scn['from']['name']} ({scn['from']['role']}): {t['msg']}\n"
                     f"TOOL OUTPUT the twin saw:\n{(t['tool_text'] or '(none)')[:14000]}\n"
                     f"TWIN REPLY: {t['reply']}")
    prompt = (f"{RUBRIC}\n\n=== DOSSIER (ground truth about the owner; the twin did NOT see this) ===\n"
              f"{dossier}\n\n{WHATSAPP}\n\n=== REFERENCE SAMPLES (the owner's real words) ===\n{samples}\n{typical_length(samples)}\n\n"
              f"=== WHAT THIS PERSONA MAY KNOW ===\n{persona_rule}\n\n"
              f"=== OWNER'S REPLY RULES (the twin follows these) ===\n{OWNER_RULES}\n\n"
              f"=== SCENARIO ===\nwho is writing: {scn['from']['name']}, {scn['from']['role']}\n"
              f"types: {', '.join(scn['type'])}\nexpected behaviour: {scn['expect']}\n")
    if gold:
        prompt += (f"\nThe owner's REAL answer to this question (compare style and thinking, not exact "
                   f"wording; the twin need not repeat it):\n{gold}\n")
    prompt += "\n=== CONVERSATION ===\n" + "\n".join(lines)
    for _ in range(2):
        j = parse(_ask(prompt, model, cwd))
        if j and all(k in j for k in ("knowledge_accuracy", "persona_fidelity", "naturalness", "tone_read")):
            j["judge_version"] = JUDGE_VERSION
            return j
    return {"error": "judge failed"}


PAIR_RUBRIC = """You compare two replies to the same WhatsApp message. Each was written as the owner (a real person).
Decide which one a real person, the owner, more plausibly typed. First list the concrete differences between
the two (length, opener, shape, details, humour, warmth, stalling), then decide.

What reads human: a specific aside a person tells (a small story, a named person, a funny or self-mocking
line); reacting to their situation in the owner's way (teasing, banter, sympathy shown); the other person's
name or shared context used naturally; a plain position; a length that fits the relationship.
What reads written: stock openers ("Fair question", "Great question"); tidy answer-reason-lesson shape;
poster-like closing advice; facts listed like a CV or report; covering every angle; a tacked-on question;
polite filler; "let me check and come back" about something the owner obviously knows.
Length: a short reply with one personal touch beats a longer one. Facts being right or wrong does NOT matter.

Reply with JSON only:
{"differences": ["..."], "more_natural": "A" | "B" | "tie", "more_like_owner": "A" | "B" | "tie",
 "why": "one line"}"""


HUMAN_RUBRIC = """You compare two replies to the same WhatsApp message. You do not know the sender. Which one
sounds more like a real person texting, rather than an AI? First list the concrete differences, then decide.
Judge only how human it sounds, not whether facts are right.

Reply with JSON only:
{"differences": ["..."], "more_natural": "A" | "B" | "tie", "more_like_owner": "tie", "why": "one line"}"""


def pair(msg: str, who: str, a: str, b: str, samples: str, model: str, cwd: Path,
         blind: bool = False) -> dict:
    """Pairwise, both orders. A verdict counts only if it survives the swap; else tie.
    blind: the plain human-likeness question, no owner samples (what a stranger would judge)."""
    def once(x, y):
        head = (HUMAN_RUBRIC + "\n\n" + WHATSAPP) if blind else (f"{PAIR_RUBRIC}\n\n=== REFERENCE SAMPLES (the owner's real "
                                           f"words) ===\n{samples}\n{typical_length(samples)}\n\n{WHATSAPP}")
        prompt = (f"{head}\n\n=== MESSAGE from {who} ===\n{msg}\n\n"
                  f"=== REPLY A ===\n{x}\n\n=== REPLY B ===\n{y}\n")
        for _ in range(2):
            j = parse(_ask(prompt, model, cwd))
            if j and "more_natural" in j:
                return j
        return {}
    j1, j2 = once(a, b), once(b, a)
    flip = {"A": "B", "B": "A", "tie": "tie"}
    out = {"why": [j1.get("why"), j2.get("why")], "judge_version": JUDGE_VERSION}
    for k in ("more_natural", "more_like_owner"):
        v1, v2 = j1.get(k), flip.get(j2.get(k))
        out[k] = v1 if v1 == v2 and v1 in ("A", "B") else "tie"
        out[k + "_flip"] = v1 != v2
    return out
