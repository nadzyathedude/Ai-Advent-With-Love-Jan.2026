"""Bug pattern detection on unified diffs — pure heuristic, no AI."""

import re
from typing import List

from .review_state import ReviewFinding

# Each pattern: (regex, severity, message, suggestion)
BUG_PATTERNS = [
    (
        r"^\+.*\bexcept\s*:",
        "high",
        "Bare except clause catches all exceptions including KeyboardInterrupt and SystemExit",
        "Use 'except Exception:' or a more specific exception type",
    ),
    (
        r"^\+.*==\s*None",
        "medium",
        "Comparison to None using == instead of 'is'",
        "Use 'is None' instead of '== None' (PEP 8)",
    ),
    (
        r"^\+.*!=\s*None",
        "medium",
        "Comparison to None using != instead of 'is not'",
        "Use 'is not None' instead of '!= None' (PEP 8)",
    ),
    (
        r"^\+.*def\s+\w+\(.*=\s*\[\]",
        "high",
        "Mutable default argument (list) — shared across calls",
        "Use 'None' as default and initialize inside the function body",
    ),
    (
        r"^\+.*def\s+\w+\(.*=\s*\{\}",
        "high",
        "Mutable default argument (dict) — shared across calls",
        "Use 'None' as default and initialize inside the function body",
    ),
    (
        r"^\+.*\b/\s*0\b",
        "high",
        "Potential division by zero",
        "Add a zero check before dividing",
    ),
    (
        r"^\+.*\.close\(\)",
        "low",
        "Manual resource close — may not execute on exception",
        "Consider using a 'with' statement (context manager) instead",
    ),
    (
        r"^\+.*\brange\(len\(",
        "low",
        "range(len(...)) pattern — often indicates C-style loop",
        "Consider using enumerate() or iterating directly over the collection",
    ),
    (
        r"^\+.*\bType[Ee]rror\b.*\bexcept\b|\bexcept\b.*\bType[Ee]rror\b",
        "low",
        "Catching TypeError may hide real type bugs",
        "Ensure TypeError handling is intentional and not masking a code issue",
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
            # Parse @@ -a,b +c,d @@ to get the starting line in new file
            hunk = re.search(r"\+(\d+)", line)
            if hunk:
                hunk_start = int(hunk.group(1))
                # Count added/context lines from hunk header to match
                count = 0
                idx = diff[:match_pos].rfind(line) + len(line)
                for subsequent in diff[idx:match_pos].split("\n"):
                    if subsequent and not subsequent.startswith("-"):
                        count += 1
                line_num = hunk_start + count - 1
        if file_path != "unknown" and line_num is not None:
            break

    return file_path, line_num


def analyze_for_bugs(diff: str) -> List[ReviewFinding]:
    """Scan a unified diff for common bug patterns."""
    findings: List[ReviewFinding] = []

    for pattern, severity, message, suggestion in BUG_PATTERNS:
        for match in re.finditer(pattern, diff, re.MULTILINE):
            file_path, line_num = _extract_file_and_line(diff, match.start())
            findings.append(ReviewFinding(
                category="bug",
                severity=severity,
                file_path=file_path,
                line=line_num,
                message=message,
                suggestion=suggestion,
            ))

    return findings
