#!/usr/bin/env python3
"""Compute aggregate market-value statistics and write docs/stats.md.

Usage: python3 scripts/stats.py
"""

import os

from common import (
    DOCS_DIR,
    GROUP_LETTERS,
    fmt_eur,
    fmt_num,
    fmt_usd,
    load_all_teams,
    load_tournament,
    squad_value,
)


def main():
    teams = load_all_teams()
    tournament = load_tournament()

    if not teams:
        print("No team data found; skipping stats.")
        return

    lines = ["# Market Value Statistics", ""]
    lines.append(f"_Based on {len(teams)} teams with data._")
    lines.append("")

    # --- most valuable squads ---
    lines.append("## Most valuable squads")
    lines.append("")
    lines.append("| Rank | Team | Group | Squad value |")
    lines.append("|------|------|-------|-------------|")
    ranked = sorted(teams, key=squad_value, reverse=True)
    for i, t in enumerate(ranked, start=1):
        lines.append(f"| {i} | {t['name']} | {t.get('group','')} | {fmt_eur(squad_value(t))} |")
    lines.append("")

    # --- value by group ---
    lines.append("## Total value by group")
    lines.append("")
    lines.append("| Group | Teams | Total value |")
    lines.append("|-------|-------|-------------|")
    by_group = {}
    for t in teams:
        by_group.setdefault(t.get("group"), []).append(t)
    for letter in GROUP_LETTERS:
        grp = by_group.get(letter, [])
        if grp:
            total = sum(squad_value(t) for t in grp)
            lines.append(f"| {letter} | {len(grp)} | {fmt_eur(total)} |")
    lines.append("")

    # --- top players ---
    players = []
    for t in teams:
        for p in t.get("squad", []):
            players.append((p, t))
    players.sort(key=lambda pt: pt[0].get("market_value_eur", 0), reverse=True)

    lines.append("## Top 25 most valuable players")
    lines.append("")
    lines.append("| Rank | Player | Team | Club | Market value |")
    lines.append("|------|--------|------|------|--------------|")
    for i, (p, t) in enumerate(players[:25], start=1):
        lines.append(
            f"| {i} | {p.get('name','')} | {t['name']} | {p.get('club','')} | "
            f"{fmt_eur(p.get('market_value_eur', 0))} |"
        )
    lines.append("")

    # --- summary numbers ---
    total_all = sum(squad_value(t) for t in teams)
    n_players = len(players)
    avg_player = total_all // n_players if n_players else 0
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total market value of all squads: **{fmt_eur(total_all)}**")
    lines.append(f"- Players counted: **{n_players}**")
    lines.append(f"- Average player value: **{fmt_eur(avg_player)}**")
    lines.append("")

    # --- economy (GNP) rankings ---
    econ = [t for t in teams if t.get("gnp_usd") is not None]
    if econ:
        lines.append("## Economy (GNP)")
        lines.append("")
        lines.append("_Gross National Product (World Bank GNI). See README for sources and caveats._")
        lines.append("")

        lines.append("### By total GNP")
        lines.append("")
        lines.append("| Rank | Team | Group | GNP | Year |")
        lines.append("|------|------|-------|-----|------|")
        for i, t in enumerate(sorted(econ, key=lambda x: x["gnp_usd"], reverse=True), 1):
            lines.append(
                f"| {i} | {t['name']} | {t.get('group','')} | "
                f"{fmt_usd(t['gnp_usd'])} | {t.get('gnp_year','')} |"
            )
        lines.append("")

        pc = [t for t in econ if t.get("gnp_per_capita_usd") is not None]
        lines.append("### By GNP per capita")
        lines.append("")
        lines.append("| Rank | Team | Group | GNP per capita | Year |")
        lines.append("|------|------|-------|----------------|------|")
        for i, t in enumerate(sorted(pc, key=lambda x: x["gnp_per_capita_usd"], reverse=True), 1):
            lines.append(
                f"| {i} | {t['name']} | {t.get('group','')} | "
                f"{fmt_usd(t['gnp_per_capita_usd'])} | {t.get('gnp_year','')} |"
            )
        lines.append("")

    # --- governance & development rankings ---
    # (Descriptive country-level indicators; not used by the odds models.)
    def ranked_table(field, label, decimals, suffix, reverse, note=""):
        present = [t for t in teams if t.get(field) is not None]
        if not present:
            return
        lines.append(f"### By {label}")
        lines.append("")
        if note:
            lines.append(f"_{note}_")
            lines.append("")
        lines.append(f"| Rank | Team | Group | {label} |")
        lines.append("|------|------|-------|" + "-" * (len(label) + 2) + "|")
        ordered = sorted(present, key=lambda x: x[field], reverse=reverse)
        for i, t in enumerate(ordered, 1):
            lines.append(
                f"| {i} | {t['name']} | {t.get('group','')} | "
                f"{fmt_num(t[field], decimals, suffix)} |"
            )
        lines.append("")

    if any(t.get("hdi") is not None for t in teams):
        lines.append("## Governance & development")
        lines.append("")
        lines.append(
            "_Descriptive country-level political and economic indicators. "
            "These are **not** used by the odds models. Sources and reference "
            "years are documented in `SOURCES.md`; England and Scotland use UK "
            "figures as a proxy._"
        )
        lines.append("")
        ranked_table("hdi", "HDI", 3, "", reverse=True,
                     note="UNDP Human Development Index, 0-1 (higher = more developed).")
        ranked_table("corruption_perceptions_index", "CPI", 0, "", reverse=True,
                     note="Transparency International, 0-100 (higher = cleaner).")
        ranked_table("democracy_index", "Democracy Index", 2, "", reverse=True,
                     note="EIU, 0-10 (higher = more democratic).")
        ranked_table("global_peace_index", "Global Peace Index", 2, "", reverse=False,
                     note="IEP, ~1-5 (LOWER = more peaceful, so this table is ascending).")
        ranked_table("gdp_growth_pct", "GDP growth", 1, "%", reverse=True,
                     note="World Bank annual real GDP growth.")

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "stats.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Wrote docs/stats.md ({len(teams)} teams, {n_players} players).")


if __name__ == "__main__":
    main()
