"""Bounded, source-balanced sharing policy for advisory congestion only."""
from __future__ import annotations

from collections import defaultdict
import statistics

MIN_SOURCES = 2
MAX_DELAY_S = 60.0
OUTLIER_CELLS = 3


def verified_decision(record):
    """Never launder an unsigned/edited gate row into newly signed memory."""
    from app.services.governance_engine import GovernanceEngine
    from app.utils import signing
    try:
        return bool(record.signature and record.signing_key_id and
                    signing.verify(GovernanceEngine.signing_payload(record), record.signature,
                                   record.signing_key_id).get('valid'))
    except (ValueError, TypeError, KeyError, AttributeError):
        return False


def aggregate(records, quarantined_sources=()):
    """One peak per source/cell; the second-highest peak needs two witnesses.

    A source cannot amplify its vote through repeated missions. Each of the two
    supporting votes is clipped to the smaller peak, with equal (50%) weight.
    Mild-record flooding cannot dilute a source's previous stop observation.
    """
    peaks = defaultdict(dict)
    for r in records:
        if r['source_robot_id'] in quarantined_sources:
            continue
        cell, source = (r['i'], r['j']), r['source_robot_id']
        peaks[cell][source] = max(peaks[cell].get(source, 0.0), min(MAX_DELAY_S, r['effective_delay']))
    costs, support = {}, {}
    for cell, sources in peaks.items():
        ordered = sorted(sources.items(), key=lambda v: (-v[1], v[0]))
        if len(ordered) >= MIN_SOURCES:
            costs[cell] = ordered[1][1]
            support[cell] = [s for s, _ in ordered[:MIN_SOURCES]]
    return costs, peaks, support


def outliers(peaks):
    """Flag repeated high outliers only against two agreeing independent peers.

    This is an anomaly heuristic, not proof of maliciousness or sensor truth.
    It is scoped to the exact experience context by the caller.
    """
    strikes = defaultdict(list)
    for cell, sources in peaks.items():
        for source, value in sources.items():
            peers = [v for s, v in sources.items() if s != source]
            if len(peers) < 2:
                continue
            middle = statistics.median(peers)
            agreeing = [v for v in peers if abs(v - middle) <= 0.5]
            if len(agreeing) >= 2 and value >= max(3.5, middle * 2.5) and value - middle >= 2:
                strikes[source].append(list(cell))
    return {source: cells for source, cells in strikes.items() if len(cells) >= OUTLIER_CELLS}
