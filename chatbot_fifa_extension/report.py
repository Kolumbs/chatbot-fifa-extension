"""Generate a prediction-pool scoring report.

Writes a Markdown report always, and a PDF too if ``reportlab`` is installed.

Run it on the host (reads the live db path from your config; read-only):

    python -m chatbot_fifa_extension.report \
        --conf /home/juris/py-programs/kolumbs/conf.toml \
        --pdf report.pdf --md report.md [--exclude Name1,Name2] [--from 7]

--from N produces an "update" report: only matches from match #N onward are
detailed, and each player's total is split into a black "Before" baseline
(matches before #N) and a green "+Since #N" delta (matches from #N onward).

For PDF output install reportlab once:  pip install reportlab
(or install this package with the extra:  pip install -e ".[report]")
"""

import argparse
import tomllib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import fifa
from .context import build_context


SCORING = (
    "Scoring: 6 points for an exact score; 3 points for the correct outcome; "
    "on a match nobody predicted exactly, the closest correct prediction earns "
    "+2 (or +1 each if several tie)."
)
GREEN = "#1a7f37"


def _preds(player):
    return player.predictions if isinstance(player.predictions, dict) else {}


def _kickoff(match):
    try:
        moment = datetime.fromisoformat(match.kickoff)
    except (ValueError, TypeError):
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def _fmt_kickoff(match, tz=timezone.utc):
    """Format a match kickoff in the given timezone for display."""
    moment = _kickoff(match)
    if moment is None:
        return match.kickoff
    return moment.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")


def upcoming(ctx, exclude=(), hours=36):
    """Preview matches without a final result yet, up to `hours` ahead.

    Includes any match that has no result and kicks off before the horizon -
    so already-started matches still awaiting their result are not missed, as
    well as not-yet-played matches within the window. Returns
    [(match, [(name, pick), ...]), ...]. No scoring (results aren't in yet).
    """
    exclude = set(exclude)
    players = [
        p for p in sorted(ctx.store.get("player"), key=lambda p: p.name)
        if p.name not in exclude
    ]
    horizon = datetime.now(timezone.utc) + timedelta(hours=hours)
    rows = []
    for match in sorted(ctx.store.get("match"), key=lambda m: m.number):
        if match.result:
            continue
        moment = _kickoff(match)
        if moment is None or moment >= horizon:
            continue
        picks = []
        for player in players:
            pred = _preds(player).get(str(match.number))
            picks.append((player.name, f"{pred[0]}:{pred[1]}" if pred else "—"))
        rows.append((match, picks))
    return rows


def compute(ctx, exclude=(), since=None):
    """Score the store.

    Returns (ranking, before, delta, match_rows):
      ranking: player names sorted by grand total (before+delta), high to low.
      before:  {name: points from matches before #since} (all points if no since).
      delta:   {name: points from matches >= #since} (zeros if no since).
      match_rows: [(match, [(name, pick, note, points), ...]), ...] for every
        played+predicted match (the renderer filters by since for display).
    """
    exclude = set(exclude)
    players = [
        p for p in sorted(ctx.store.get("player"), key=lambda p: p.name)
        if p.name not in exclude
    ]
    matches = sorted(ctx.store.get("match"), key=lambda m: m.number)
    before = {p.name: 0 for p in players}
    delta = {p.name: 0 for p in players}
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
        is_since = since is not None and match.number >= since
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
            (delta if is_since else before)[player.name] += pts
            rows.append((player.name, pick, note, pts))
        match_rows.append((match, rows))
    ranking = sorted(before, key=lambda n: (-(before[n] + delta[n]), n))
    return ranking, before, delta, match_rows


def to_markdown(ranking, before, delta, match_rows, since=None,
                upcoming_rows=(), hours=36, tz=timezone.utc):
    """Render the report as Markdown text."""
    gen = datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")
    lines = ["# World Cup 2026 — Predictions",
             f"_Generated {gen}_", "", f"**{SCORING}**", "", "## Standings"]
    if since:
        lines += ["| # | Player | Total |", "|---|--------|------:|"]
        for i, n in enumerate(ranking, 1):
            total = before[n] + delta[n]
            cell = f"{total} +{delta[n]}" if delta[n] else f"{total}"
            lines.append(f"| {i} | {n} | {cell} |")
    else:
        lines += ["| # | Player | Points |", "|---|--------|-------:|"]
        for i, n in enumerate(ranking, 1):
            lines.append(f"| {i} | {n} | {before[n]} |")
    heading = "## Match-by-match" + (f" (from #{since})" if since else "")
    lines += ["", heading]
    for match, rows in match_rows:
        if since and match.number < since:
            continue
        lines.append(
            f"### #{match.number} {match.home} vs {match.away} - "
            f"actual {match.result[0]}:{match.result[1]}")
        lines += [f"_kickoff {_fmt_kickoff(match, tz)}_", "",
                  "| Player | Pick | Scoring | Points |",
                  "|--------|------|---------|-------:|"]
        for name, pick, note, pts in rows:
            lines.append(f"| {name} | {pick} | {note} | {pts} |")
        lines.append("")
    if upcoming_rows:
        lines += ["", "## Pending & upcoming - predictions preview"]
        for match, picks in upcoming_rows:
            lines.append(f"### #{match.number} {match.home} vs {match.away}")
            lines += [f"_kickoff {_fmt_kickoff(match, tz)}_", "", "| Player | Pick |",
                      "|--------|------|"]
            for name, pick in picks:
                lines.append(f"| {name} | {pick} |")
            lines.append("")
    return "\n".join(lines)


def to_pdf(ranking, before, delta, match_rows, since, path,
           upcoming_rows=(), hours=36, tz=timezone.utc):
    """Write the report as a styled PDF (requires reportlab)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    styles = getSampleStyleSheet()
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=11, leading=13)
    gen = datetime.now(tz).strftime("%Y-%m-%d %H:%M %Z")
    head, sub = colors.HexColor("#1f4e79"), colors.HexColor("#2e6da4")

    def styled(data, widths, colour, extra=()):
        table = Table(data, colWidths=widths, hAlign="LEFT")
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), colour),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#eef3f8")]),
        ]
        table.setStyle(TableStyle(style + list(extra)))
        return table

    el = [
        Paragraph("World Cup 2026 — Predictions", styles["Title"]),
        Paragraph(f"Generated {gen}", styles["Normal"]), Spacer(1, 0.3 * cm),
        Paragraph(SCORING, styles["Normal"]), Spacer(1, 0.4 * cm),
        Paragraph("Standings", styles["Heading2"]),
    ]
    if since:
        def total_cell(n):
            total = before[n] + delta[n]
            if delta[n]:
                return Paragraph(
                    f"{total} <font color='{GREEN}'>+{delta[n]}</font>", cell)
            return str(total)
        data = [["#", "Player", "Total"]] + [
            [str(i), n, total_cell(n)] for i, n in enumerate(ranking, 1)]
        el.append(styled(data, [1.2 * cm, 8.6 * cm, 4 * cm], head))
    else:
        data = [["#", "Player", "Points"]] + [
            [str(i), n, str(before[n])] for i, n in enumerate(ranking, 1)]
        el.append(styled(data, [1.2 * cm, 8.6 * cm, 4 * cm], head))
    title = "Match-by-match" + (f" (from #{since})" if since else "")
    el += [Spacer(1, 0.5 * cm), Paragraph(title, styles["Heading2"])]
    for match, rows in match_rows:
        if since and match.number < since:
            continue
        el.append(Spacer(1, 0.2 * cm))
        el.append(Paragraph(
            f"#{match.number} {match.home} vs {match.away} — "
            f"actual {match.result[0]}:{match.result[1]} "
            f"<font size=9 color=grey>({_fmt_kickoff(match, tz)})</font>",
            styles["Heading4"]))
        el.append(styled([["Player", "Pick", "Scoring", "Pts"]] +
                         [[n, pk, nt, str(pt)] for n, pk, nt, pt in rows],
                         [3.5 * cm, 2 * cm, 6.5 * cm, 1.8 * cm], sub))
    if upcoming_rows:
        amber = colors.HexColor("#9c6500")
        el += [Spacer(1, 0.5 * cm),
               Paragraph("Pending & upcoming — predictions preview",
                         styles["Heading2"])]
        for match, picks in upcoming_rows:
            el.append(Spacer(1, 0.2 * cm))
            el.append(Paragraph(
                f"#{match.number} {match.home} vs {match.away} "
                f"<font size=9 color=grey>(kickoff {_fmt_kickoff(match, tz)})</font>",
                styles["Heading4"]))
            el.append(styled([["Player", "Pick"]] + [[n, pk] for n, pk in picks],
                             [9.2 * cm, 4.6 * cm], amber))
    SimpleDocTemplate(path, pagesize=(15 * cm, A4[1]),
                      leftMargin=0.6 * cm, rightMargin=0.6 * cm,
                      topMargin=0.6 * cm, bottomMargin=0.6 * cm,
                      title="World Cup 2026 — Predictions").build(el)


def main(argv=None):
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Generate the FIFA prediction-pool report.")
    parser.add_argument(
        "--db", default=".",
        help="Directory holding the membank 'db' file (default: current dir).")
    parser.add_argument(
        "--conf", default=None,
        help="Read the database path from this conf.toml instead of --db.")
    parser.add_argument("--pdf", default="report.pdf",
                        help="Output PDF path (skipped if reportlab missing).")
    parser.add_argument("--md", default=None,
                        help="Optional Markdown output path (off by default).")
    parser.add_argument("--tz", default=None,
                        help="Timezone for displayed kickoff times, e.g. "
                        "Europe/Riga (default UTC).")
    parser.add_argument("--exclude", default="",
                        help="Comma-separated player names to leave out.")
    parser.add_argument(
        "--from", dest="since", type=int, default=None,
        help="Update mode: detail only matches from this match number onward, "
        "and split standings into Before (black) + Since (green).")
    parser.add_argument(
        "--upcoming", type=int, default=36,
        help="Hours ahead to preview not-yet-played matches' predictions "
        "(default 36; 0 to disable).")
    args = parser.parse_args(argv)

    tz = timezone.utc
    if args.tz:
        try:
            tz = ZoneInfo(args.tz)
        except Exception:
            print(f"Unknown timezone '{args.tz}', using UTC.")

    if args.conf:
        with open(args.conf, "rb") as handle:
            database_path = tomllib.load(handle)["chatbot_fifa_extension"]["database_path"]
    else:
        database_path = args.db
    ctx = build_context({"database_path": database_path})
    exclude = [x.strip() for x in args.exclude.split(",") if x.strip()]
    ranking, before, delta, match_rows = compute(ctx, exclude, args.since)
    upcoming_rows = upcoming(ctx, exclude, args.upcoming) if args.upcoming else []

    if args.md:
        with open(args.md, "w", encoding="utf-8") as handle:
            handle.write(to_markdown(ranking, before, delta, match_rows,
                                     args.since, upcoming_rows, args.upcoming, tz))
        print(f"Wrote {args.md}")
    try:
        to_pdf(ranking, before, delta, match_rows, args.since, args.pdf,
               upcoming_rows, args.upcoming, tz)
        print(f"Wrote {args.pdf}")
    except ImportError:
        print("reportlab not installed - PDF skipped. Install: pip install reportlab")

    print("\nStandings:")
    for i, n in enumerate(ranking, 1):
        total = before[n] + delta[n]
        extra = f"  (before {before[n]} + since {delta[n]})" if args.since else ""
        print(f"  {i}. {n} - {total}{extra}")


if __name__ == "__main__":
    main()
