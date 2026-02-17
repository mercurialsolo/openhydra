"""Static analysis for skill scripts — regex-based dangerous pattern detection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import RiskLevel, StaticFinding

# Each pattern: (compiled regex, description, severity)
_PATTERNS: list[tuple[re.Pattern[str], str, RiskLevel]] = []


@dataclass
class _PatternDef:
    regex: str
    description: str
    severity: RiskLevel


_PATTERN_DEFS: list[_PatternDef] = [
    _PatternDef(
        regex=r"rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?-[a-zA-Z]*r|rm\s+(-[a-zA-Z]*r[a-zA-Z]*\s+)?-[a-zA-Z]*f|rm\s+-[a-zA-Z]*rf",
        description="Recursive force delete (rm -rf)",
        severity=RiskLevel.CRITICAL,
    ),
    _PatternDef(
        regex=r"curl\s+.*\|\s*(ba)?sh|wget\s+.*\|\s*(ba)?sh",
        description="Remote code execution via curl/wget pipe to shell",
        severity=RiskLevel.CRITICAL,
    ),
    _PatternDef(
        regex=r"\$\{?[A-Z_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z_]*\}?",
        description="Potential environment variable exfiltration (secrets)",
        severity=RiskLevel.HIGH,
    ),
    _PatternDef(
        regex=r"\bsudo\b",
        description="Privilege escalation via sudo",
        severity=RiskLevel.HIGH,
    ),
    _PatternDef(
        regex=r"\bimport\s+socket\b|\bfrom\s+socket\b|socket\.socket\(",
        description="Direct socket access",
        severity=RiskLevel.MEDIUM,
    ),
    _PatternDef(
        regex=r"\beval\s*\(|\bexec\s*\(",
        description="Dynamic code execution (eval/exec)",
        severity=RiskLevel.HIGH,
    ),
    _PatternDef(
        regex=r"\bos\.system\s*\(|\bsubprocess\.\w+\s*\(",
        description="Shell command execution",
        severity=RiskLevel.MEDIUM,
    ),
    _PatternDef(
        regex=r"\bchmod\s+[0-7]*7[0-7]*\b|\bchmod\s+\+[xs]",
        description="Permissive file permission change",
        severity=RiskLevel.MEDIUM,
    ),
    _PatternDef(
        regex=r">\s*/dev/s|/etc/passwd|/etc/shadow",
        description="Sensitive system file access",
        severity=RiskLevel.HIGH,
    ),
    _PatternDef(
        regex=r"\b(nc|ncat|netcat)\b\s+(-[a-z]*\s+)*-[a-z]*l",
        description="Network listener (netcat)",
        severity=RiskLevel.HIGH,
    ),
]

# Compile patterns once at import time
for _pd in _PATTERN_DEFS:
    _PATTERNS.append((re.compile(_pd.regex, re.IGNORECASE), _pd.description, _pd.severity))


class StaticAnalyzer:
    """Scans skill directories for dangerous patterns in scripts and markdown."""

    SCAN_EXTENSIONS = {".sh", ".bash", ".py", ".js", ".ts", ".rb", ".pl", ".md"}

    def scan_skill_dir(self, skill_dir: Path) -> list[StaticFinding]:
        """Scan all files in a skill directory for dangerous patterns."""
        findings: list[StaticFinding] = []
        if not skill_dir.exists():
            return findings

        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix not in self.SCAN_EXTENSIONS:
                continue
            try:
                content = file_path.read_text(errors="replace")
            except OSError:
                continue
            findings.extend(self._scan_content(content, str(file_path)))

        return findings

    def scan_text(self, text: str, source_label: str = "<inline>") -> list[StaticFinding]:
        """Scan a string of text for dangerous patterns."""
        return self._scan_content(text, source_label)

    def _scan_content(self, content: str, file_path: str) -> list[StaticFinding]:
        """Scan content line-by-line against all patterns."""
        findings: list[StaticFinding] = []
        for line_num, line in enumerate(content.splitlines(), start=1):
            for pattern, description, severity in _PATTERNS:
                match = pattern.search(line)
                if match:
                    findings.append(StaticFinding(
                        pattern=pattern.pattern,
                        description=description,
                        file_path=file_path,
                        line_number=line_num,
                        severity=severity,
                        matched_text=match.group(0),
                    ))
        return findings
