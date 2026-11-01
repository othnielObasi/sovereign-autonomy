"""
Compliance Report Service
Generates audit reports for regulatory compliance (ISO 42001, EU AI Act, etc.)
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class ComplianceMetrics(BaseModel):
    total_decisions: int = 0
    approved: int = 0
    denied: int = 0
    approval_rate: float = 0.0
    avg_risk_score: float = 0.0
    max_risk_score: float = 0.0
    violations_by_policy: Dict[str, int] = {}
    critical_violations: int = 0


class AuditEntry(BaseModel):
    timestamp: str
    decision_id: str
    action_type: str
    approved: bool
    risk_score: float
    violations: List[str]
    hash: str
    previous_hash: str


class ComplianceReport(BaseModel):
    report_id: str
    generated_at: str
    run_id: str
    period_start: str
    period_end: str
    metrics: ComplianceMetrics
    audit_entries: List[AuditEntry]
    chain_valid: bool
    framework_mapping: Dict[str, List[str]]


class ComplianceReportService:
    """Generates compliance reports from governance decisions."""
    
    def __init__(self):
        self.framework_mappings = {
            "EU_AI_ACT": [
                "Article 9: Risk Management System",
                "Article 11: Technical Documentation", 
                "Article 12: Record-Keeping",
                "Article 13: Transparency",
                "Article 14: Human Oversight",
                "Article 15: Accuracy and Robustness",
            ],
            "ISO_42001": [
                "Clause 6: Planning - Risk Assessment",
                "Clause 7: Support - Monitoring",
                "Clause 8: Operation - Risk Treatment",
                "Clause 9: Evaluation - Internal Audit",
                "Clause 10: Improvement - Continual",
            ],
            "NIST_AI_RMF": [
                "GOVERN: Policy configuration and access control",
                "MAP: Context-aware risk assessment",
                "MEASURE: Continuous risk scoring",
                "MANAGE: Real-time policy enforcement",
            ],
        }
    
    def generate_report(
        self,
        run_id: str,
        events: List[Dict[str, Any]],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        framework: str = "ISO_42001",
    ) -> ComplianceReport:
        """Generate a compliance report from governance events."""
        
        now = datetime.now(timezone.utc)
        
        # Calculate metrics
        metrics = self._calculate_metrics(events)
        
        # Build audit entries with hash chain
        audit_entries = self._build_audit_chain(events)
        
        # Verify chain integrity
        chain_valid = self._verify_chain(audit_entries)
        
        # Get framework mapping
        framework_mapping = {
            framework: self.framework_mappings.get(framework, [])
        }
        
        return ComplianceReport(
            report_id=f"CR-{run_id}-{now.strftime('%Y%m%d%H%M%S')}",
            generated_at=now.isoformat() + "Z",
            run_id=run_id,
            period_start=(start_time or now).isoformat() + "Z",
            period_end=(end_time or now).isoformat() + "Z",
            metrics=metrics,
            audit_entries=audit_entries,
            chain_valid=chain_valid,
            framework_mapping=framework_mapping,
        )
    
    def _calculate_metrics(self, events: List[Dict[str, Any]]) -> ComplianceMetrics:
        """Calculate compliance metrics from events."""
        
        if not events:
            return ComplianceMetrics()
        
        total = len(events)
        approved = sum(1 for e in events if e.get("approved", False))
        denied = total - approved
        
        risk_scores = [e.get("risk_score", 0) for e in events]
        avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0
        max_risk = max(risk_scores) if risk_scores else 0
        
        # Count violations by policy
        violations_by_policy: Dict[str, int] = {}
        critical_count = 0
        
        for event in events:
            for violation in event.get("violations", []):
                policy_id = violation.get("policy_id", "unknown")
                violations_by_policy[policy_id] = violations_by_policy.get(policy_id, 0) + 1
                
                if violation.get("severity") == "HIGH":
                    critical_count += 1
        
        return ComplianceMetrics(
            total_decisions=total,
            approved=approved,
            denied=denied,
            approval_rate=approved / total if total > 0 else 0,
            avg_risk_score=round(avg_risk, 3),
            max_risk_score=round(max_risk, 3),
            violations_by_policy=violations_by_policy,
            critical_violations=critical_count,
        )
    
    def _build_audit_chain(self, events: List[Dict[str, Any]]) -> List[AuditEntry]:
        """Build audit entries with SHA-256 hash chain."""
        
        entries = []
        previous_hash = "0" * 64  # Genesis hash
        
        for event in events:
            # Create entry data
            entry_data = {
                "timestamp": event.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "decision_id": event.get("id", "unknown"),
                "action_type": event.get("action_type", "unknown"),
                "approved": event.get("approved", False),
                "risk_score": event.get("risk_score", 0),
                "violations": [v.get("policy_id", "") for v in event.get("violations", [])],
            }
            
            # Calculate hash
            hash_input = json.dumps(entry_data, sort_keys=True) + previous_hash
            current_hash = hashlib.sha256(hash_input.encode()).hexdigest()
            
            entry = AuditEntry(
                timestamp=entry_data["timestamp"],
                decision_id=entry_data["decision_id"],
                action_type=entry_data["action_type"],
                approved=entry_data["approved"],
                risk_score=entry_data["risk_score"],
                violations=entry_data["violations"],
                hash=current_hash,
                previous_hash=previous_hash,
            )
            
            entries.append(entry)
            previous_hash = current_hash
        
        return entries
    
    def _verify_chain(self, entries: List[AuditEntry]) -> bool:
        """Verify the integrity of the audit chain."""
        
        if not entries:
            return True
        
        previous_hash = "0" * 64
        
        for entry in entries:
            if entry.previous_hash != previous_hash:
                return False
            
            # Recalculate hash
            entry_data = {
                "timestamp": entry.timestamp,
                "decision_id": entry.decision_id,
                "action_type": entry.action_type,
                "approved": entry.approved,
                "risk_score": entry.risk_score,
                "violations": entry.violations,
            }
            
            hash_input = json.dumps(entry_data, sort_keys=True) + previous_hash
            calculated_hash = hashlib.sha256(hash_input.encode()).hexdigest()
            
            if calculated_hash != entry.hash:
                return False
            
            previous_hash = entry.hash
        
        return True
    
    def export_json(self, report: ComplianceReport) -> str:
        """Export report as JSON."""
        return report.model_dump_json(indent=2)
    
    def export_summary(self, report: ComplianceReport) -> str:
        """Export a human-readable summary."""
        
        lines = [
            "=" * 60,
            "COMPLIANCE REPORT",
            "=" * 60,
            f"Report ID: {report.report_id}",
            f"Generated: {report.generated_at}",
            f"Run ID: {report.run_id}",
            f"Period: {report.period_start} to {report.period_end}",
            "",
            "DECISION STATISTICS",
            "-" * 40,
            f"Total Decisions: {report.metrics.total_decisions}",
            f"Approved: {report.metrics.approved}",
            f"Denied: {report.metrics.denied}",
            f"Approval Rate: {report.metrics.approval_rate:.1%}",
            "",
            "RISK ANALYSIS",
            "-" * 40,
            f"Average Risk Score: {report.metrics.avg_risk_score}",
            f"Maximum Risk Score: {report.metrics.max_risk_score}",
            f"Critical Violations: {report.metrics.critical_violations}",
            "",
            "VIOLATIONS BY POLICY",
            "-" * 40,
        ]
        
        for policy, count in report.metrics.violations_by_policy.items():
            lines.append(f"  {policy}: {count}")
        
        lines.extend([
            "",
            "AUDIT CHAIN INTEGRITY",
            "-" * 40,
            f"Chain Valid: {'✓ VERIFIED' if report.chain_valid else '✗ COMPROMISED'}",
            f"Total Entries: {len(report.audit_entries)}",
            "",
            "FRAMEWORK COMPLIANCE",
            "-" * 40,
        ])
        
        for framework, articles in report.framework_mapping.items():
            lines.append(f"\n{framework}:")
            for article in articles:
                lines.append(f"  ✓ {article}")
        
        lines.append("=" * 60)
        
        return "\n".join(lines)


# Singleton instance
compliance_service = ComplianceReportService()
