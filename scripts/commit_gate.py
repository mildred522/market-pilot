#!/usr/bin/env python3
"""Review staged changes before a commit.

The gate is intentionally dependency-free and only reads the Git index. It is
not an antivirus; it is a conservative repository hygiene and secret-leak
check that makes the staged scope visible before a commit is created.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
GATE_FILES = {
    ".githooks/pre-commit",
    "scripts/commit_gate.py",
    "scripts/install-git-hooks.sh",
}
ALLOWED_BINARY_SUFFIXES = {
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".ttf",
    ".webp",
    ".woff",
    ".woff2",
}
DATA_SUFFIXES = {".csv", ".tsv", ".jsonl", ".parquet", ".feather", ".xlsx", ".xls"}
PLACEHOLDER_MARKERS = (
    "example",
    "dummy",
    "fake",
    "local",
    "placeholder",
    "sample",
    "test",
    "your-",
    "change-me",
)


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    path: str
    detail: str


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("github_token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b")),
    ("provider_key", re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b")),
)
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)\b"
    r"\s*[:=]\s*[\"']([^\"']{16,})[\"']"
)
INTERNAL_ENDPOINT_PATTERN = re.compile(
    r"(?i)(?:https?://|git@)"
    r"(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
    r"[^/\s:@]+\.(?:corp|internal|intranet)(?::\d+)?)"
)
DOWNLOAD_PIPE_PATTERN = re.compile(
    r"(?i)\b(?:curl|wget)\b[^\n|]*\|\s*(?:sh|bash|zsh|python(?:3)?)\b"
)
DESTRUCTIVE_COMMAND_PATTERN = re.compile(
    r"(?im)(?:^|[;&|])\s*(?:rm\s+-rf\s+/(?:\s|$)|mkfs(?:\s|$)|dd\s+if=)"
)
OBFUSCATED_EXEC_PATTERN = re.compile(
    r"(?i)\b(?:base64\s+--?decode|openssl\s+enc)[^\n|]*\|\s*(?:sh|bash|zsh)\b"
)
CONFLICT_MARKER_PATTERN = re.compile(r"(?m)^(?:<<<<<<<|=======|>>>>>>>)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Review staged changes before commit")
    parser.add_argument(
        "--ci",
        action="store_true",
        help="fail on warnings instead of asking for interactive approval",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="ask for explicit approval when only warnings are present",
    )
    args = parser.parse_args()

    paths = _staged_paths()
    if not paths:
        print("[commit-gate] no staged changes; nothing to review")
        return 0

    findings = _review(paths)
    _print_report(paths, findings)

    errors = [finding for finding in findings if finding.severity == "ERROR"]
    warnings = [finding for finding in findings if finding.severity == "WARN"]
    if errors:
        print(f"[commit-gate] BLOCKED: {len(errors)} high-risk finding(s)")
        return 1
    if args.ci:
        if warnings:
            print(f"[commit-gate] BLOCKED in CI: {len(warnings)} review warning(s)")
            return 1
        print("[commit-gate] PASSED")
        return 0
    if warnings and (args.interactive or sys.stdin.isatty()):
        if _approve_interactively():
            print("[commit-gate] approved by operator")
            return 0
        print("[commit-gate] BLOCKED: operator did not approve the review")
        return 1
    if warnings:
        print("[commit-gate] BLOCKED: interactive approval is required")
        return 1

    print("[commit-gate] PASSED")
    return 0


def _staged_paths() -> list[str]:
    output = _git("diff", "--cached", "--name-only", "-z")
    return [path for path in output.decode("utf-8", errors="replace").split("\0") if path]


def _review(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    normalized_paths = {path.replace("\\", "/") for path in paths}
    if normalized_paths.intersection(GATE_FILES):
        findings.append(
            Finding(
                "WARN",
                "gate_files_changed",
                ", ".join(sorted(normalized_paths.intersection(GATE_FILES))),
                "commit-gate implementation changes require explicit human review before approval",
            )
        )

    roots = {path.split("/", 1)[0] for path in normalized_paths}
    if len(roots) >= 4:
        findings.append(
            Finding(
                "WARN",
                "broad_scope",
                "<commit>",
                "staged files span many top-level areas; confirm unrelated work is not mixed in",
            )
        )

    for path in sorted(normalized_paths):
        staged = _staged_blob(path)
        if staged is None:
            continue
        findings.extend(_review_path(path, staged))

    diff_check = subprocess.run(
        ["git", "diff", "--cached", "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if diff_check.returncode != 0:
        findings.append(
            Finding(
                "ERROR",
                "diff_check_failed",
                "<staged diff>",
                "Git whitespace/error check failed; run git diff --cached --check for details",
            )
        )
    return findings


def _review_path(path: str, content: bytes) -> list[Finding]:
    findings: list[Finding] = []
    lower_path = path.lower()
    suffix = Path(lower_path).suffix
    blocked_reason = _blocked_path_reason(lower_path)
    if blocked_reason:
        findings.append(Finding("ERROR", "sensitive_path", path, blocked_reason))
    if suffix in DATA_SUFFIXES:
        findings.append(
            Finding(
                "WARN",
                "data_file",
                path,
                "structured data file requires manual review for provenance, privacy, and internal-data leakage",
            )
        )

    if b"\x00" in content[:8192]:
        if suffix not in ALLOWED_BINARY_SUFFIXES:
            findings.append(
                Finding(
                    "ERROR",
                    "unreviewed_binary",
                    path,
                    "binary file type is not on the repository allowlist",
                )
            )
        return findings

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(
            Finding("ERROR", "unreviewed_binary", path, "file is not valid UTF-8 text")
        )
        return findings

    findings.extend(_review_text(path, text))
    return findings


def _review_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    for code, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(
                Finding("ERROR", code, path, f"high-confidence secret pattern near line {_line_number(text, match.start())}")
            )
    for match in ASSIGNMENT_PATTERN.finditer(text):
        value = match.group(1).lower()
        if not any(marker in value for marker in PLACEHOLDER_MARKERS):
            findings.append(
                Finding(
                    "ERROR",
                    "secret_assignment",
                    path,
                    f"credential-like literal near line {_line_number(text, match.start())}",
                )
            )
    for code, pattern, detail in (
        (
            "internal_endpoint",
            INTERNAL_ENDPOINT_PATTERN,
            "private or internal network endpoint found",
        ),
        (
            "download_pipe",
            DOWNLOAD_PIPE_PATTERN,
            "downloaded content is piped directly into an interpreter",
        ),
        (
            "destructive_command",
            DESTRUCTIVE_COMMAND_PATTERN,
            "destructive shell command pattern found",
        ),
        (
            "obfuscated_exec",
            OBFUSCATED_EXEC_PATTERN,
            "encoded content is piped into a shell",
        ),
        (
            "conflict_marker",
            CONFLICT_MARKER_PATTERN,
            "merge conflict marker found",
        ),
    ):
        match = pattern.search(text)
        if match:
            findings.append(
                Finding(
                    "ERROR",
                    code,
                    path,
                    f"{detail} near line {_line_number(text, match.start())}",
                )
            )
    return findings


def _blocked_path_reason(path: str) -> str | None:
    basename = Path(path).name
    if basename in {".env", ".env.local", ".env.production", ".env.development"}:
        return "environment file may contain credentials or local deployment secrets"
    if basename.startswith(".env.") and basename != ".env.example":
        return "non-example environment file may contain credentials"
    if any(part in {"data", "backups", "backup", "dumps", "storage"} for part in path.split("/")):
        return "data/storage/backup path requires explicit manual handling"
    if basename.lower() in {"credentials", "credentials.json", "secret.json", "secrets.json"}:
        return "credential-bearing filename is blocked"
    if Path(path).suffix.lower() in {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
        ".jks",
        ".keystore",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".log",
        ".dump",
        ".bak",
    }:
        return "private key, local database, log, or backup file is blocked"
    return None


def _staged_blob(path: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f":{path}"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _git(*args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _print_report(paths: list[str], findings: list[Finding]) -> None:
    print("[commit-gate] staged scope:")
    for path in sorted(paths):
        print(f"  - {path}")
    if not findings:
        print("[commit-gate] no security or scope findings")
        return
    print("[commit-gate] findings:")
    for finding in findings:
        print(f"  [{finding.severity}] {finding.code}: {finding.path} — {finding.detail}")


def _approve_interactively() -> bool:
    if os.getenv("COMMIT_GATE_APPROVED", "").strip() == "1":
        print("[commit-gate] approved via explicit COMMIT_GATE_APPROVED=1")
        return True
    try:
        with open("/dev/tty", encoding="utf-8") as terminal:
            terminal.write("[commit-gate] Review the staged scope above. Proceed? [y/N] ")
            terminal.flush()
            return terminal.readline().strip().lower() in {"y", "yes"}
    except OSError:
        return False


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as error:
        print(f"[commit-gate] ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
