#!/usr/bin/env python3
"""Resolve knowable knockout placeholders from completed tournament results.

Dry-run by default. Use ``--apply`` after a group or knockout round finishes so
the day files contain real team slugs for harvesting and future site builds.
Unknown slots remain untouched; real team assignments are never overwritten.
"""

import os
import sys

from common import (
    RESULTS_DIR,
    atomic_write_json,
    compute_standings,
    load_all_teams,
    load_json,
    load_match_details,
    load_results,
    placeholder_label,
    resolve_bracket_slots,
)


def main():
    apply = "--apply" in sys.argv[1:]
    teams = load_all_teams()
    matches = load_results()
    details = load_match_details()
    standings = compute_standings(teams, matches, details)
    resolved = {m["id"]: m for m in resolve_bracket_slots(matches, standings)}

    changes = 0
    dirty_days = []
    for fname in sorted(f for f in os.listdir(RESULTS_DIR) if f.endswith(".json")):
        path = os.path.join(RESULTS_DIR, fname)
        day = load_json(path)
        dirty = False
        for match in day.get("matches", []):
            target = resolved.get(match.get("id"))
            if not target:
                continue
            for side in ("home", "away"):
                old, new = match.get(side), target.get(side)
                if old != new and placeholder_label(old) and not placeholder_label(new):
                    print(f"{match['id']}: {side} {placeholder_label(old)} -> {new}")
                    match[side] = new
                    dirty = True
                    changes += 1
        if dirty:
            dirty_days.append((path, day))

    if apply:
        for path, day in dirty_days:
            atomic_write_json(path, day)
        print(f"WROTE {changes} slot(s) across {len(dirty_days)} day file(s).")
    else:
        print(f"DRY RUN {changes} resolvable slot(s)"
              + (" (pass --apply to write)." if changes else "."))


if __name__ == "__main__":
    main()
