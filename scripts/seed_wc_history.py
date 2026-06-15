"""Seed each team's World Cup history fields (wc_titles / wc_appearances /
wc_best_finish) used by the football model in odds.py.

Values are each nation's real-world men's World Cup record through the 2022
tournament, with predecessor states folded in (West Germany -> Germany,
Czechoslovakia -> Czechia, USSR not applicable here). best_finish uses the
enum in schema/team.schema.json.

Dry-run by default (prints a table); pass --apply to write the team JSONs.

    python3 scripts/seed_wc_history.py            # preview
    python3 scripts/seed_wc_history.py --apply    # write
"""

import json
import sys

from common import GROUP_LETTERS, load_tournament, team_path

# slug -> (titles, appearances through 2022, best_finish)
WC_HISTORY = {
    "mexico":             (0, 17, "quarter-final"),
    "south-africa":       (0, 3,  "group-stage"),
    "south-korea":        (0, 11, "fourth"),
    "czechia":            (0, 9,  "runner-up"),    # incl. Czechoslovakia
    "canada":             (0, 2,  "group-stage"),
    "bosnia-herzegovina": (0, 1,  "group-stage"),
    "qatar":              (0, 1,  "group-stage"),
    "switzerland":        (0, 12, "quarter-final"),
    "brazil":             (5, 22, "winners"),
    "morocco":            (0, 6,  "fourth"),       # 2022 semi-finalists
    "haiti":              (0, 1,  "group-stage"),
    "scotland":           (0, 8,  "group-stage"),
    "usa":                (0, 11, "third"),        # 1930
    "paraguay":           (0, 8,  "quarter-final"),
    "australia":          (0, 6,  "round-16"),
    "turkiye":            (0, 2,  "third"),         # 2002
    "germany":            (4, 20, "winners"),       # incl. West Germany
    "curacao":            (0, 0,  "never-qualified"),
    "cote-divoire":       (0, 3,  "group-stage"),
    "ecuador":            (0, 4,  "round-16"),
    "netherlands":        (0, 11, "runner-up"),
    "japan":              (0, 7,  "round-16"),
    "sweden":             (0, 12, "runner-up"),     # 1958 hosts
    "tunisia":            (0, 6,  "group-stage"),
    "belgium":            (0, 14, "third"),         # 2018
    "egypt":              (0, 3,  "group-stage"),
    "iran":               (0, 6,  "group-stage"),
    "new-zealand":        (0, 2,  "group-stage"),
    "spain":              (1, 16, "winners"),       # 2010
    "cabo-verde":         (0, 0,  "never-qualified"),
    "saudi-arabia":       (0, 6,  "round-16"),      # 1994
    "uruguay":            (2, 14, "winners"),
    "france":             (2, 16, "winners"),
    "senegal":            (0, 3,  "quarter-final"), # 2002
    "iraq":               (0, 1,  "group-stage"),
    "norway":             (0, 3,  "round-16"),      # 1998
    "argentina":          (3, 18, "winners"),
    "algeria":            (0, 4,  "round-16"),      # 2014
    "austria":            (0, 7,  "third"),         # 1954
    "jordan":             (0, 0,  "never-qualified"),
    "portugal":           (0, 8,  "third"),         # 1966
    "dr-congo":           (0, 1,  "group-stage"),   # Zaire 1974
    "uzbekistan":         (0, 0,  "never-qualified"),
    "colombia":           (0, 6,  "quarter-final"), # 2014
    "england":            (1, 16, "winners"),       # 1966
    "croatia":            (0, 6,  "runner-up"),     # 2018
    "ghana":              (0, 4,  "quarter-final"), # 2010
    "panama":             (0, 1,  "group-stage"),
}


def ordered_with_wc(team, titles, apps, finish):
    """Return team dict with wc_* inserted just before the squad."""
    out = {}
    for key, val in team.items():
        if key == "squad":
            out["wc_titles"] = titles
            out["wc_appearances"] = apps
            out["wc_best_finish"] = finish
        out[key] = val
    return out


def main():
    apply = "--apply" in sys.argv[1:]
    tournament = load_tournament()
    slugs = [s for L in GROUP_LETTERS for s in tournament["groups"].get(L, [])]

    missing = [s for s in slugs if s not in WC_HISTORY]
    if missing:
        sys.exit(f"no WC history for: {', '.join(missing)}")

    print(f"{'team':22s} {'titles':>6} {'apps':>5}  best finish")
    for slug in slugs:
        titles, apps, finish = WC_HISTORY[slug]
        print(f"{slug:22s} {titles:>6} {apps:>5}  {finish}")
        if apply:
            path = team_path(slug)
            team = json.loads(open(path, encoding="utf-8").read())
            team = ordered_with_wc(team, titles, apps, finish)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(team, ensure_ascii=False, indent=2) + "\n")

    print(f"\n{'WROTE' if apply else 'DRY RUN'} {len(slugs)} teams"
          + ("" if apply else "  (pass --apply to write)"))


if __name__ == "__main__":
    main()
