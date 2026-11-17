"""Command line: python -m radar {full|catch-up|render-only|backlog} [options]."""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .common import utc_today
from .config import load_config
from .discover import GitHubSource
from .github_api import GitHubClient
from .pipeline import Paths, Report, backlog, run_catch_up, run_full, run_render
from .reviewer import Reviewer

TOKEN_WARNING_DAYS = 30


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m radar", description="Update the oss-radar directory.")
    parser.add_argument("mode", choices=("full", "catch-up", "render-only", "backlog"))
    parser.add_argument("--max-reviews", type=int, help="cap on Claude reviews this run (default: config)")
    parser.add_argument("--no-review", action="store_true", help="skip Claude reviews")
    parser.add_argument("--dry-run", action="store_true",
                        help="skip Claude and write into .dryrun/ instead of the repo")
    parser.add_argument("--out", type=Path, help="folder for data/, lists/ and README.md (default: the repo)")
    parser.add_argument("--include", action="append", default=[], metavar="OWNER/REPO",
                        help="catch-up: review these repos first")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = Path.cwd()
    cfg = load_config(root / "config.toml")
    paths = Paths(root, args.out or (root / ".dryrun" if args.dry_run else root))
    today = utc_today()

    if args.mode == "backlog":
        print(backlog(paths, cfg))
        return 0
    if args.mode == "render-only":
        report = run_render(paths, cfg, today)
    else:
        token = os.environ.get("RADAR_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            parser.error("set GITHUB_TOKEN (or RADAR_TOKEN) so the GitHub API can be used")
        source = GitHubSource(GitHubClient(token), cfg)
        reviewer = None
        if not (args.no_review or args.dry_run):
            rubric = (root / "prompts" / "review.md").read_text(encoding="utf-8")
            reviewer = Reviewer(rubric, model=cfg.review_model, effort=cfg.review_effort)
        limit = cfg.review_max_per_run if args.max_reviews is None else args.max_reviews
        if args.mode == "full":
            report = run_full(paths, cfg, source, reviewer, today, limit)
        else:
            report = run_catch_up(paths, cfg, source, reviewer, today, limit, args.include)
    _publish(report)
    return 0


def _publish(report: Report) -> None:
    """Log the run, and hand results to GitHub Actions when running there."""
    logging.info(
        "%s run: %d added, %d refreshed, %d gone, %d reviewed (%d kept, %d dropped), "
        "%d waiting, %d listed, %d GitHub points%s",
        report.mode, report.added, report.refreshed, report.gone, report.reviewed, report.kept,
        report.dropped, report.waiting, report.listed, report.github_points,
        f", reviews stopped: {report.review_stop}" if report.review_stop else "",
    )
    outputs = {
        "waiting": str(report.waiting),
        "reviewed": str(report.reviewed),
        "review_stop": report.review_stop or "",
        "claude_problem": report.review_stop if report.review_stop in ("auth", "setup") else "",
        "token_expires_soon": _expiring(report.credential_expires_at),
    }
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.writelines(f"{key}={value}\n" for key, value in outputs.items())
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        rows = [
            ("Found: new lane / traction lane", f"{report.found_new:,} / {report.found_traction:,}"),
            ("Added to tracking", f"{report.added:,}"),
            ("Refreshed / gone / frozen", f"{report.refreshed:,} / {report.gone:,} / {report.frozen:,}"),
            ("Reviewed (kept / dropped)", f"{report.reviewed:,} ({report.kept:,} / {report.dropped:,})"),
            ("Waiting for review", f"{report.waiting:,}"),
            ("Listed in total", f"{report.listed:,}"),
            ("GitHub API points used", f"{report.github_points:,}"),
            ("Claude calls", f"{report.claude_calls:,}"),
            ("Reviews stopped early", report.review_stop or "no"),
        ]
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### oss-radar {report.mode} run, {report.date}\n\n| | |\n|---|---|\n")
            fh.writelines(f"| {label} | {value} |\n" for label, value in rows)


def _expiring(expires_at: str | None) -> str:
    """The token's expiry date when it is within TOKEN_WARNING_DAYS, else ''."""
    if not expires_at:
        return ""
    try:
        when = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    soon = datetime.now(timezone.utc) + timedelta(days=TOKEN_WARNING_DAYS)
    return when.date().isoformat() if when <= soon else ""


if __name__ == "__main__":
    raise SystemExit(main())
