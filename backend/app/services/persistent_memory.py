"""Persistent agent memory service (#17, #18).

Replaces the ephemeral in-process AgentMemory with a DB-backed store that
persists across runs and process restarts.  Enables the agent to learn from
past denial patterns and apply that knowledge to future planning.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models import AgentMemoryEntry
from app.utils.time import utc_now

logger = logging.getLogger("app.persistent_memory")

# Maximum memory entries to retain per category
MAX_ENTRIES_PER_CATEGORY = 200

# Categories of memory
CATEGORY_DECISION = "decision"          # governance decisions and outcomes
CATEGORY_DENIAL_PATTERN = "denial"      # extracted denial patterns
CATEGORY_LEARNING = "learning"          # internalized lessons
CATEGORY_STRATEGY = "strategy"          # successful strategies


class PersistentMemory:
    """DB-backed agent memory that survives across runs and restarts."""

    def store_decision(
        self,
        db: Session,
        run_id: str,
        proposal_intent: str,
        proposal_params: Dict[str, Any],
        decision: str,
        policy_hits: List[str],
        reasons: List[str],
        was_executed: bool,
    ) -> None:
        """Store a governance decision outcome for future reference."""
        entry = AgentMemoryEntry(
            run_id=run_id,
            category=CATEGORY_DECISION,
            ts=utc_now(),
            content_json=json.dumps({
                "intent": proposal_intent,
                "params": proposal_params,
                "decision": decision,
                "policy_hits": policy_hits,
                "reasons": reasons,
                "was_executed": was_executed,
            }),
            importance=self._compute_importance(decision, policy_hits),
        )
        db.add(entry)
        self._enforce_limit(db, CATEGORY_DECISION)

    def store_denial_pattern(
        self,
        db: Session,
        run_id: str,
        pattern: Dict[str, Any],
    ) -> None:
        """Store an extracted denial pattern for learning."""
        entry = AgentMemoryEntry(
            run_id=run_id,
            category=CATEGORY_DENIAL_PATTERN,
            ts=utc_now(),
            content_json=json.dumps(pattern),
            importance=0.8,
        )
        db.add(entry)
        self._enforce_limit(db, CATEGORY_DENIAL_PATTERN)

    def store_learning(
        self,
        db: Session,
        run_id: str,
        lesson: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store an internalized lesson learned from run outcomes."""
        entry = AgentMemoryEntry(
            run_id=run_id,
            category=CATEGORY_LEARNING,
            ts=utc_now(),
            content_json=json.dumps({
                "lesson": lesson,
                "context": context or {},
            }),
            importance=0.9,
        )
        db.add(entry)
        self._enforce_limit(db, CATEGORY_LEARNING)

    def store_strategy(
        self,
        db: Session,
        run_id: str,
        strategy: Dict[str, Any],
    ) -> None:
        """Store a successful strategy for future reuse."""
        entry = AgentMemoryEntry(
            run_id=run_id,
            category=CATEGORY_STRATEGY,
            ts=utc_now(),
            content_json=json.dumps(strategy),
            importance=0.7,
        )
        db.add(entry)
        self._enforce_limit(db, CATEGORY_STRATEGY)

    def recall(
        self,
        db: Session,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Recall memory entries, optionally filtered by category."""
        q = db.query(AgentMemoryEntry)
        if category:
            q = q.filter(AgentMemoryEntry.category == category)
        rows = q.order_by(AgentMemoryEntry.importance.desc(), AgentMemoryEntry.ts.desc()).limit(limit).all()
        return [
            {
                "id": r.id,
                "run_id": r.run_id,
                "category": r.category,
                "ts": r.ts.isoformat() if r.ts else None,
                "content": json.loads(r.content_json),
                "importance": r.importance,
            }
            for r in rows
        ]

    def recall_denial_patterns(self, db: Session, limit: int = 10) -> List[Dict[str, Any]]:
        """Recall denial patterns for planning avoidance."""
        return self.recall(db, category=CATEGORY_DENIAL_PATTERN, limit=limit)

    def recall_similar(
        self,
        db: Session,
        query: str,
        category: Optional[str] = None,
        limit: int = 10,
        threshold: float = 0.1,
    ) -> List[Dict[str, Any]]:
        """Semantic similarity retrieval using TF-IDF cosine similarity.

        No external dependencies — uses pure-Python TF-IDF over stored entries.
        Returns entries sorted by similarity score above threshold.
        """
        import math
        import re as _re

        # Tokenize helper
        def tokenize(text: str) -> List[str]:
            return _re.findall(r"[a-z0-9_]+", text.lower())

        query_tokens = tokenize(query)
        if not query_tokens:
            return self.recall(db, category=category, limit=limit)

        # Fetch candidate entries
        q = db.query(AgentMemoryEntry)
        if category:
            q = q.filter(AgentMemoryEntry.category == category)
        candidates = q.order_by(AgentMemoryEntry.ts.desc()).limit(500).all()

        if not candidates:
            return []

        # Build document corpus
        docs: List[List[str]] = []
        for c in candidates:
            text = c.content_json or ""
            docs.append(tokenize(text))

        # IDF from corpus
        doc_count = len(docs) + 1  # +1 for query
        term_doc_freq: Dict[str, int] = {}
        all_docs_plus_query = docs + [query_tokens]
        for d in all_docs_plus_query:
            seen = set(d)
            for t in seen:
                term_doc_freq[t] = term_doc_freq.get(t, 0) + 1

        idf: Dict[str, float] = {}
        for term, df in term_doc_freq.items():
            idf[term] = math.log((doc_count + 1) / (df + 1)) + 1

        # TF-IDF vector for query
        def tfidf_vector(tokens: List[str]) -> Dict[str, float]:
            tf: Dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            vec: Dict[str, float] = {}
            for t, count in tf.items():
                vec[t] = (1 + math.log(count)) * idf.get(t, 1.0)
            return vec

        def cosine_sim(v1: Dict[str, float], v2: Dict[str, float]) -> float:
            intersection = set(v1) & set(v2)
            if not intersection:
                return 0.0
            dot = sum(v1[t] * v2[t] for t in intersection)
            mag1 = math.sqrt(sum(x * x for x in v1.values()))
            mag2 = math.sqrt(sum(x * x for x in v2.values()))
            if mag1 == 0 or mag2 == 0:
                return 0.0
            return dot / (mag1 * mag2)

        q_vec = tfidf_vector(query_tokens)

        # Score each candidate
        scored = []
        for i, c in enumerate(candidates):
            d_vec = tfidf_vector(docs[i])
            sim = cosine_sim(q_vec, d_vec)
            if sim >= threshold:
                scored.append((sim, c))

        # Sort by similarity descending
        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "id": c.id,
                "run_id": c.run_id,
                "category": c.category,
                "ts": c.ts.isoformat() if c.ts else None,
                "content": json.loads(c.content_json),
                "importance": c.importance,
                "similarity": round(sim, 4),
            }
            for sim, c in scored[:limit]
        ]

    def recall_for_context(self, db: Session, max_tokens: int = 1500) -> str:
        """Build a text context string from memory for LLM prompts."""
        entries = self.recall(db, limit=15)
        if not entries:
            return "No persistent memory entries."

        lines = ["Persistent agent memory (learned from past runs):"]
        char_count = 0
        for e in entries:
            content = e["content"]
            if e["category"] == CATEGORY_DECISION:
                line = (
                    f"- [{e['category']}] {content.get('intent', '?')} "
                    f"→ {content.get('decision', '?')} "
                    f"(policies: {', '.join(content.get('policy_hits', []))})"
                )
            elif e["category"] == CATEGORY_LEARNING:
                line = f"- [lesson] {content.get('lesson', '?')}"
            elif e["category"] == CATEGORY_DENIAL_PATTERN:
                line = f"- [denial pattern] {json.dumps(content)[:100]}"
            else:
                line = f"- [{e['category']}] {json.dumps(content)[:80]}"

            if char_count + len(line) > max_tokens * 4:  # rough char-to-token
                break
            lines.append(line)
            char_count += len(line)

        return "\n".join(lines)

    def get_stats(self, db: Session) -> Dict[str, Any]:
        """Get memory statistics."""
        categories = {}
        for cat in [CATEGORY_DECISION, CATEGORY_DENIAL_PATTERN, CATEGORY_LEARNING, CATEGORY_STRATEGY]:
            count = db.query(AgentMemoryEntry).filter(AgentMemoryEntry.category == cat).count()
            categories[cat] = count
        total = sum(categories.values())
        return {"total_entries": total, "by_category": categories}

    def extract_lessons_from_run(self, db: Session, run_id: str) -> List[str]:
        """Internalized learning: analyze a run's decisions and extract lessons.

        This is the core of item #18 — the agent examines its own history
        and produces generalizable lessons.
        """
        decisions = self.recall(db, category=CATEGORY_DECISION, limit=50)
        run_decisions = [d for d in decisions if d.get("run_id") == run_id]

        if not run_decisions:
            return []

        lessons: List[str] = []
        denial_count = sum(1 for d in run_decisions if d["content"].get("decision") != "APPROVED")
        total = len(run_decisions)

        # Learn from high denial rates
        if total > 5 and denial_count / total > 0.3:
            # Find most common policy hits
            policy_counter: Dict[str, int] = {}
            for d in run_decisions:
                for p in d["content"].get("policy_hits", []):
                    policy_counter[p] = policy_counter.get(p, 0) + 1
            top_policy = max(policy_counter, key=policy_counter.get) if policy_counter else "unknown"
            lesson = f"Run {run_id[:8]} had {denial_count}/{total} denials, mostly from {top_policy}. Prefer slower speeds and wider clearance when approaching that policy boundary."
            lessons.append(lesson)
            self.store_learning(db, run_id, lesson, {"denial_rate": denial_count / total, "top_policy": top_policy})

            # Store denial pattern
            self.store_denial_pattern(db, run_id, {
                "top_policy": top_policy,
                "denial_rate": round(denial_count / total, 3),
                "total_decisions": total,
            })

        # Learn from successful strategies
        approved = [d for d in run_decisions if d["content"].get("decision") == "APPROVED" and d["content"].get("was_executed")]
        if len(approved) > 5:
            # Extract common successful parameters
            speeds = []
            for a in approved:
                params = a["content"].get("params", {})
                s = params.get("max_speed")
                if s is not None:
                    speeds.append(float(s))
            if speeds:
                avg_speed = sum(speeds) / len(speeds)
                lesson = f"Successful runs typically use speed ~{avg_speed:.2f}m/s. Store as preferred speed baseline."
                lessons.append(lesson)
                self.store_strategy(db, run_id, {
                    "type": "preferred_speed",
                    "avg_speed": round(avg_speed, 3),
                    "sample_size": len(speeds),
                })

        return lessons

    @staticmethod
    def _compute_importance(decision: str, policy_hits: List[str]) -> float:
        """Higher importance for denials and safety-related decisions."""
        base = 0.5
        if decision in ("DENIED", "NEEDS_REVIEW"):
            base = 0.8
        if any(p in policy_hits for p in ["GEOFENCE_01", "HUMAN_PROXIMITY_02", "WORKER_PROXIMITY_06"]):
            base = max(base, 0.9)
        return base

    @staticmethod
    def _enforce_limit(db: Session, category: str) -> None:
        """Remove oldest low-importance entries if category exceeds limit."""
        count = db.query(AgentMemoryEntry).filter(AgentMemoryEntry.category == category).count()
        if count > MAX_ENTRIES_PER_CATEGORY:
            excess = count - MAX_ENTRIES_PER_CATEGORY
            oldest = (
                db.query(AgentMemoryEntry)
                .filter(AgentMemoryEntry.category == category)
                .order_by(AgentMemoryEntry.importance.asc(), AgentMemoryEntry.ts.asc())
                .limit(excess)
                .all()
            )
            for entry in oldest:
                db.delete(entry)
