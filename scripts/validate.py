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
    RESULTS_DIR,
    TEAMS_DIR,
    load_tournament,
    team_path,
    load_json,
)

CONFEDERATIONS = {"AFC", "CAF", "CONCACAF", "CONMEBOL", "OFC", "UEFA"}
SQUAD_SIZE = 26
STAGES = {
    "group", "round-of-32", "round-of-16", "quarter-final",
    "semi-final", "third-place", "final",
}
RESULT_STATUSES = {"completed", "scheduled"}


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

    # --- results validation ---
    _validate_results(set(all_slugs), groups, errors, warnings)

    return errors, warnings


def _validate_results(valid_slugs, groups, errors, warnings):
    if not os.path.isdir(RESULTS_DIR):
        return
    for fname in sorted(f for f in os.listdir(RESULTS_DIR) if f.endswith(".json")):
        day = load_json(os.path.join(RESULTS_DIR, fname))
        date = day.get("date")
        if not date or fname != f"{date}.json":
            warnings.append(f"results/{fname}: filename does not match its date field '{date}'")
        for i, m in enumerate(day.get("matches", [])):
            tag = f"results/{fname} match #{i + 1}"

            def err(msg):
                errors.append(f"{tag}: {msg}")

            if m.get("stage") not in STAGES:
                err(f"invalid stage '{m.get('stage')}'")
            status = m.get("status")
            if status not in RESULT_STATUSES:
                err(f"invalid status '{status}'")
            for side in ("home", "away"):
                slug = m.get(side)
                if slug not in valid_slugs:
                    err(f"{side} team '{slug}' is not a known team slug")
            if m.get("home") == m.get("away"):
                err("home and away teams are identical")
            grp = m.get("group")
            if m.get("stage") == "group":
                if grp not in GROUP_LETTERS:
                    err(f"group match has invalid group '{grp}'")
                else:
                    for side in ("home", "away"):
                        slug = m.get(side)
                        if slug in valid_slugs and slug not in groups.get(grp, []):
                            err(f"{side} team '{slug}' is not in group {grp}")
            for fld in ("home_score", "away_score"):
                sc = m.get(fld)
                if status == "completed":
                    if not isinstance(sc, int) or isinstance(sc, bool) or sc < 0:
                        err(f"completed match needs non-negative integer {fld}, got {sc!r}")
                elif sc is not None:
                    err(f"scheduled match should have null {fld}, got {sc!r}")


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
    n_result_files = 0
    n_matches = 0
    if os.path.isdir(RESULTS_DIR):
        for fname in os.listdir(RESULTS_DIR):
            if fname.endswith(".json"):
                n_result_files += 1
                n_matches += len(load_json(os.path.join(RESULTS_DIR, fname)).get("matches", []))
    print(
        f"\nChecked {n_teams}/48 team files and {n_matches} matches "
        f"across {n_result_files} result file(s). "
        f"{len(errors)} error(s), {len(warnings)} warning(s)."
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
