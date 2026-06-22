#!/usr/bin/env python3
"""Write docs/favourites.md — the markdown mirror of the favourite/underdog
comparison models (see scripts/odds.py).

Usage: python3 scripts/favourites.py
"""

import os

from common import DOCS_DIR, fmt_eur, fmt_pop, load_all_teams, load_tournament, squad_value
from odds import build_team_scores


def main():
    teams = load_all_teams()
    tournament = load_tournament()
    if not teams:
        print("No team data found; skipping favourites.")
        return

    by_slug = {t["slug"]: t for t in teams}
    scores = build_team_scores(teams, tournament)

    lines = ["# Favourites", ""]
    lines.append(f"_Two independent toy models rate every team 0–100, based on "
                 f"{len(teams)} teams with data._")
    lines.append("")
    lines.append("The **football** model weighs squad market value, World Football "
                 "Elo, FIFA ranking, World Cup pedigree and squad age/depth. The "
                 "**socio-economic** "
                 "model weighs wealth (GNP per capita), population, total GNP, the "
                 "share of the squad playing abroad and in the big-5 leagues, plus "
                 "a host bump. They are never blended — the gaps between them are "
                 "the interesting part. Estimates only, not betting advice.")
    lines.append("")

    fb_order = sorted(scores.items(), key=lambda kv: -kv[1]["football"])
    so_order = sorted(scores.items(), key=lambda kv: -kv[1]["socio"])
    fb_rank = {s: i for i, (s, _) in enumerate(fb_order, 1)}
    so_rank = {s: i for i, (s, _) in enumerate(so_order, 1)}

    def rank_table(title, order, model):
        out = [f"## {title}", "", "| # | Team | Group | Score |",
               "|---|------|-------|-------|"]
        for i, (slug, sc) in enumerate(order, 1):
            host = " (host)" if sc.get("host") else ""
            grp = by_slug.get(slug, {}).get("group", "")
            out.append(f"| {i} | {sc['name']}{host} | {grp} | {sc[model]:.1f} |")
        out.append("")
        return out

    lines += rank_table("Football favourites", fb_order, "football")
    lines += rank_table("Socio-economic favourites", so_order, "socio")

    # Overachievers: football rank far better than socio-economic rank.
    lines += ["## Punching above their weight", "",
              "_Teams ranked far higher by football than by socio-economics — "
              "overachievers relative to their resources._", "",
              "| Team | Football | Socio-econ | Climb |",
              "|------|----------|------------|-------|"]
    climbs = sorted(scores, key=lambda s: so_rank[s] - fb_rank[s], reverse=True)
    for slug in climbs[:8]:
        gap = so_rank[slug] - fb_rank[slug]
        if gap <= 0:
            break
        lines.append(f"| {scores[slug]['name']} | #{fb_rank[slug]} | "
                     f"#{so_rank[slug]} | +{gap} |")
    lines.append("")

    # Talent density: squad value per citizen.
    lines += ["## Most squad value per citizen", "",
              "_Squad market value spread across the population — a talent-density "
              "read on the small nations._", "",
              "| Team | Squad value | Citizens | € / citizen |",
              "|------|-------------|----------|-------------|"]
    dens = [(s, sc) for s, sc in scores.items()
            if sc["density"].get("value_per_capita") is not None]
    dens.sort(key=lambda kv: kv[1]["density"]["value_per_capita"], reverse=True)
    for slug, sc in dens[:10]:
        t = by_slug.get(slug, {})
        vpc = sc["density"]["value_per_capita"]
        lines.append(f"| {sc['name']} | {fmt_eur(squad_value(t))} | "
                     f"{fmt_pop(t.get('population'))} | €{round(vpc):,} |")
    lines.append("")

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "favourites.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"Wrote docs/favourites.md ({len(teams)} teams).")


if __name__ == "__main__":
    main()
