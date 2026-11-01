"""From screened guidance to a temporary site constraint, with no model involved.

* Hazard classes are read from accepted text with a fixed keyword lexicon.
* A class is ENFORCED only when at least two distinct authoritative domains
  report it (corroboration). One source alone is shown as advice only.
* Each class maps to a reviewed constraint (exclusion radius, slow radius,
  speed). The strictest class wins; values are clamped to fixed bounds.
* Constraints can only tighten: every spill gets a baseline rule, and outside
  information can raise the radius or lower the speed, never the reverse.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional

from app.services.site_intel.firewall import Screened

LEXICON: Dict[str, List[str]] = {
    "toxic_vapour": [r"toxic if inhaled", r"fatal if inhaled", r"harmful if inhaled", r"toxic (gas|vapou?rs?|fumes)",
                     r"chlorine gas", r"inhalation hazard", r"may cause respiratory irritation", r"respiratory (tract )?irritation"],
    "flammable": [r"\bhighly flammable\b", r"\bflammable (liquid|vapou?r)", r"\bignition sources?\b", r"\bflash ?point\b",
                  r"\bexplosive (mixture|atmosphere)", r"\bvapou?rs? may (form|ignite)", r"\bflammable\b"],
    "oxidiser": [r"\boxidi[sz](er|ing|ising|izing)\b", r"may intensify fire"],
    "corrosive": [r"\bcorrosive\b", r"severe skin burns", r"serious eye damage", r"causes burns"],
    "slippery": [r"\bslip(pery| hazard|s| and fall|ping)\b", r"\bslick\b", r"\boily\b", r"\blubricant\b"],
}
_LEX = {k: [re.compile(p, re.I) for p in v] for k, v in LEXICON.items()}

# Reviewed constraint per class: (exclusion radius m, slow radius m, max speed m/s)
CLASS_RULES: Dict[str, tuple] = {
    "toxic_vapour": (5.0, 8.0, 0.2),
    "flammable": (3.0, 6.0, 0.2),
    "oxidiser": (2.5, 5.0, 0.3),
    "corrosive": (2.0, 4.0, 0.3),
    "slippery": (1.5, 3.0, 0.3),
}
BASELINE = (1.2, 3.0, 0.3)      # any spill, before (or without) a lookup
BOUNDS = {"radius": (1.0, 6.0), "slow_radius": (2.0, 10.0), "max_speed": (0.1, 0.3)}
CORROBORATION = 2


@dataclass
class HazardAssessment:
    substance: str
    classes_enforced: List[str]
    classes_advisory: List[str]
    evidence: Dict[str, List[str]]          # class -> domains that reported it
    radius: float
    slow_radius: float
    max_speed: float
    basis: str                              # human-readable reason for the numbers

    def as_dict(self) -> Dict:
        return asdict(self)


def classify(text: str) -> List[str]:
    return [c for c, rxs in _LEX.items() if any(rx.search(text or "") for rx in rxs)]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def assess(substance: str, items: Iterable[Screened]) -> HazardAssessment:
    evidence: Dict[str, set] = {}
    for it in items:
        if it.verdict != "accepted" or not it.trusted_source:
            continue
        for c in classify(f"{it.title} {it.text}"):
            evidence.setdefault(c, set()).add(it.source)
    enforced = sorted(c for c, d in evidence.items() if len(d) >= CORROBORATION)
    advisory = sorted(c for c, d in evidence.items() if len(d) < CORROBORATION)
    radius, slow, speed = BASELINE
    basis = "Baseline spill rule"
    for c in enforced:
        r, s, v = CLASS_RULES[c]
        if r > radius or s > slow or v < speed:
            basis = f"{c.replace('_', ' ')}, reported by {len(evidence[c])} authoritative sources"
        radius, slow, speed = max(radius, r), max(slow, s), min(speed, v)
    radius = _clamp(radius, *BOUNDS["radius"])
    slow = _clamp(max(slow, radius + 1.0), *BOUNDS["slow_radius"])
    speed = _clamp(speed, *BOUNDS["max_speed"])
    return HazardAssessment(substance=substance, classes_enforced=enforced, classes_advisory=advisory,
                            evidence={c: sorted(d) for c, d in evidence.items()},
                            radius=round(radius, 2), slow_radius=round(slow, 2), max_speed=round(speed, 2), basis=basis)


def query_for(substance: str) -> str:
    return f"{substance} spill hazards handling precautions workplace safety data"


# ---------------------------------------------------------------------------
# Offline samples: used ONLY when no TAVILY_API_KEY is set, and always labelled
# as samples in receipts and the interface. Paraphrased reference text, written
# for this demo; not retrieved results.
# ---------------------------------------------------------------------------
OFFLINE_SAMPLES: Dict[str, List[Dict[str, str]]] = {
    "isopropyl alcohol": [
        {"url": "https://pubchem.ncbi.nlm.nih.gov/compound/Isopropanol", "title": "Isopropanol (sample)",
         "content": "Highly flammable liquid and vapour. Vapours may form explosive mixtures with air. Keep away from ignition sources. May cause respiratory irritation."},
        {"url": "https://www.cdc.gov/niosh/npg/", "title": "NIOSH Pocket Guide (sample)",
         "content": "Isopropyl alcohol: flammable liquid; flash point about 12 C. Eliminate ignition sources; ventilate the area of the spill."},
        {"url": "https://www.hse.gov.uk/fireandexplosion/", "title": "HSE fire and explosion (sample)",
         "content": "Flammable liquid spills give off vapour that can ignite; keep sources of ignition, including electrical equipment, away."},
    ],
    "hydraulic oil": [
        {"url": "https://www.hse.gov.uk/slips/", "title": "HSE slips and trips (sample)",
         "content": "Oil on floors is a common slip hazard; contain and clean spills promptly and keep people away from slippery surfaces."},
        {"url": "https://www.osha.gov/walking-working-surfaces", "title": "OSHA walking-working surfaces (sample)",
         "content": "Floors must be kept free of oil and other slip hazards; spills create slippery conditions."},
    ],
    "sodium hypochlorite solution": [
        {"url": "https://pubchem.ncbi.nlm.nih.gov/compound/Sodium-hypochlorite", "title": "Sodium hypochlorite (sample)",
         "content": "Causes severe skin burns and eye damage. Corrosive. Contact with acids liberates toxic gas (chlorine gas)."},
        {"url": "https://www.cdc.gov/niosh/npg/", "title": "NIOSH Pocket Guide (sample)",
         "content": "Hypochlorite solutions are corrosive; mixing with acids may release chlorine gas, an inhalation hazard."},
        {"url": "https://echa.europa.eu/", "title": "ECHA substance information (sample)",
         "content": "Classified as corrosive to skin; may cause respiratory irritation where chlorine is released."},
    ],
    "detergent": [
        {"url": "https://www.hse.gov.uk/slips/", "title": "HSE slips and trips (sample)",
         "content": "Wet floors and cleaning products cause slips; use signs and keep people away until dry."},
    ],
}


def offline_results(substance: str) -> List[Dict[str, str]]:
    return OFFLINE_SAMPLES.get(substance.lower().strip(), [])
