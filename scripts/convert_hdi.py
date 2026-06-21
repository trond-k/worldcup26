"""Convert the UNDP HDR 2025 statistical annex (Table 1) into a flat dataset.

This is a *dataset converter*, not a seeder: it reads the immutable raw source
file shipped under ``data/raw/`` and emits a normalized, diff-friendly CSV that
downstream seeders can consume. Keeping the conversion separate from seeding is
the "build from datasets" pattern -- next year, drop in ``hdi-<year>.xlsx``,
rerun this, and the seeder picks up the new values without hand-edited literals.

Source
    UNDP, Human Development Report 2025, Statistical Annex -- "Table 1. Human
    Development Index and its components". Reference year 2023.
    https://hdr.undp.org/data-center/human-development-index

    Raw file:  data/raw/hdi/hdi-2025.xlsx   (do not edit; treat as immutable)
    Output:    data/raw/hdi/hdi-2025.csv

The .xlsx is a zipped bundle of XML, so we parse it with the standard library
only (zipfile + ElementTree) -- pandas / openpyxl are not installed.

Columns emitted, one row per country (all 193, not just the 48 qualified
nations -- the converter is source-faithful; team-name mapping is the seeder's
job). Per-team consumers can also use the ``alias`` argument to ALIASES below.

    country               UNDP country name (verbatim)
    hdi                   HDI value, 2023            (0-1, higher = more developed)
    hdi_rank              HDI rank, 2023
    life_expectancy       Life expectancy at birth, years, 2023
    expected_schooling    Expected years of schooling, 2023
    mean_schooling        Mean years of schooling, 2023
    gni_per_capita_ppp    GNI per capita, 2021 PPP $, 2023

Dry-run by default (prints a preview); pass --apply to write the CSV.

    python3 scripts/convert_hdi.py            # preview
    python3 scripts/convert_hdi.py --apply    # write data/raw/hdi/hdi-2025.csv
"""

import csv
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

from common import DATA_DIR

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

RAW_DIR = os.path.join(DATA_DIR, "raw", "hdi")
XLSX_PATH = os.path.join(RAW_DIR, "hdi-2025.xlsx")
CSV_PATH = os.path.join(RAW_DIR, "hdi-2025.csv")

# Cell columns in "Table 1. HDI" -> output field. The sheet interleaves tier
# headers ("Very high human development") and footnote rows; a real data row is
# identified by an integer HDI rank in column A and an HDI value in column C.
COLUMNS = [
    ("A", "hdi_rank", int),
    ("C", "hdi", lambda v: round(float(v), 3)),
    ("E", "life_expectancy", lambda v: round(float(v), 1)),
    ("G", "expected_schooling", lambda v: round(float(v), 1)),
    ("I", "mean_schooling", lambda v: round(float(v), 1)),
    ("K", "gni_per_capita_ppp", lambda v: round(float(v))),
]
FIELDNAMES = ["country", "hdi", "hdi_rank", "life_expectancy",
              "expected_schooling", "mean_schooling", "gni_per_capita_ppp"]

# Repo team name -> UNDP country name, for the names that don't match verbatim.
# Mirrors the sovereignty notes in SOURCES.md / seed_politico_economic.py:
# England & Scotland proxy to the United Kingdom; Curacao is not covered (no
# UNDP entry) and is intentionally absent so the seeder leaves it null.
ALIASES = {
    "DR Congo": "Congo (Democratic Republic of the)",
    "IR Iran": "Iran (Islamic Republic of)",
    "South Korea": "Korea (Republic of)",
    "England": "United Kingdom",
    "Scotland": "United Kingdom",
}


def _column(ref):
    return re.match(r"([A-Z]+)\d+", ref).group(1)


def parse_table(xlsx_path):
    """Return a list of {country, hdi, ...} dicts, one per country row."""
    with zipfile.ZipFile(xlsx_path) as z:
        shared = [
            "".join(t.text or "" for t in si.iter(f"{NS}t"))
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{NS}si")
        ]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))

    rows = {}
    for c in sheet.iter(f"{NS}c"):
        ref = c.get("r")
        m = re.match(r"([A-Z]+)(\d+)", ref)
        col, row = m.group(1), int(m.group(2))
        v = c.find(f"{NS}v")
        if c.get("t") == "s" and v is not None:
            val = shared[int(v.text)]
        else:
            val = v.text if v is not None else None
        rows.setdefault(row, {})[col] = val

    records = []
    for row in sorted(rows):
        cells = rows[row]
        rank, country, hdi = cells.get("A"), cells.get("B"), cells.get("C")
        if not (country and rank and hdi and re.match(r"^\d+$", str(rank).strip())):
            continue  # tier header, footnote, or blank
        rec = {"country": country.strip()}
        for col, field, cast in COLUMNS:
            raw = cells.get(col)
            rec[field] = cast(raw) if raw not in (None, "") else None
        records.append(rec)
    return records


def main():
    apply = "--apply" in sys.argv[1:]
    if not os.path.exists(XLSX_PATH):
        sys.exit(f"missing raw source: {XLSX_PATH}")

    records = parse_table(XLSX_PATH)
    records.sort(key=lambda r: r["hdi_rank"])
    print(f"parsed {len(records)} countries from {os.path.relpath(XLSX_PATH, DATA_DIR)}")
    print(f"\n{'rank':>4}  {'country':28s} {'hdi':>5} {'life':>5} {'gni_ppp':>8}")
    for r in records[:5] + records[-3:]:
        print(f"{r['hdi_rank']:>4}  {r['country']:28s} "
              f"{r['hdi']:.3f} {r['life_expectancy']:>5} {r['gni_per_capita_ppp']:>8}")

    if not apply:
        print(f"\n(dry run) pass --apply to write {os.path.relpath(CSV_PATH, DATA_DIR)}")
        return

    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k) for k in FIELDNAMES})
    print(f"\nwrote {len(records)} rows -> {os.path.relpath(CSV_PATH, DATA_DIR)}")


if __name__ == "__main__":
    main()
