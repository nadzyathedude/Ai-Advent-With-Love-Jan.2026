"""Performance anti-pattern detection on unified diffs."""

import re
from typing import List

from .review_state import ReviewFinding

# Each pattern: (regex, severity, message, suggestion)
PERFORMANCE_PATTERNS = [
    (
        r"^\+.*\bfor\b.*\bfor\b",
        "medium",
        "Nested loop detected — potential O(n^2) or worse complexity",
        "Consider using a set/dict for lookup, or restructure the algorithm",
    ),
    (
        r'^\+.*\+\s*=\s*["\']|^\+.*=.*\+\s*["\'].*\bfor\b',
        "medium",
        "String concatenation with + in possible loop context",
        "Use str.join(), io.StringIO, or f-strings for building strings",
    ),
    (
        r"^\+.*\.readlines\s*\(\)",
        "low",
        ".readlines() loads entire file into memory",
        "Iterate over the file object directly: 'for line in f:'",
    ),
    (
        r"^\+.*\bimport\s+pandas\b",
        "low",
        "Import of heavy module (pandas) — slow startup if at module level",
        "Consider lazy import inside the function that uses it",
    ),
    (
        r"^\+.*\bimport\s+numpy\b",
        "low",
        "Import of heavy module (numpy) — slow startup if at module level",
        "Consider lazy import inside the function that uses it",
    ),
    (
        r"^\+.*\bimport\s+tensorflow\b",
        "low",
        "Import of heavy module (tensorflow) — slow startup if at module level",
        "Consider lazy import inside the function that uses it",
    ),
    (
        r"^\+.*\bimport\s+torch\b",
        "low",
        "Import of heavy module (torch) — slow startup if at module level",
        "Consider lazy import inside the function that uses it",
    ),
    (
        r"^\+.*\btime\.sleep\s*\(",
        "medium",
        "Synchronous sleep blocks the thread",
        "In async code, use 'await asyncio.sleep()'; otherwise ensure blocking is intentional",
    ),
    (
        r"^\+.*\bglob\.glob\s*\(.*\*\*",
        "low",
        "Recursive glob can be slow on large directory trees",
        "Consider limiting depth or using os.scandir() for better performance",
    ),
    (
        r"^\+.*\bin\s+list\(",
        "low",
        "'in list(...)' converts to list before searching — O(n)",
        "Use 'in set(...)' for O(1) lookups, or iterate directly",
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


def analyze_performance(diff: str) -> List[ReviewFinding]:
    """Scan a unified diff for performance anti-patterns."""
    findings: List[ReviewFinding] = []

    for pattern, severity, message, suggestion in PERFORMANCE_PATTERNS:
        for match in re.finditer(pattern, diff, re.MULTILINE):
            file_path, line_num = _extract_file_and_line(diff, match.start())
            findings.append(ReviewFinding(
                category="performance",
                severity=severity,
                file_path=file_path,
                line=line_num,
                message=message,
                suggestion=suggestion,
            ))

    return findings
