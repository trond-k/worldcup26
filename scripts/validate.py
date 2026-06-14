#!/usr/bin/env python3
"""Validate the World Cup 2026 dataset.

Checks structural integrity of data/tournament.json and every data/teams/*.json
file. Exits non-zero if any problem is found, so it can be used in CI.

Usage: python3 scripts/validate.py
"""

import os
import sys

from common import (
    GROUP_LETTERS,
    POSITIONS,
    TEAMS_DIR,
    load_tournament,
    team_path,
    load_json,
)

CONFEDERATIONS = {"AFC", "CAF", "CONCACAF", "CONMEBOL", "OFC", "UEFA"}
SQUAD_SIZE = 26


def validate():
    errors = []
    warnings = []

    tournament = load_tournament()
    groups = tournament.get("groups", {})

    # --- group structure ---
    if sorted(groups.keys()) != GROUP_LETTERS:
        errors.append(
            f"groups must be exactly {GROUP_LETTERS}, found {sorted(groups.keys())}"
        )

    all_slugs = []
    for letter in GROUP_LETTERS:
        members = groups.get(letter, [])
        if len(members) != 4:
            errors.append(f"group {letter} must have 4 teams, has {len(members)}")
        all_slugs.extend(members)

    dupes = {s for s in all_slugs if all_slugs.count(s) > 1}
    if dupes:
        errors.append(f"team slugs appear in more than one group: {sorted(dupes)}")

    if len(set(all_slugs)) != 48:
        errors.append(f"expected 48 unique teams, found {len(set(all_slugs))}")

    # --- orphan team files (file exists but not referenced) ---
    if os.path.isdir(TEAMS_DIR):
        on_disk = {f[:-5] for f in os.listdir(TEAMS_DIR) if f.endswith(".json")}
        for slug in sorted(on_disk - set(all_slugs)):
            warnings.append(f"team file {slug}.json is not referenced in tournament.json")

    # --- per-team validation ---
    for letter in GROUP_LETTERS:
        for slug in groups.get(letter, []):
            path = team_path(slug)
            if not os.path.exists(path):
                warnings.append(f"missing team file for '{slug}' (group {letter})")
                continue
            _validate_team(slug, letter, load_json(path), errors)

    return errors, warnings


def _validate_team(slug, expected_group, team, errors):
    def err(msg):
        errors.append(f"[{slug}] {msg}")

    if team.get("slug") != slug:
        err(f"slug field '{team.get('slug')}' does not match filename '{slug}'")
    if not team.get("name"):
        err("missing name")
    if team.get("confederation") not in CONFEDERATIONS:
        err(f"invalid confederation '{team.get('confederation')}'")
    if team.get("group") != expected_group:
        err(f"group '{team.get('group')}' does not match tournament group '{expected_group}'")

    squad = team.get("squad", [])
    if len(squad) != SQUAD_SIZE:
        err(f"squad has {len(squad)} players, expected {SQUAD_SIZE}")

    names = []
    for i, p in enumerate(squad):
        tag = f"player #{i + 1} ({p.get('name', '?')})"
        if not p.get("name"):
            err(f"{tag}: missing name")
        names.append(p.get("name"))
        if p.get("position") not in POSITIONS:
            err(f"{tag}: invalid position '{p.get('position')}'")
        if not p.get("club"):
            err(f"{tag}: missing club")
        mv = p.get("market_value_eur")
        if not isinstance(mv, int) or isinstance(mv, bool) or mv < 0:
            err(f"{tag}: market_value_eur must be a non-negative integer, got {mv!r}")
        age = p.get("age")
        if age is not None and (not isinstance(age, int) or age < 15 or age > 50):
            err(f"{tag}: implausible age {age!r}")

    dupe_names = {n for n in names if n and names.count(n) > 1}
    if dupe_names:
        err(f"duplicate player names: {sorted(dupe_names)}")


def main():
    errors, warnings = validate()
    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERROR: {e}")

    tournament = load_tournament()
    n_teams = sum(
        1 for letter in GROUP_LETTERS for slug in tournament["groups"].get(letter, [])
        if os.path.exists(team_path(slug))
    )
    print(
        f"\nChecked {n_teams}/48 team files. "
        f"{len(errors)} error(s), {len(warnings)} warning(s)."
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
