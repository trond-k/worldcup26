#!/usr/bin/env python3
"""Generate human-readable Markdown views under docs/ from the JSON data.

Produces:
  docs/README.md        index of all groups
  docs/group-<x>.md     one page per group with a squad table per team

Everything under docs/ is generated -- do not edit by hand.

Usage: python3 scripts/generate_markdown.py
"""

import os

from common import (
    DOCS_DIR,
    GROUP_LETTERS,
    fmt_eur,
    fmt_usd,
    load_team,
    load_tournament,
    sorted_squad,
    squad_value,
    team_path,
)


def render_team(team):
    lines = []
    lines.append(f"### {team['name']}")
    lines.append("")
    meta = []
    if team.get("confederation"):
        meta.append(f"**Confederation:** {team['confederation']}")
    if team.get("fifa_ranking"):
        meta.append(f"**FIFA ranking:** {team['fifa_ranking']}")
    if team.get("coach"):
        meta.append(f"**Coach:** {team['coach']}")
    meta.append(f"**Squad value:** {fmt_eur(squad_value(team))}")
    if team.get("gnp_usd") is not None:
        yr = f" ({team['gnp_year']})" if team.get("gnp_year") else ""
        meta.append(f"**GNP:** {fmt_usd(team['gnp_usd'])}{yr}")
    if team.get("gnp_per_capita_usd") is not None:
        meta.append(f"**GNP per capita:** {fmt_usd(team['gnp_per_capita_usd'])}")
    if team.get("population") is not None:
        meta.append(f"**Population:** {team['population']:,}")
    lines.append(" · ".join(meta))
    lines.append("")
    lines.append("| # | Player | Pos | Club | Market value |")
    lines.append("|---|--------|-----|------|--------------|")
    for i, p in enumerate(sorted_squad(team), start=1):
        club = p.get("club", "")
        if p.get("club_country"):
            club += f" ({p['club_country']})"
        lines.append(
            f"| {i} | {p.get('name','')} | {p.get('position','')} | "
            f"{club} | {fmt_eur(p.get('market_value_eur', 0))} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_group(letter, slugs):
    teams = [load_team(s) for s in slugs if os.path.exists(team_path(s))]
    lines = [f"# Group {letter}", ""]
    if teams:
        lines.append("| Team | Confederation | Squad value |")
        lines.append("|------|---------------|-------------|")
        for t in sorted(teams, key=squad_value, reverse=True):
            lines.append(
                f"| {t['name']} | {t.get('confederation','')} | "
                f"{fmt_eur(squad_value(t))} |"
            )
        lines.append("")
    missing = [s for s in slugs if not os.path.exists(team_path(s))]
    if missing:
        lines.append(f"_Pending data: {', '.join(missing)}_")
        lines.append("")
    for t in teams:
        lines.append(render_team(t))
    return "\n".join(lines)


def render_index(tournament):
    lines = [f"# {tournament['name']}", ""]
    lines.append(tournament.get("format", ""))
    lines.append("")
    lines.append(f"> {tournament.get('data_disclaimer', '')}")
    lines.append("")
    lines.append("| Group | Teams |")
    lines.append("|-------|-------|")
    for letter in GROUP_LETTERS:
        slugs = tournament["groups"].get(letter, [])
        names = []
        for s in slugs:
            if os.path.exists(team_path(s)):
                names.append(load_team(s)["name"])
            else:
                names.append(f"_{s}_")
        lines.append(f"| [{letter}](group-{letter.lower()}.md) | {', '.join(names)} |")
    lines.append("")
    lines.append("See [favourites.md](favourites.md) for the favourite/underdog "
                 "odds models, [stats.md](stats.md) for aggregate market-value "
                 "rankings, and [results.md](results.md) for match results and "
                 "live standings.")
    lines.append("")
    return "\n".join(lines)


def main():
    os.makedirs(DOCS_DIR, exist_ok=True)
    tournament = load_tournament()

    with open(os.path.join(DOCS_DIR, "README.md"), "w", encoding="utf-8") as fh:
        fh.write(render_index(tournament))

    for letter in GROUP_LETTERS:
        slugs = tournament["groups"].get(letter, [])
        path = os.path.join(DOCS_DIR, f"group-{letter.lower()}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render_group(letter, slugs))

    print(f"Wrote docs/README.md and {len(GROUP_LETTERS)} group pages to {DOCS_DIR}")


if __name__ == "__main__":
    main()
