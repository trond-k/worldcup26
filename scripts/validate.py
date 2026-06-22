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
    ROOT,
    RESULTS_DIR,
    TEAMS_DIR,
    load_results,
    load_tournament,
    placeholder_label,
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
SCHEMA_DIR = os.path.join(ROOT, "schema")
_SCHEMA_CACHE = {}


def _validate_schema(data, schema_name, tag, errors):
    """Validate one object against its canonical JSON Schema."""
    try:
        from jsonschema import Draft7Validator, FormatChecker
    except ModuleNotFoundError:
        msg = "jsonschema is required; install dependencies with: pip install -r requirements.txt"
        if msg not in errors:
            errors.append(msg)
        return
    schema = _SCHEMA_CACHE.get(schema_name)
    if schema is None:
        schema = load_json(os.path.join(SCHEMA_DIR, schema_name))
        Draft7Validator.check_schema(schema)
        _SCHEMA_CACHE[schema_name] = schema
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    for failure in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        location = ".".join(str(part) for part in failure.absolute_path)
        prefix = f"{tag}: schema"
        errors.append(f"{prefix}{f' at {location}' if location else ''}: {failure.message}")


def _minute_ok(value):
    """A minute may be null (unknown) or a string like '9', '45+1', '90+2'."""
    return value is None or bool(MINUTE_RE.match(str(value)))


def validate():
    errors = []
    warnings = []

    tournament = load_tournament()
    _validate_schema(tournament, "tournament.schema.json", "tournament.json", errors)
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
            team = load_json(path)
            _validate_schema(team, "team.schema.json", f"teams/{slug}.json", errors)
            _validate_team(slug, letter, team, errors)

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

        _validate_schema(d, "match-detail.schema.json", tag, errors)

        if not mid or fname != f"{mid}.json":
            err(f"id '{mid}' does not match filename")
            continue
        base = completed.get(mid)
        if base is None:
            err("no matching completed match with this id in data/results/")
            continue

        if d.get("date") != base.get("date"):
            err(f"date {d.get('date')!r} does not match results date {base.get('date')!r}")

        home, away = d.get("home"), d.get("away")
        sides = {home, away}
        if home != base["home"] or away != base["away"]:
            err("home/away do not match the results entry")
        for fld in ("home_score", "away_score"):
            if d.get(fld) != base.get(fld):
                err(f"{fld} {d.get(fld)!r} does not match results value {base.get(fld)!r}")
        for fld in ("home_penalties", "away_penalties", "decision"):
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
    seen_ids = {}
    seen_numbers = {}
    bracket_refs = []
    group_appearances = {}
    stage_counts = {}
    for fname in sorted(f for f in os.listdir(RESULTS_DIR) if f.endswith(".json")):
        day = load_json(os.path.join(RESULTS_DIR, fname))
        _validate_schema(day, "results.schema.json", f"results/{fname}", errors)
        date = day.get("date")
        if not date or fname != f"{date}.json":
            warnings.append(f"results/{fname}: filename does not match its date field '{date}'")
        for i, m in enumerate(day.get("matches", [])):
            tag = f"results/{fname} match #{i + 1}"

            def err(msg):
                errors.append(f"{tag}: {msg}")

            if m.get("stage") not in STAGES:
                err(f"invalid stage '{m.get('stage')}'")
            else:
                stage_counts[m.get("stage")] = stage_counts.get(m.get("stage"), 0) + 1
            status = m.get("status")
            if status not in RESULT_STATUSES:
                err(f"invalid status '{status}'")
            mid = m.get("id")
            if mid in seen_ids:
                err(f"duplicate id '{mid}' (also in {seen_ids[mid]})")
            elif mid:
                seen_ids[mid] = fname
            number = m.get("match_number")
            if m.get("stage") != "group" and not isinstance(number, int):
                err("knockout match needs match_number")
            if isinstance(number, int):
                if number in seen_numbers:
                    err(f"duplicate match_number {number} (also in {seen_numbers[number]})")
                else:
                    seen_numbers[number] = fname
            for side in ("home", "away"):
                slug = m.get(side)
                if slug not in valid_slugs:
                    # Knockout slots are seeded as placeholders (e.g.
                    # 'winner-group-a') before the teams are known.
                    if m.get("stage") == "group" or placeholder_label(slug) is None:
                        err(f"{side} team '{slug}' is not a known team slug")
                    elif slug.startswith(("winner-match-", "loser-match-")):
                        bracket_refs.append((tag, number, slug))
                    elif m.get("stage") != "round-of-32":
                        err(f"group-place placeholder '{slug}' is only valid in the Round of 32")
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
                        if slug in valid_slugs:
                            group_appearances[slug] = group_appearances.get(slug, 0) + 1
                if m.get("decision") in ("extra-time", "penalties"):
                    err("group match cannot be decided by extra time or penalties")
            elif grp is not None or m.get("matchday") is not None:
                err("knockout match must have null group and matchday")
            for fld in ("home_score", "away_score"):
                sc = m.get(fld)
                if status == "completed":
                    if not isinstance(sc, int) or isinstance(sc, bool) or sc < 0:
                        err(f"completed match needs non-negative integer {fld}, got {sc!r}")
                elif sc is not None:
                    err(f"scheduled match should have null {fld}, got {sc!r}")

            hp, ap = m.get("home_penalties"), m.get("away_penalties")
            decision = m.get("decision")
            if status == "scheduled" and any(v is not None for v in (hp, ap)):
                err("scheduled match cannot have penalty scores")
            if status == "scheduled" and decision is not None:
                err("scheduled match cannot have a decision")
            if decision == "penalties":
                if not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                           for v in (hp, ap)):
                    err("penalty decision needs non-negative integer penalty scores")
                elif hp == ap:
                    err("penalty shoot-out scores cannot be tied")
            elif any(v is not None for v in (hp, ap)):
                err("penalty scores require decision 'penalties'")
            if (status == "completed" and m.get("stage") != "group"
                    and m.get("home_score") == m.get("away_score")
                    and decision != "penalties"):
                err("tied knockout match needs a penalty decision and shoot-out score")

    if len(seen_ids) != 104:
        errors.append(f"results: expected 104 unique match ids, found {len(seen_ids)}")
    expected_stage_counts = {"group": 72, "round-of-32": 16, "round-of-16": 8,
                             "quarter-final": 4, "semi-final": 2,
                             "third-place": 1, "final": 1}
    if stage_counts != expected_stage_counts:
        errors.append(f"results: stage counts {stage_counts} != {expected_stage_counts}")
    bad_appearances = {slug: count for slug, count in group_appearances.items() if count != 3}
    if bad_appearances or set(group_appearances) != valid_slugs:
        errors.append(f"results: every team must have three group fixtures; found {bad_appearances}")
    expected_numbers = set(range(73, 105))
    if set(seen_numbers) != expected_numbers:
        errors.append("results: knockout match_number values must be exactly 73-104")
    for tag, current, slug in bracket_refs:
        referenced = int(slug.rsplit("-", 1)[-1])
        if referenced not in seen_numbers:
            errors.append(f"{tag}: placeholder '{slug}' references an unknown match")
        elif not isinstance(current, int) or referenced >= current:
            errors.append(f"{tag}: placeholder '{slug}' must reference an earlier match")


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

    for fld in ("gnp_usd", "gnp_per_capita_usd"):
        v = team.get(fld)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
            err(f"{fld} must be a non-negative integer or null, got {v!r}")
    elo_rating = team.get("elo_rating")
    if elo_rating is not None and (not isinstance(elo_rating, int) or isinstance(elo_rating, bool) or elo_rating < 0):
        err(f"elo_rating must be a non-negative integer or null, got {elo_rating!r}")
    elo_rank = team.get("elo_rank")
    if elo_rank is not None and (not isinstance(elo_rank, int) or isinstance(elo_rank, bool) or elo_rank < 1):
        err(f"elo_rank must be a positive integer or null, got {elo_rank!r}")
    pop = team.get("population")
    if pop is not None and (not isinstance(pop, int) or isinstance(pop, bool) or pop < 0):
        err(f"population must be a non-negative integer or null, got {pop!r}")
    for yf in ("gnp_year", "population_year"):
        yv = team.get(yf)
        if yv is not None and (not isinstance(yv, int) or yv < 2010 or yv > 2026):
            err(f"{yf} must be an integer 2010-2026 or null, got {yv!r}")

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
