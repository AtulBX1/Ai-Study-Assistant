"""Export accepted classic questions for manual review and score ratings."""

import argparse
import random
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "docs" / "results" / "quiz_quality.md"
SHEET_PATH = ROOT / "docs" / "results" / "quiz_rating_sheet.md"


def accepted_classic_questions(report: str) -> list[str]:
    """Read classic-engine accepted examples from the quality report."""
    in_classic = in_accepted = False
    rows = []
    for line in report.splitlines():
        if line == "## classic":
            in_classic = True
        elif line.startswith("## ") and line != "## classic":
            in_classic = False
        if not in_classic:
            continue
        if line == "### Accepted examples":
            in_accepted = True
        elif line.startswith("### "):
            in_accepted = False
        elif in_accepted and line.startswith("- p."):
            rows.append(line[2:])
    return rows


def export_sheet(report_path: Path = REPORT_PATH, sheet_path: Path = SHEET_PATH) -> int:
    """Write up to twenty randomized accepted classic questions."""
    candidates = accepted_classic_questions(report_path.read_text(encoding="utf-8"))
    selected = random.SystemRandom().sample(candidates, min(20, len(candidates)))
    lines = [
        "# Quiz question rating sheet",
        "",
        "Rate each question **good**, **ok**, or **bad**.",
        "",
        "| # | Question and answer | Rating (good / ok / bad) |",
        "|---:|---|---|",
    ]
    for index, item in enumerate(selected, start=1):
        escaped_item = item.replace("|", "\\|")
        lines.append(f"| {index} | {escaped_item} |  |")
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(selected)


def score_sheet(sheet_path: Path = SHEET_PATH) -> tuple[int, int, float | None]:
    """Return (good, rated, percent_good) for completed rating rows."""
    return score_ratings(sheet_path.read_text(encoding="utf-8"))


def score_ratings(markdown: str) -> tuple[int, int, float | None]:
    """Parse filled ratings and return (good, rated, percent_good)."""
    good = rated = 0
    for line in markdown.splitlines():
        if not line.startswith("|") or line.startswith("|---") or "Rating (" in line:
            continue
        cells = [
            cell.strip().casefold() for cell in line.strip("|").rsplit("|", maxsplit=2)
        ]
        if len(cells) < 3 or not cells[0].isdigit():
            continue
        rating = re.sub(r"\\([|\\])", r"\1", cells[2])
        if rating in {"good", "ok", "bad"}:
            rated += 1
            good += rating == "good"
    return good, rated, (100 * good / rated) if rated else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--score", action="store_true", help="read ratings from the sheet"
    )
    args = parser.parse_args()
    if args.score:
        good, rated, percentage = score_sheet()
        result = "not rated" if percentage is None else f"{percentage:.1f}% rated good"
        print(f"{good} good of {rated} rated questions ({result}).")
    else:
        count = export_sheet()
        print(f"Exported {count} questions to {SHEET_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
