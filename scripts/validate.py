#!/usr/bin/env python3
"""Validate the World Cup 2026 dataset.

Checks structural integrity of data/tournament.json and every data/teams/*.json
file. Exits non-zero if any problem is found, so it can be used in CI.

Usage: python3 scripts/validate.py
"""

import os
import re
import sys

from common import (
    GROUP_LETTERS,
    MATCHES_DIR,
    POSITIONS,
    RESULTS_DIR,
    TEAMS_DIR,
    load_results,
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
GOAL_TYPES = {"regular", "penalty", "own_goal"}
CARD_TYPES = {"yellow", "second-yellow", "red"}
MINUTE_RE = re.compile(r"^\d{1,3}(\+\d{1,2})?$")


def _minute_ok(value):
    """A minute may be null (unknown) or a string like '9', '45+1', '90+2'."""
    return value is None or bool(MINUTE_RE.match(str(value)))


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

    # --- match-detail validation ---
    _validate_match_details(set(all_slugs), errors, warnings)

    return errors, warnings


def _validate_match_details(valid_slugs, errors, warnings):
    if not os.path.isdir(MATCHES_DIR):
        return
    # index completed matches from the results files by id
    completed = {}
    for m in load_results():
        if m.get("status") == "completed" and m.get("id"):
            completed[m["id"]] = m

    for fname in sorted(f for f in os.listdir(MATCHES_DIR) if f.endswith(".json")):
        d = load_json(os.path.join(MATCHES_DIR, fname))
        mid = d.get("id")
        tag = f"matches/{fname}"

        def err(msg):
            errors.append(f"{tag}: {msg}")

        if not mid or fname != f"{mid}.json":
            err(f"id '{mid}' does not match filename")
            continue
        base = completed.get(mid)
        if base is None:
            err("no matching completed match with this id in data/results/")
            continue

        home, away = d.get("home"), d.get("away")
        sides = {home, away}
        if home != base["home"] or away != base["away"]:
            err("home/away do not match the results entry")
        for fld in ("home_score", "away_score"):
            if d.get(fld) != base.get(fld):
                err(f"{fld} {d.get(fld)!r} does not match results value {base.get(fld)!r}")

        # goals: enums, minute format, team membership, reconcile to score
        tallies = {home: 0, away: 0}
        for i, g in enumerate(d.get("goals", [])):
            gt = f"goal #{i + 1}"
            if g.get("team") not in sides:
                err(f"{gt}: team '{g.get('team')}' is not in this match")
            else:
                tallies[g["team"]] += 1
            if not g.get("player"):
                err(f"{gt}: missing player")
            if g.get("type") not in GOAL_TYPES:
                err(f"{gt}: invalid type '{g.get('type')}'")
            if not _minute_ok(g.get("minute")):
                err(f"{gt}: invalid minute '{g.get('minute')}'")
        if d.get("goals"):
            if tallies.get(home) != d.get("home_score"):
                err(f"goals credited to home ({tallies.get(home)}) != home_score ({d.get('home_score')})")
            if tallies.get(away) != d.get("away_score"):
                err(f"goals credited to away ({tallies.get(away)}) != away_score ({d.get('away_score')})")

        for i, c in enumerate(d.get("cards", [])):
            ct = f"card #{i + 1}"
            if c.get("team") not in sides:
                err(f"{ct}: team '{c.get('team')}' is not in this match")
            if c.get("card") not in CARD_TYPES:
                err(f"{ct}: invalid card '{c.get('card')}'")
            if not _minute_ok(c.get("minute")):
                err(f"{ct}: invalid minute '{c.get('minute')}'")

        for i, s in enumerate(d.get("substitutions", [])):
            st = f"sub #{i + 1}"
            if s.get("team") not in sides:
                err(f"{st}: team '{s.get('team')}' is not in this match")
            if not s.get("off") and not s.get("on"):
                err(f"{st}: substitution needs at least one of off/on")
            if not _minute_ok(s.get("minute")):
                err(f"{st}: invalid minute '{s.get('minute')}'")

        lineups = d.get("lineups", {})
        for side_key, slug in (("home", home), ("away", away)):
            lu = lineups.get(side_key)
            if not lu:
                continue
            starting = lu.get("starting", [])
            if starting and len(starting) != 11:
                warnings.append(f"{tag}: {side_key} starting XI has {len(starting)} players, expected 11")
            for p in starting:
                if not p.get("name"):
                    err(f"{side_key} lineup: a starter is missing a name")
                pos = p.get("position")
                if pos is not None and pos not in POSITIONS:
                    err(f"{side_key} lineup: invalid position '{pos}' for {p.get('name')}")

    for mid in completed:
        if not os.path.exists(os.path.join(MATCHES_DIR, f"{mid}.json")):
            warnings.append(f"no match-detail file yet for completed match '{mid}'")


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
    n_details = 0
    if os.path.isdir(MATCHES_DIR):
        n_details = len([f for f in os.listdir(MATCHES_DIR) if f.endswith(".json")])
    print(
        f"\nChecked {n_teams}/48 team files, {n_matches} matches "
        f"across {n_result_files} result file(s), and {n_details} match-detail file(s). "
        f"{len(errors)} error(s), {len(warnings)} warning(s)."
    )
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
