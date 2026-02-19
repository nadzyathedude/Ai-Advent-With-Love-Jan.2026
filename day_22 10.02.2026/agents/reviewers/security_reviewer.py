"""Security pattern scanning on unified diffs — detects common vulnerabilities."""

import re
from typing import List

from .review_state import ReviewFinding

# Each pattern: (regex, severity, message, suggestion)
SECURITY_PATTERNS = [
    (
        r"^\+.*\beval\s*\(",
        "high",
        "Use of eval() — allows arbitrary code execution",
        "Replace eval() with a safe alternative (ast.literal_eval, json.loads, etc.)",
    ),
    (
        r"^\+.*\bexec\s*\(",
        "high",
        "Use of exec() — allows arbitrary code execution",
        "Avoid exec(); use safer alternatives or refactor the logic",
    ),
    (
        r"^\+.*\bos\.system\s*\(",
        "high",
        "os.system() is vulnerable to shell injection",
        "Use subprocess.run() with a list of arguments instead",
    ),
    (
        r"^\+.*subprocess\.\w+\(.*shell\s*=\s*True",
        "high",
        "subprocess with shell=True is vulnerable to shell injection",
        "Use shell=False (default) with a list of arguments",
    ),
    (
        r"^\+.*\bpickle\.loads?\s*\(",
        "high",
        "pickle.load/loads can execute arbitrary code on untrusted data",
        "Use json or a safe serialization format for untrusted data",
    ),
    (
        r'^\+.*(?:password|passwd|secret|api_key|apikey|token|auth)\s*=\s*["\'][^"\']{4,}["\']',
        "high",
        "Possible hardcoded secret or credential",
        "Move secrets to environment variables or a secrets manager",
    ),
    (
        r"^\+.*(?:PASSWORD|SECRET|API_KEY|TOKEN)\s*=\s*[\"'][^\"']{4,}[\"']",
        "high",
        "Hardcoded secret in uppercase constant",
        "Use environment variables (os.environ) or a secrets manager",
    ),
    (
        r'^\+.*["\']http://(?!localhost|127\.0\.0\.1|0\.0\.0\.0)',
        "medium",
        "HTTP URL used where HTTPS may be expected",
        "Use HTTPS for secure communication",
    ),
    (
        r"^\+.*\bf[\"'].*\{.*\}.*(?:SELECT|INSERT|UPDATE|DELETE|DROP)",
        "high",
        "Possible SQL injection via f-string formatting",
        "Use parameterized queries instead of string formatting",
    ),
    (
        r'^\+.*(?:format|%)\s*.*(?:SELECT|INSERT|UPDATE|DELETE|DROP)',
        "high",
        "Possible SQL injection via string formatting",
        "Use parameterized queries instead of string formatting",
    ),
    (
        r"^\+.*\byaml\.load\s*\(",
        "medium",
        "yaml.load() without Loader is unsafe — can execute arbitrary Python",
        "Use yaml.safe_load() instead",
    ),
    (
        r"^\+.*verify\s*=\s*False",
        "medium",
        "SSL verification disabled — vulnerable to MITM attacks",
        "Enable SSL verification or handle certificates properly",
    ),
]


def _extract_file_and_line(diff: str, match_pos: int) -> tuple:
    """Walk backwards from a match position to find the current file and line."""
    lines_before = diff[:match_pos].split("\n")
    file_path = "unknown"
    line_num = None

    for line in reversed(lines_before):
        if line.startswith("+++ b/") and file_path == "unknown":
            file_path = line[6:]
        if line.startswith("@@") and line_num is None:
            hunk = re.search(r"\+(\d+)", line)
            if hunk:
                hunk_start = int(hunk.group(1))
                count = 0
                idx = diff[:match_pos].rfind(line) + len(line)
                for subsequent in diff[idx:match_pos].split("\n"):
                    if subsequent and not subsequent.startswith("-"):
                        count += 1
                line_num = hunk_start + count - 1
        if file_path != "unknown" and line_num is not None:
            break

    return file_path, line_num


def analyze_security(diff: str) -> List[ReviewFinding]:
    """Scan a unified diff for security vulnerabilities."""
    findings: List[ReviewFinding] = []

    for pattern, severity, message, suggestion in SECURITY_PATTERNS:
        for match in re.finditer(pattern, diff, re.MULTILINE | re.IGNORECASE):
            file_path, line_num = _extract_file_and_line(diff, match.start())
            findings.append(ReviewFinding(
                category="security",
                severity=severity,
                file_path=file_path,
                line=line_num,
                message=message,
                suggestion=suggestion,
            ))

    return findings
