#!/usr/bin/env python3
"""Seed team HDI values from the normalized UNDP HDR 2025 dataset.

The report was published in 2025 and its indicator reference year is 2023.
Run ``scripts/convert_hdi.py --apply`` only when rebuilding the normalized CSV
from the original workbook; this seeder consumes the tracked CSV directly.
"""

import csv
import os
import sys

from common import atomic_write_json, load_all_teams, load_json, team_path
from convert_hdi import ALIASES, CSV_PATH


HDI_YEAR = 2023


def load_hdi(path=CSV_PATH):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return {row["country"]: float(row["hdi"]) for row in csv.DictReader(fh)
                if row.get("country") and row.get("hdi")}


def with_hdi(team, value):
    """Return a copy with hdi_year next to hdi, preserving readable key order."""
    out = {}
    inserted_year = False
    for key, current in team.items():
        if key == "hdi":
            out[key] = value
            out["hdi_year"] = HDI_YEAR if value is not None else None
            inserted_year = True
        elif key != "hdi_year":
            out[key] = current
    if not inserted_year:
        out["hdi"] = value
        out["hdi_year"] = HDI_YEAR if value is not None else None
    return out


def main():
    apply = "--apply" in sys.argv[1:]
    if not os.path.exists(CSV_PATH):
        sys.exit(f"missing normalized HDI dataset: {CSV_PATH}")
    values = load_hdi()
    missing = []
    changes = []
    updates = []
    for summary in load_all_teams():
        source_name = ALIASES.get(summary["name"], summary["name"])
        value = values.get(source_name)
        if value is None and summary["slug"] != "curacao":
            missing.append(f"{summary['name']} -> {source_name}")
            continue
        old = summary.get("hdi")
        if old != value or summary.get("hdi_year") != (HDI_YEAR if value is not None else None):
            changes.append((summary["slug"], old, value))
            path = team_path(summary["slug"])
            updates.append((path, with_hdi(load_json(path), value)))

    if missing:
        sys.exit("unmatched HDI countries: " + ", ".join(missing))
    for slug, old, new in changes:
        print(f"{slug:22s} {old!s:>5} -> {new!s:<5} ({HDI_YEAR})")
    if apply:
        for path, team in updates:
            atomic_write_json(path, team)
    print(f"\n{'WROTE' if apply else 'DRY RUN'} {len(changes)} changed team(s)"
          + ("" if apply else " (pass --apply to write)"))


if __name__ == "__main__":
    main()
