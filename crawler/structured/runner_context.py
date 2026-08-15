"""Shared season path derivation for production Structured runners."""

from __future__ import annotations

from pathlib import Path

from crawler.season_context import DEFAULT_SEASON, SeasonContext


def runner_context(
    repo: Path,
    season: str,
    output_root: Path,
    report_path: Path,
    default_output: Path,
    default_report: Path,
) -> tuple[SeasonContext, Path, Path]:
    context = SeasonContext(repo, season)
    output = context.structured_root if output_root == default_output else output_root
    report = (
        context.report_root / default_report.name
        if report_path == default_report and season != DEFAULT_SEASON
        else report_path
    )
    return context, output, report
