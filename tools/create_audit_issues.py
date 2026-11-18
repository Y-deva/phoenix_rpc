"""Create GitHub issues from docs/AUDIT_ISSUES.md.

The project keeps its audit register in Markdown because the repository's
Issues tab was disabled when the audit was performed.  Once Issues is
enabled, run this script with a token that can create issues:

    GITHUB_TOKEN=... python tools/create_audit_issues.py --repo owner/name

The script is idempotent: issues whose titles already start with the audit
identifier are skipped.  It never prints the token.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "docs" / "AUDIT_ISSUES.md"
HEADING = re.compile(r"^### (AUD-[0-9]+)\. (.+)$")
SEVERITY = re.compile(r"^- С[её]рь[её]зность:\s*(.+)$", re.MULTILINE)
STATUS = re.compile(r"^- Статус:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class AuditIssue:
    """One parsed audit record."""

    identifier: str
    title: str
    severity: str
    status: str
    body: str


def parse_register(path: Path = REGISTER) -> list[AuditIssue]:
    """Parse audit records from the Markdown register."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"(?=^### AUD-[0-9]+\.)", text, flags=re.MULTILINE)
    issues: list[AuditIssue] = []
    for part in parts:
        match = HEADING.match(part.splitlines()[0]) if part.strip() else None
        if not match:
            continue
        identifier, title = match.groups()
        severity = SEVERITY.search(part)
        status = STATUS.search(part)
        body = part.split("\n", 1)[1].strip() if "\n" in part else ""
        issues.append(
            AuditIssue(
                identifier=identifier,
                title=title.strip(),
                severity=severity.group(1).strip() if severity else "unknown",
                status=status.group(1).strip() if status else "unknown",
                body=body,
            )
        )
    return issues


def issue_title(issue: AuditIssue) -> str:
    """Return the stable GitHub issue title."""
    return f"[{issue.identifier}] {issue.title}"


def existing_titles(session: requests.Session, api: str) -> set[str]:
    """Return all open and closed issue titles, paging the API."""
    titles: set[str] = set()
    page = 1
    while True:
        response = session.get(
            f"{api}/issues",
            params={"state": "all", "per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            return titles
        titles.update(str(item.get("title", "")) for item in batch)
        page += 1


def main(argv: list[str] | None = None) -> int:
    """Run the import command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument(
        "--apply", action="store_true", help="create issues; default is dry-run"
    )
    args = parser.parse_args(argv)
    issues = parse_register()
    print(f"Audit records: {len(issues)}")
    for issue in issues:
        print(f"  {issue.identifier}: {issue.title} ({issue.severity}, {issue.status})")
    if not args.apply:
        print("Dry run only; pass --apply to create issues.")
        return 0

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN is required for --apply.", file=sys.stderr)
        return 2
    api = f"https://api.github.com/repos/{args.repo}"
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    try:
        present = existing_titles(session, api)
        created = 0
        for issue in issues:
            title = issue_title(issue)
            if title in present:
                continue
            body = (
                f"**Audit:** {issue.identifier}\n\n"
                f"**Severity:** {issue.severity}\n\n"
                f"{issue.body}\n\n"
                "---\n"
                "Imported from `docs/AUDIT_ISSUES.md`."
            )
            response = session.post(
                f"{api}/issues",
                json={"title": title, "body": body},
                timeout=30,
            )
            if response.status_code == 410:
                print(
                    "GitHub Issues are disabled for this repository; "
                    "enable Settings -> Features -> Issues first.",
                    file=sys.stderr,
                )
                return 3
            response.raise_for_status()
            created += 1
            print(f"Created {response.json().get('html_url')}")
        print(f"Created {created} issue(s).")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
