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
    """country -> {"hdi": float, "ppp": int|None} from the normalized CSV."""
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("country") and row.get("hdi")):
                continue
            ppp = row.get("gni_per_capita_ppp")
            out[row["country"]] = {
                "hdi": float(row["hdi"]),
                "ppp": int(ppp) if ppp else None,
            }
    return out


def with_hdi(team, hdi, ppp):
    """Return a copy with hdi/hdi_year set and gni_per_capita_ppp_usd placed next
    to the economic fields, preserving readable key order."""
    out = {}
    inserted_hdi_year = False
    for key, current in team.items():
        if key in ("hdi_year", "gni_per_capita_ppp_usd"):
            continue  # re-inserted at canonical positions below
        out[key] = current
        if key == "gnp_per_capita_usd":
            out["gni_per_capita_ppp_usd"] = ppp
        if key == "hdi":
            out[key] = hdi
            out["hdi_year"] = HDI_YEAR if hdi is not None else None
            inserted_hdi_year = True
    if "gni_per_capita_ppp_usd" not in out:
        out["gni_per_capita_ppp_usd"] = ppp
    if not inserted_hdi_year:
        out["hdi"] = hdi
        out["hdi_year"] = HDI_YEAR if hdi is not None else None
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
        rec = values.get(source_name)
        if rec is None and summary["slug"] != "curacao":
            missing.append(f"{summary['name']} -> {source_name}")
            continue
        hdi = rec["hdi"] if rec else None
        ppp = rec["ppp"] if rec else None
        old = summary.get("hdi")
        old_ppp = summary.get("gni_per_capita_ppp_usd")
        if (old != hdi or old_ppp != ppp
                or summary.get("hdi_year") != (HDI_YEAR if hdi is not None else None)):
            changes.append((summary["slug"], old, hdi, old_ppp, ppp))
            path = team_path(summary["slug"])
            updates.append((path, with_hdi(load_json(path), hdi, ppp)))

    if missing:
        sys.exit("unmatched HDI countries: " + ", ".join(missing))
    for slug, old, hdi, old_ppp, ppp in changes:
        print(f"{slug:22s} hdi {old!s:>5} -> {hdi!s:<5} | "
              f"ppp {old_ppp!s:>7} -> {ppp!s:<7} ({HDI_YEAR})")
    if apply:
        for path, team in updates:
            atomic_write_json(path, team)
    print(f"\n{'WROTE' if apply else 'DRY RUN'} {len(changes)} changed team(s)"
          + ("" if apply else " (pass --apply to write)"))


if __name__ == "__main__":
    main()
