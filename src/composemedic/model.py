"""Stable, deliberately small report format. Never include raw config or logs."""

from dataclasses import asdict, dataclass, field
import re


def safe_label(value: object) -> str:
    """Prevent terminal control sequences in untrusted service/field names."""
    return re.sub(r"[\x00-\x1f\x7f-\x9f]", "?", str(value))[:160]


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    service: str
    field: str
    message: str
    suggestion: str


@dataclass
class Report:
    mode: str = "offline"
    services_checked: int = 0
    findings: list[Finding] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def add(self, code: str, severity: str, service: str, path: str,
            message: str, suggestion: str) -> None:
        finding = Finding(code, severity, safe_label(service), safe_label(path),
                          safe_label(message), safe_label(suggestion))
        if finding not in self.findings:
            self.findings.append(finding)

    def to_dict(self) -> dict:
        ordered = sorted(self.findings, key=lambda f: ({"error": 0, "warning": 1, "info": 2}[f.severity], f.service, f.code, f.field))
        return {"schema_version": 1, "tool": "composemedic", "version": "0.1.0",
                "mode": self.mode, "services_checked": self.services_checked,
                "summary": {level: sum(f.severity == level for f in ordered) for level in ("error", "warning", "info")},
                "findings": [asdict(f) for f in ordered], "limitations": self.limitations}
