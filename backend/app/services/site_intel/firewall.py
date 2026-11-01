"""Context firewall: every piece of outside text is screened before anything uses it.

Outside text (web results, noticeboard bulletins) is data, never instructions.
The firewall
  * strips markup and hidden characters, and bounds the length,
  * flags text that tries to instruct an AI or robot, or to relax a safety rule,
  * marks whether the source is on the authoritative allowlist,
  * fingerprints the content so receipts can prove what was seen.

Quarantined items are logged and never reach the planner or the rule builder.
Accepted items are still only *advisory* to the planner; the gate never reads
outside text at all.
"""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List

# Authoritative hazard-reference publishers. Only these can corroborate a hazard.
TRUSTED_DOMAINS = (
    "hse.gov.uk", "gov.uk", "osha.gov", "cdc.gov", "epa.gov", "noaa.gov",
    "echa.europa.eu", "europa.eu", "pubchem.ncbi.nlm.nih.gov", "nih.gov",
    "who.int", "ilo.org", "ccohs.ca", "safeworkaustralia.gov.au",
)

MAX_CHARS = 700

_HIDDEN = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAGS = re.compile(r"<[^>]{0,400}>")
_WS = re.compile(r"\s+")

# (flag, pattern). Patterns target text that addresses an AI/robot or relaxes a
# rule; ordinary safety guidance ("remove ignition sources") must not trip them.
_RULES = [
    ("prompt_injection", r"\b(ignore|disregard|forget)\b[^.]{0,30}\b(previous|prior|above|earlier|all|your|the)\b[^.]{0,20}\b(instructions?|rules?|prompts?|polic(y|ies)|guidance)\b"),
    ("prompt_injection", r"\b(system|developer)\s+(prompt|message|instructions?)\b"),
    ("prompt_injection", r"\byou are (now|an?|the)\b[^.]{0,40}\b(ai|assistant|model|planner|robot|agent)\b"),
    ("prompt_injection", r"\b(new|updated|revised)\s+instructions?\s*(for|to)\b[^.]{0,20}\b(ai|assistant|model|planner|robots?|agents?|amrs?)\b"),
    ("prompt_injection", r"\b(as an ai|jailbreak|do anything now)\b"),
    ("relax_safety", r"\b(disable|disabled|suspend|suspended|switch(ed)? off|turn(ed)? off|bypass(ed)?|override|overridden|lift(ed)?|waive(d)?|relax(ed)?|ignore|deactivate(d)?)\b[^.]{0,40}\b(safety|speed limits?|limits?|geofences?|sensors?|lidar|e-?stops?|interlocks?|exclusion|polic(y|ies)|rules?|governance|checks?|stop radius)\b"),
    ("relax_safety", r"\b(speed limits?|safety (rules|checks?|limits?)|exclusion zones?|stop radius|geofence)\b[^.]{0,40}\b(suspended|lifted|waived|disabled|removed|no longer (apply|applies|required)|do(es)? not apply|not required|raised to)\b"),
    ("robot_permission", r"\b(robots?|amrs?|agvs?|autonomous (vehicles?|robots?)|planners?)\b[^.]{0,50}\b(may|can|are (now )?(allowed|permitted|authori[sz]ed|cleared))\b[^.]{0,60}\b(pass|drive|move|enter|operate|proceed|ignore|exceed|approach)\b"),
    ("robot_permission", r"\b(approve|authori[sz]e|whitelist|allow)\b[^.]{0,20}\b(all|every|any)\b[^.]{0,20}\b(moves?|motions?|routes?|actions?|commands?)\b"),
    ("proximity_claim", r"\bwithin\s+0?\.\d+\s*(m|metres?|meters?)\b[^.]{0,30}\b(of\s+)?(staff|people|workers|pedestrians|personnel|operatives)\b"),
    ("hidden_content", r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0)"),
    ("encoded_payload", r"[A-Za-z0-9+/]{120,}={0,2}"),
    ("script", r"<\s*script|javascript:"),
]
_COMPILED = [(f, re.compile(p, re.I)) for f, p in _RULES]


@dataclass
class Screened:
    source: str                 # domain, or e.g. "noticeboard"
    url: str
    title: str
    text: str                   # sanitised, bounded
    content_sha256: str         # fingerprint of the ORIGINAL content
    trusted_source: bool
    verdict: str                # "accepted" | "quarantined"
    flags: List[Dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return asdict(self)


def is_trusted(domain: str) -> bool:
    d = (domain or "").lower()
    return any(d == t or d.endswith("." + t) for t in TRUSTED_DOMAINS)


def sanitise(raw: str) -> str:
    t = _COMMENT.sub(" ", raw or "")
    t = _TAGS.sub(" ", t)
    t = html.unescape(t)
    t = _HIDDEN.sub("", t)
    t = _WS.sub(" ", t).strip()
    return t[:MAX_CHARS]


def screen(raw: str, *, source: str, url: str = "", title: str = "") -> Screened:
    """Screen one item. Flags are checked on the raw text (to catch hidden markup)
    and on the sanitised text (to catch instructions split by markup)."""
    raw = raw or ""
    clean = sanitise(raw)
    flags: List[Dict[str, str]] = []
    seen = set()
    for label, rx in _COMPILED:
        for hay in (raw, clean, title or ""):
            m = rx.search(hay)
            if m:
                snippet = m.group(0)[:90]
                if (label, snippet.lower()) not in seen:
                    seen.add((label, snippet.lower()))
                    flags.append({"flag": label, "match": snippet})
                break
    if _HIDDEN.search(raw):
        flags.append({"flag": "hidden_content", "match": "zero-width / bidi characters"})
    return Screened(
        source=source, url=url, title=sanitise(title)[:200], text=clean,
        content_sha256=hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest(),
        trusted_source=is_trusted(source),
        verdict="quarantined" if flags else "accepted",
        flags=flags,
    )
