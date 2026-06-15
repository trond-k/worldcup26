#!/usr/bin/env python3
"""Generate docs/results.md from data/results/*.json and data/results/matches/*.json.

Produces live group standings (from completed matches) and, for each match,
the score plus — where a match-detail file exists — goals, lineups,
substitutions, cards and team statistics. Everything under docs/ is generated;
do not edit by hand.

Usage: python3 scripts/generate_results.py
"""

import os

from common import (
    CARD_ICON,
    DOCS_DIR,
    GROUP_LETTERS,
    STAT_LABELS,
    compute_standings,
    load_all_teams,
    load_match_details,
    load_results,
    minute_key,
    team_name,
)


def render_goals(detail, by_slug):
    goals = sorted(detail.get("goals", []), key=lambda g: minute_key(g.get("minute")))
    if not goals:
        return ""
    parts = []
    for g in goals:
        tag = ""
        if g.get("type") == "penalty":
            tag = " (pen)"
        elif g.get("type") == "own_goal":
            tag = " (OG)"
        minute = f"{g['minute']}'" if g.get("minute") else "?"
        team = team_name(by_slug, g.get("team"))
        parts.append(f"{minute} {g.get('player')}{tag} ({team})")
    return "**Goals:** " + "; ".join(parts)


def render_lineup(detail, side_key, slug, by_slug):
    lu = (detail.get("lineups") or {}).get(side_key)
    if not lu:
        return None
    header = f"**{team_name(by_slug, slug)}**"
    bits = []
    if lu.get("formation"):
        bits.append(lu["formation"])
    if lu.get("manager"):
        bits.append(lu["manager"])
    if bits:
        header += f" ({' — '.join(bits)})"
    names = []
    for p in lu.get("starting", []):
        n = p.get("name", "")
        if p.get("number"):
            n = f"{p['number']}. {n}"
        names.append(n)
    return f"{header}: " + ", ".join(names) if names else header


def render_subs(detail, by_slug):
    subs = sorted(detail.get("substitutions", []), key=lambda s: minute_key(s.get("minute")))
    if not subs:
        return ""
    parts = []
    for s in subs:
        minute = f"{s['minute']}'" if s.get("minute") else "?"
        team = team_name(by_slug, s.get("team"))
        off = s.get("off") or "?"
        on = s.get("on") or "?"
        parts.append(f"{minute} {off} → {on} ({team})")
    return "**Substitutions:** " + "; ".join(parts)


def render_cards(detail, by_slug):
    cards = sorted(detail.get("cards", []), key=lambda c: minute_key(c.get("minute")))
    if not cards:
        return ""
    parts = []
    for c in cards:
        icon = CARD_ICON.get(c.get("card"), "")
        minute = f"{c['minute']}'" if c.get("minute") else "?"
        team = team_name(by_slug, c.get("team"))
        parts.append(f"{icon} {minute} {c.get('player')} ({team})")
    return "**Cards:** " + "; ".join(parts)


def render_stats_table(detail, home, away, by_slug):
    stats = detail.get("stats") or {}
    hs, as_ = stats.get("home") or {}, stats.get("away") or {}
    rows = []
    for key, label, unit in STAT_LABELS:
        hv, av = hs.get(key), as_.get(key)
        if hv is None and av is None:
            continue
        fmt = lambda v: "—" if v is None else f"{v}{unit}"
        rows.append(f"| {label} | {fmt(hv)} | {fmt(av)} |")
    if not rows:
        return ""
    head = (
        f"| Stat | {team_name(by_slug, home)} | {team_name(by_slug, away)} |\n"
        "|------|---|---|"
    )
    return head + "\n" + "\n".join(rows)


def render_match(m, detail, by_slug):
    home, away = m["home"], m["away"]
    grp = f"Group {m['group']}" if m.get("group") else m.get("stage", "")
    lines = [f"#### {team_name(by_slug, home)} {m['home_score']}–{m['away_score']} "
             f"{team_name(by_slug, away)} ({grp})"]
    meta = []
    if m.get("venue"):
        meta.append(f"_{m['venue']}_")
    if detail and detail.get("attendance"):
        meta.append(f"Att: {detail['attendance']:,}")
    if detail and detail.get("referee"):
        meta.append(f"Referee: {detail['referee']}")
    if meta:
        lines.append(" · ".join(meta))
    lines.append("")

    if detail:
        goals = render_goals(detail, by_slug)
        if goals:
            lines.append(goals)
            lines.append("")
        inner = []
        for side_key, slug in (("home", home), ("away", away)):
            lu = render_lineup(detail, side_key, slug, by_slug)
            if lu:
                inner.append(lu)
                inner.append("")
        for block in (render_subs(detail, by_slug), render_cards(detail, by_slug)):
            if block:
                inner.append(block)
                inner.append("")
        table = render_stats_table(detail, home, away, by_slug)
        if table:
            inner.append(table)
            inner.append("")
        if inner:
            lines.append("<details><summary>Lineups, substitutions, cards & stats</summary>")
            lines.append("")
            lines.extend(inner)
            lines.append("</details>")
            lines.append("")
    elif m.get("note"):
        lines.append(m["note"])
        lines.append("")
    return "\n".join(lines)


def render_results_by_date(matches, details, by_slug):
    lines = ["## Match results", ""]
    dates = []
    for m in matches:
        if m["date"] not in dates:
            dates.append(m["date"])
    for date in dates:
        lines.append(f"### {date}")
        lines.append("")
        for m in [mm for mm in matches if mm["date"] == date]:
            if m.get("status") == "completed":
                lines.append(render_match(m, details.get(m.get("id")), by_slug))
            else:
                grp = f"Group {m['group']}" if m.get("group") else m.get("stage", "")
                lines.append(
                    f"#### {team_name(by_slug, m['home'])} vs "
                    f"{team_name(by_slug, m['away'])} ({grp}) — _scheduled_\n"
                )
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
    details = load_match_details()
    teams = load_all_teams()
    by_slug = {t["slug"]: t for t in teams}

    if not matches:
        print("No results found; skipping results.md.")
        return

    completed = [m for m in matches if m.get("status") == "completed"]
    lines = ["# Results", ""]
    lines.append(
        f"_{len(completed)} matches played; {len(details)} with full detail "
        f"(goals, lineups, stats)._"
    )
    lines.append("")
    standings = compute_standings(teams, matches)
    lines.append(render_standings(standings))
    lines.append(render_results_by_date(matches, details, by_slug))

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "results.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Wrote docs/results.md ({len(completed)} completed, {len(details)} detailed).")


if __name__ == "__main__":
    main()
