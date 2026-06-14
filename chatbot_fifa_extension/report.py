"""Generate a prediction-pool scoring report.

Writes a Markdown report always, and a PDF too if ``reportlab`` is installed.

Run it on the host (reads the live db path from your config; read-only):

    python -m chatbot_fifa_extension.report \
        --conf /home/juris/py-programs/kolumbs/conf.toml \
        --pdf report.pdf --md report.md [--exclude Name1,Name2]

For PDF output install reportlab once:  pip install reportlab
(or install this package with the extra:  pip install -e ".[report]")
"""

import argparse
import tomllib
from datetime import datetime, timezone

from . import fifa
from .context import build_context


SCORING = (
    "Scoring: 6 points for an exact score; 3 points for the correct outcome; "
    "on a match nobody predicted exactly, the closest correct prediction earns "
    "+2 (or +1 each if several tie)."
)


def _preds(player):
    return player.predictions if isinstance(player.predictions, dict) else {}


def compute(ctx, exclude=()):
    """Return (ranking, match_rows) scored from the store.

    ranking: list of (name, points) sorted high-to-low.
    match_rows: list of (match, [(name, pick, note, points), ...]) for each
        played match that at least one (included) player predicted.
    """
    exclude = set(exclude)
    players = [
        p for p in sorted(ctx.store.get("player"), key=lambda p: p.name)
        if p.name not in exclude
    ]
    matches = sorted(ctx.store.get("match"), key=lambda m: m.number)
    totals = {p.name: 0 for p in players}
    match_rows = []
    for match in matches:
        if not match.result:
            continue
        if all(_preds(p).get(str(match.number)) is None for p in players):
            continue
        info = {}
        perfect = False
        for player in players:
            pred = _preds(player).get(str(match.number))
            if not pred:
                info[player.name] = (None, None, None)
                continue
            correct, diff = fifa.get_score_bet(match.result, pred)
            info[player.name] = (pred, correct, diff)
            if correct and diff == 0:
                perfect = True
        cands = [(n, d) for n, (pr, c, d) in info.items() if pr and c and d > 0]
        closest = []
        if cands:
            mind = min(d for _, d in cands)
            closest = [n for n, d in cands if d == mind]
        rows = []
        for player in players:
            pred, correct, diff = info[player.name]
            if not pred:
                rows.append((player.name, "—", "no pick", 0))
                continue
            pick = f"{pred[0]}:{pred[1]}"
            if correct and diff == 0:
                pts, note = 6, "exact score"
            elif correct:
                pts, note = 3, "correct outcome"
                if not perfect and player.name in closest:
                    bonus = 2 if len(closest) == 1 else 1
                    pts += bonus
                    note += f" +{bonus} (closest)"
            else:
                pts, note = 0, "wrong"
            totals[player.name] += pts
            rows.append((player.name, pick, note, pts))
        match_rows.append((match, rows))
    ranking = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranking, match_rows


def to_markdown(ranking, match_rows):
    """Render the report as Markdown text."""
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# FIFA World Cup 2026 - Prediction Pool Report",
        f"_Generated {gen}_", "", f"**{SCORING}**", "",
        "## Standings", "| # | Player | Points |", "|---|--------|-------:|",
    ]
    for i, (name, pts) in enumerate(ranking, 1):
        lines.append(f"| {i} | {name} | {pts} |")
    lines += ["", "## Match-by-match"]
    for match, rows in match_rows:
        lines.append(
            f"### #{match.number} {match.home} vs {match.away} - "
            f"actual {match.result[0]}:{match.result[1]}"
        )
        lines += [f"_kickoff {match.kickoff}_", "",
                  "| Player | Pick | Scoring | Points |",
                  "|--------|------|---------|-------:|"]
        for name, pick, note, pts in rows:
            lines.append(f"| {name} | {pick} | {note} | {pts} |")
        lines.append("")
    return "\n".join(lines)


def to_pdf(ranking, match_rows, path):
    """Write the report as a styled PDF (requires reportlab)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet

    styles = getSampleStyleSheet()
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    head, sub = colors.HexColor("#1f4e79"), colors.HexColor("#2e6da4")

    def styled(data, widths, colour):
        table = Table(data, colWidths=widths, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colour),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#eef3f8")]),
        ]))
        return table

    el = [
        Paragraph("FIFA World Cup 2026 — Prediction Pool Report", styles["Title"]),
        Paragraph(f"Generated {gen}", styles["Normal"]), Spacer(1, 0.3 * cm),
        Paragraph(SCORING, styles["Normal"]), Spacer(1, 0.4 * cm),
        Paragraph("Standings", styles["Heading2"]),
        styled([["#", "Player", "Points"]] +
               [[str(i), n, str(p)] for i, (n, p) in enumerate(ranking, 1)],
               [1.2 * cm, 6 * cm, 2.5 * cm], head),
        Spacer(1, 0.5 * cm), Paragraph("Match-by-match", styles["Heading2"]),
    ]
    for match, rows in match_rows:
        el.append(Spacer(1, 0.2 * cm))
        el.append(Paragraph(
            f"#{match.number} {match.home} vs {match.away} — "
            f"actual {match.result[0]}:{match.result[1]} "
            f"<font size=8 color=grey>({match.kickoff})</font>",
            styles["Heading4"]))
        el.append(styled([["Player", "Pick", "Scoring", "Pts"]] +
                         [[n, pk, nt, str(pt)] for n, pk, nt, pt in rows],
                         [4 * cm, 2 * cm, 7 * cm, 1.3 * cm], sub))
    SimpleDocTemplate(path, pagesize=A4,
                      title="WC2026 Prediction Pool Report").build(el)


def main(argv=None):
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Generate the FIFA prediction-pool report.")
    parser.add_argument(
        "--db", default=".",
        help="Directory holding the membank 'db' file (default: current dir, "
        "i.e. drop the refreshed db at the repo root and run from there).")
    parser.add_argument(
        "--conf", default=None,
        help="Read the database path from this conf.toml instead of --db.")
    parser.add_argument("--pdf", default="report.pdf",
                        help="Output PDF path (skipped if reportlab missing).")
    parser.add_argument("--md", default="report.md", help="Markdown output path.")
    parser.add_argument("--exclude", default="",
                        help="Comma-separated player names to leave out.")
    args = parser.parse_args(argv)

    if args.conf:
        with open(args.conf, "rb") as handle:
            database_path = tomllib.load(handle)["chatbot_fifa_extension"]["database_path"]
    else:
        database_path = args.db
    ctx = build_context({"database_path": database_path})
    exclude = [x.strip() for x in args.exclude.split(",") if x.strip()]
    ranking, match_rows = compute(ctx, exclude)

    if args.md:
        with open(args.md, "w", encoding="utf-8") as handle:
            handle.write(to_markdown(ranking, match_rows))
        print(f"Wrote {args.md}")
    try:
        to_pdf(ranking, match_rows, args.pdf)
        print(f"Wrote {args.pdf}")
    except ImportError:
        print("reportlab not installed - PDF skipped. Install: pip install reportlab")

    print("\nStandings:")
    for i, (name, pts) in enumerate(ranking, 1):
        print(f"  {i}. {name} - {pts}")


if __name__ == "__main__":
    main()
