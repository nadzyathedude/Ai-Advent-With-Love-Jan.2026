"""Style rule checking on unified diffs — pattern-based with docs context."""

import re
from typing import Dict, List, Any

from .review_state import ReviewFinding


# Each pattern: (regex, severity, message, suggestion)
STYLE_PATTERNS = [
    (
        r"^\+.{121,}$",
        "low",
        "Line exceeds 120 characters",
        "Break the line to stay within 120 characters",
    ),
    (
        r"^\+.*[ \t]+$",
        "low",
        "Trailing whitespace detected",
        "Remove trailing whitespace",
    ),
    (
        r"^\+.*\t.*  |^\+.*  .*\t",
        "medium",
        "Mixed tabs and spaces for indentation",
        "Use consistent indentation — prefer spaces (PEP 8)",
    ),
    (
        r"^\+\s*from\s+\S+\s+import\s+\*",
        "medium",
        "Wildcard import pollutes namespace",
        "Import only the specific names you need",
    ),
    (
        r"^\+\s*#\s*(TODO|FIXME|HACK|XXX)\b",
        "low",
        "TODO/FIXME/HACK comment found in new code",
        "Resolve the issue or create a tracked ticket instead",
    ),
    (
        r"^\+\s*def\s+[a-z]+[A-Z]",
        "medium",
        "Function name uses mixedCase instead of snake_case",
        "Rename to snake_case per PEP 8 naming conventions",
    ),
    (
        r"^\+\s*[a-z]+[A-Z]\w*\s*=",
        "low",
        "Variable name uses mixedCase instead of snake_case",
        "Rename to snake_case per PEP 8 naming conventions",
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


def _check_missing_docstrings(diff: str) -> List[ReviewFinding]:
    """Check for public function definitions without docstrings."""
    findings: List[ReviewFinding] = []
    lines = diff.split("\n")

    for i, line in enumerate(lines):
        if not re.match(r"^\+\s*def\s+[a-z]", line):
            continue
        # Skip private/protected functions
        func_match = re.search(r"def\s+(_+\w+|__\w+__)", line)
        if func_match and func_match.group(1).startswith("_"):
            continue
        # Check if next non-empty added line is a docstring
        has_docstring = False
        for j in range(i + 1, min(i + 5, len(lines))):
            next_line = lines[j]
            if next_line.startswith("-") or next_line.strip() == "":
                continue
            if next_line.startswith("+") and ('"""' in next_line or "'''" in next_line):
                has_docstring = True
            break
        if not has_docstring:
            file_path, line_num = _extract_file_and_line(diff, diff.find(line))
            findings.append(ReviewFinding(
                category="style",
                severity="low",
                file_path=file_path,
                line=line_num,
                message="Public function missing docstring",
                suggestion="Add a docstring describing the function's purpose",
            ))

    return findings


def _check_docs_conventions(diff: str, docs_context: List[Dict[str, Any]]) -> List[ReviewFinding]:
    """Cross-reference diff against project documentation conventions."""
    findings: List[ReviewFinding] = []
    if not docs_context:
        return findings

    # Combine docs text to search for convention keywords
    docs_text = " ".join(d.get("text", "") for d in docs_context).lower()

    # If docs mention snake_case and diff has camelCase
    if "snake_case" in docs_text or "snake case" in docs_text:
        for match in re.finditer(r"^\+\s*def\s+[a-z]+[A-Z]", diff, re.MULTILINE):
            file_path, line_num = _extract_file_and_line(diff, match.start())
            findings.append(ReviewFinding(
                category="style",
                severity="medium",
                file_path=file_path,
                line=line_num,
                message="Function name violates project snake_case convention (per docs)",
                suggestion="Rename to snake_case as documented in project style guide",
            ))

    return findings


def analyze_style(diff: str, docs_context: List[Dict[str, Any]] = None) -> List[ReviewFinding]:
    """Scan a unified diff for style violations."""
    if docs_context is None:
        docs_context = []

    findings: List[ReviewFinding] = []

    for pattern, severity, message, suggestion in STYLE_PATTERNS:
        for match in re.finditer(pattern, diff, re.MULTILINE):
            file_path, line_num = _extract_file_and_line(diff, match.start())
            findings.append(ReviewFinding(
                category="style",
                severity=severity,
                file_path=file_path,
                line=line_num,
                message=message,
                suggestion=suggestion,
            ))

    findings.extend(_check_missing_docstrings(diff))
    findings.extend(_check_docs_conventions(diff, docs_context))
    return findings
