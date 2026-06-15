#!/usr/bin/env python3
"""Generate docs/results.md from data/results/*.json.

Produces a results-by-date section and live group standings computed from the
completed matches. Everything under docs/ is generated -- do not edit by hand.

Usage: python3 scripts/generate_results.py
"""

import os

from common import (
    DOCS_DIR,
    GROUP_LETTERS,
    compute_standings,
    load_all_teams,
    load_results,
)


def team_name(by_slug, slug):
    t = by_slug.get(slug)
    return t["name"] if t else slug


def render_results_by_date(matches, by_slug):
    lines = ["## Results by date", ""]
    dates = []
    for m in matches:
        if m["date"] not in dates:
            dates.append(m["date"])
    for date in dates:
        day_matches = [m for m in matches if m["date"] == date]
        lines.append(f"### {date}")
        lines.append("")
        for m in day_matches:
            home = team_name(by_slug, m["home"])
            away = team_name(by_slug, m["away"])
            grp = f"Group {m['group']}" if m.get("group") else m.get("stage", "")
            if m.get("status") == "completed":
                line = f"- **{home} {m['home_score']}–{m['away_score']} {away}** ({grp})"
            else:
                line = f"- {home} vs {away} — _scheduled_ ({grp})"
            if m.get("venue"):
                line += f" — {m['venue']}"
            lines.append(line)
            if m.get("note"):
                lines.append(f"  - {m['note']}")
        lines.append("")
    return "\n".join(lines)


def render_standings(standings):
    lines = ["## Group standings", "", "_Computed from completed matches only._", ""]
    for letter in GROUP_LETTERS:
        rows = standings.get(letter, [])
        if not rows or all(r["played"] == 0 for r in rows):
            continue
        lines.append(f"### Group {letter}")
        lines.append("")
        lines.append("| Team | P | W | D | L | GF | GA | GD | Pts |")
        lines.append("|------|---|---|---|---|----|----|----|-----|")
        for r in rows:
            gd = f"{r['gd']:+d}" if r["gd"] != 0 else "0"
            lines.append(
                f"| {r['name']} | {r['played']} | {r['won']} | {r['drawn']} | "
                f"{r['lost']} | {r['gf']} | {r['ga']} | {gd} | {r['points']} |"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    matches = load_results()
    teams = load_all_teams()
    by_slug = {t["slug"]: t for t in teams}

    if not matches:
        print("No results found; skipping results.md.")
        return

    completed = [m for m in matches if m.get("status") == "completed"]
    lines = ["# Results", ""]
    lines.append(
        f"_{len(completed)} matches played across {len(matches)} listed fixtures._"
    )
    lines.append("")
    standings = compute_standings(teams, matches)
    lines.append(render_standings(standings))
    lines.append(render_results_by_date(matches, by_slug))

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "results.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Wrote docs/results.md ({len(completed)} completed matches).")


if __name__ == "__main__":
    main()
