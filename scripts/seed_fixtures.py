#!/usr/bin/env python3
"""Seed the remaining 2026 World Cup fixtures into data/results/.

The dataset shipped with matchday 1 (complete) and matchday 2 for groups A-J.
This one-off script fills in the rest of the published schedule:

  * Group K & L matchday 2  (23 Jun)
  * All matchday 3 fixtures (24-27 Jun)
  * The full 32-match knockout bracket (28 Jun - 19 Jul)

Group-stage pairings, dates and venues were cross-checked against two
independent published schedules; the matchups also follow FIFA's fixed
round-robin pattern from each group's draw position in tournament.json.

Knockout teams are unknown until the group stage finishes, so each slot is
written as a placeholder slug (winner-group-a, runner-up-group-b,
third-cefhi, winner-match-73, loser-match-101 ...). common.placeholder_label
renders these as "Winner Group A" etc., and validate.py accepts them for
non-group stages.

Existing result files are never overwritten; the script only writes dates that
do not yet exist. Run once, then validate + regenerate as usual.

Usage: python3 scripts/seed_fixtures.py
"""

import json
import os

from common import RESULTS_DIR

# Canonical venue strings keyed by a short city handle, matching the spelling
# already used in the committed result files.
VEN = {
    "mexico-city": "Estadio Azteca, Mexico City",
    "guadalajara": "Estadio Akron, Guadalajara",
    "monterrey": "Estadio BBVA, Monterrey",
    "vancouver": "BC Place, Vancouver",
    "toronto": "BMO Field, Toronto",
    "seattle": "Lumen Field, Seattle",
    "sf": "Levi's Stadium, Santa Clara",
    "la": "SoFi Stadium, Inglewood",
    "houston": "NRG Stadium, Houston",
    "dallas": "AT&T Stadium, Arlington",
    "kansas": "Arrowhead Stadium, Kansas City",
    "atlanta": "Mercedes-Benz Stadium, Atlanta",
    "miami": "Hard Rock Stadium, Miami Gardens",
    "boston": "Gillette Stadium, Foxborough",
    "philadelphia": "Lincoln Financial Field, Philadelphia",
    "nynj": "MetLife Stadium, East Rutherford",
}

# --- group stage: (date, group, matchday, home, away, venue) -----------------
GROUP = [
    # Group K & L matchday 2 (23 Jun)
    ("2026-06-23", "K", 2, "portugal", "uzbekistan", "houston"),
    ("2026-06-23", "L", 2, "england", "ghana", "boston"),
    ("2026-06-23", "L", 2, "panama", "croatia", "toronto"),
    ("2026-06-23", "K", 2, "colombia", "dr-congo", "guadalajara"),
    # Matchday 3 (24-27 Jun)
    ("2026-06-24", "C", 3, "scotland", "brazil", "miami"),
    ("2026-06-24", "C", 3, "morocco", "haiti", "atlanta"),
    ("2026-06-24", "B", 3, "switzerland", "canada", "vancouver"),
    ("2026-06-24", "B", 3, "bosnia-herzegovina", "qatar", "seattle"),
    ("2026-06-24", "A", 3, "czechia", "mexico", "mexico-city"),
    ("2026-06-24", "A", 3, "south-africa", "south-korea", "monterrey"),
    ("2026-06-25", "E", 3, "curacao", "cote-divoire", "philadelphia"),
    ("2026-06-25", "E", 3, "ecuador", "germany", "nynj"),
    ("2026-06-25", "F", 3, "japan", "sweden", "dallas"),
    ("2026-06-25", "F", 3, "tunisia", "netherlands", "kansas"),
    ("2026-06-25", "D", 3, "turkiye", "usa", "la"),
    ("2026-06-25", "D", 3, "paraguay", "australia", "sf"),
    ("2026-06-26", "I", 3, "norway", "france", "boston"),
    ("2026-06-26", "I", 3, "senegal", "iraq", "toronto"),
    ("2026-06-26", "H", 3, "cabo-verde", "saudi-arabia", "houston"),
    ("2026-06-26", "H", 3, "uruguay", "spain", "guadalajara"),
    ("2026-06-26", "G", 3, "egypt", "iran", "seattle"),
    ("2026-06-26", "G", 3, "new-zealand", "belgium", "vancouver"),
    ("2026-06-27", "L", 3, "panama", "england", "nynj"),
    ("2026-06-27", "L", 3, "croatia", "ghana", "philadelphia"),
    ("2026-06-27", "K", 3, "colombia", "portugal", "miami"),
    ("2026-06-27", "K", 3, "dr-congo", "uzbekistan", "atlanta"),
    ("2026-06-27", "J", 3, "algeria", "austria", "kansas"),
    ("2026-06-27", "J", 3, "jordan", "argentina", "dallas"),
]

# --- knockout: (date, stage, match#, home_slot, away_slot, venue) ------------
STAGE_CODE = {
    "round-of-32": "r32", "round-of-16": "r16", "quarter-final": "qf",
    "semi-final": "sf", "third-place": "tp", "final": "f",
}
STAGE_LABEL = {
    "round-of-32": "Round of 32", "round-of-16": "Round of 16",
    "quarter-final": "Quarter-final", "semi-final": "Semi-final",
    "third-place": "Third-place play-off", "final": "Final",
}
KNOCKOUT = [
    ("2026-06-28", "round-of-32", 73, "runner-up-group-a", "runner-up-group-b", "la"),
    ("2026-06-29", "round-of-32", 74, "winner-group-e", "third-abcdf", "boston"),
    ("2026-06-29", "round-of-32", 75, "winner-group-f", "runner-up-group-c", "monterrey"),
    ("2026-06-29", "round-of-32", 76, "winner-group-c", "runner-up-group-f", "houston"),
    ("2026-06-30", "round-of-32", 77, "winner-group-i", "third-cdfgh", "nynj"),
    ("2026-06-30", "round-of-32", 78, "runner-up-group-e", "runner-up-group-i", "dallas"),
    ("2026-06-30", "round-of-32", 79, "winner-group-a", "third-cefhi", "mexico-city"),
    ("2026-07-01", "round-of-32", 80, "winner-group-l", "third-ehijk", "atlanta"),
    ("2026-07-01", "round-of-32", 81, "winner-group-d", "third-befij", "sf"),
    ("2026-07-01", "round-of-32", 82, "winner-group-g", "third-aehij", "seattle"),
    ("2026-07-02", "round-of-32", 83, "runner-up-group-k", "runner-up-group-l", "toronto"),
    ("2026-07-02", "round-of-32", 84, "winner-group-h", "runner-up-group-j", "la"),
    ("2026-07-02", "round-of-32", 85, "winner-group-b", "third-efgij", "vancouver"),
    ("2026-07-03", "round-of-32", 86, "winner-group-j", "runner-up-group-h", "miami"),
    ("2026-07-03", "round-of-32", 87, "winner-group-k", "third-deijl", "kansas"),
    ("2026-07-03", "round-of-32", 88, "runner-up-group-d", "runner-up-group-g", "dallas"),
    ("2026-07-04", "round-of-16", 89, "winner-match-74", "winner-match-77", "philadelphia"),
    ("2026-07-04", "round-of-16", 90, "winner-match-73", "winner-match-75", "houston"),
    ("2026-07-05", "round-of-16", 91, "winner-match-76", "winner-match-78", "nynj"),
    ("2026-07-05", "round-of-16", 92, "winner-match-79", "winner-match-80", "mexico-city"),
    ("2026-07-06", "round-of-16", 93, "winner-match-83", "winner-match-84", "dallas"),
    ("2026-07-06", "round-of-16", 94, "winner-match-81", "winner-match-82", "seattle"),
    ("2026-07-07", "round-of-16", 95, "winner-match-86", "winner-match-88", "atlanta"),
    ("2026-07-07", "round-of-16", 96, "winner-match-85", "winner-match-87", "vancouver"),
    ("2026-07-09", "quarter-final", 97, "winner-match-89", "winner-match-90", "boston"),
    ("2026-07-10", "quarter-final", 98, "winner-match-93", "winner-match-94", "la"),
    ("2026-07-11", "quarter-final", 99, "winner-match-91", "winner-match-92", "miami"),
    ("2026-07-11", "quarter-final", 100, "winner-match-95", "winner-match-96", "kansas"),
    ("2026-07-14", "semi-final", 101, "winner-match-97", "winner-match-98", "dallas"),
    ("2026-07-15", "semi-final", 102, "winner-match-99", "winner-match-100", "atlanta"),
    ("2026-07-18", "third-place", 103, "loser-match-101", "loser-match-102", "miami"),
    ("2026-07-19", "final", 104, "winner-match-101", "winner-match-102", "nynj"),
]


def group_match(date, grp, md, home, away, ven):
    return {
        "id": f"{date}-{home}-vs-{away}",
        "stage": "group",
        "group": grp,
        "matchday": md,
        "home": home,
        "away": away,
        "home_score": None,
        "away_score": None,
        "status": "scheduled",
        "venue": VEN[ven],
        "note": f"Group {grp} matchday {md}.",
    }


def knockout_match(date, stage, num, home, away, ven):
    return {
        "id": f"{date}-{STAGE_CODE[stage]}-{num}",
        "match_number": num,
        "stage": stage,
        "group": None,
        "matchday": None,
        "home": home,
        "away": away,
        "home_score": None,
        "away_score": None,
        "status": "scheduled",
        "venue": VEN[ven],
        "note": f"{STAGE_LABEL[stage]} — Match {num}.",
    }


def main():
    by_date = {}
    for row in GROUP:
        by_date.setdefault(row[0], []).append(group_match(*row))
    for row in KNOCKOUT:
        by_date.setdefault(row[0], []).append(knockout_match(*row))

    written = skipped = 0
    for date in sorted(by_date):
        path = os.path.join(RESULTS_DIR, f"{date}.json")
        if os.path.exists(path):
            print(f"skip   {date}.json (already exists)")
            skipped += 1
            continue
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"date": date, "matches": by_date[date]}, fh,
                      ensure_ascii=False, indent=2)
            fh.write("\n")
        print(f"wrote  {date}.json ({len(by_date[date])} matches)")
        written += 1

    total = len(GROUP) + len(KNOCKOUT)
    print(f"\n{written} file(s) written, {skipped} skipped; "
          f"{total} fixtures defined ({len(GROUP)} group, {len(KNOCKOUT)} knockout).")


if __name__ == "__main__":
    main()
