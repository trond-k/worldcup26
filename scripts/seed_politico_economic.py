"""Seed each team's political & economic indicator fields on the team JSON files.

These are descriptive country-level fields (they are NOT consumed by the odds
models in odds.py). Each value is the nation's most recent publicly reported
figure, best-effort and accurate in scale rather than authoritative — matching
the data convention used for the squad/market-value fields (see README).

Per indicator, the source and the (latest available) reference year:

  * gdp_growth_pct                - World Bank NY.GDP.MKTP.KD.ZG       (2023)
  * inflation_pct                 - World Bank FP.CPI.TOTL.ZG          (2023)
  * unemployment_pct              - ILO modelled / World Bank          (2023)
  * hdi                           - legacy UNDP value (2022); a newer dataset-
                                    backed value from seed_hdi.py is preserved
  * gini_index                    - World Bank SI.POV.GINI (latest yr)
  * median_age_years              - UN World Population Prospects       (2023)
  * democracy_index               - EIU Democracy Index                 (2023)
  * corruption_perceptions_index  - Transparency International CPI      (2023)
  * political_stability           - World Bank WGI                      (2022)
  * government_effectiveness      - World Bank WGI                      (2022)
  * press_freedom_score           - RSF World Press Freedom Index       (2024)
  * global_peace_index            - IEP Global Peace Index (LOWER=calm) (2024)
  * military_expenditure_pct_gdp  - SIPRI                               (2023)

Sovereignty notes: England and Scotland have no separate entry in these indices,
so they use the United Kingdom value as a proxy (as gnp_* already does). Curacao
is an autonomous territory not covered by these indices and is left null.

Dry-run by default (prints a table); pass --apply to write the team JSONs.

    python3 scripts/seed_politico_economic.py            # preview
    python3 scripts/seed_politico_economic.py --apply    # write
"""

import json
import sys

from common import GROUP_LETTERS, load_tournament, team_path

# Field order as inserted into each team file (before "squad").
FIELDS = [
    "gdp_growth_pct",
    "inflation_pct",
    "unemployment_pct",
    "hdi",
    "gini_index",
    "median_age_years",
    "democracy_index",
    "corruption_perceptions_index",
    "political_stability",
    "government_effectiveness",
    "press_freedom_score",
    "global_peace_index",
    "military_expenditure_pct_gdp",
]

INDICATORS_YEAR = 2023  # most indices' latest available; per-source years above.

# slug -> values in FIELDS order. None = no reliable figure (left null).
#         gdp_g  infl   unemp  hdi    gini  medage demo  cpi  pstab  goveff press gpi   mil
DATA = {
    "mexico":             (3.2,  4.7,  2.8,  0.781, 45.4, 29.3, 5.14, 31, -0.65,  0.04, 51.4, 2.60, 0.6),
    "south-africa":       (0.6,  6.0,  32.1, 0.717, 63.0, 28.0, 7.05, 41, -0.30,  0.20, 78.1, 2.37, 0.8),
    "south-korea":        (1.4,  3.6,  2.7,  0.929, 31.4, 43.9, 8.09, 63,  0.55,  1.30, 70.0, 1.78, 2.7),
    "czechia":            (-0.3, 10.7, 2.6,  0.895, 26.2, 43.3, 7.97, 57,  0.85,  1.00, 84.0, 1.38, 1.5),
    "canada":             (1.1,  3.9,  5.4,  0.935, 31.7, 41.6, 8.69, 76,  0.95,  1.70, 83.5, 1.35, 1.3),
    "bosnia-herzegovina": (1.7,  6.1,  13.2, 0.780, 33.0, 43.3, 5.00, 35, -0.40, -0.50, 65.0, 2.07, 0.9),
    "qatar":              (1.6,  3.1,  0.1,  0.855, 41.1, 33.7, 3.65, 58,  0.90,  1.10, 41.0, 1.48, 4.0),
    "switzerland":        (0.8,  2.1,  2.0,  0.967, 33.1, 43.1, 9.14, 82,  1.30,  1.95, 89.0, 1.34, 0.7),
    "brazil":             (2.9,  4.6,  8.0,  0.760, 52.0, 33.5, 6.68, 36, -0.40, -0.10, 65.0, 2.40, 1.1),
    "morocco":            (3.0,  6.1,  13.0, 0.698, 39.5, 29.5, 5.04, 38, -0.20, -0.10, 45.0, 1.95, 4.3),
    "haiti":              (-1.9, 44.0, 15.0, 0.552, 41.1, 24.5, 2.59, 17, -1.50, -1.60, 50.0, 2.70, 0.0),
    "scotland":           (0.1,  6.8,  4.0,  0.940, 32.6, 40.5, 8.28, 71,  0.40,  1.30, 78.0, 1.60, 2.3),  # UK proxy
    "usa":                (2.5,  4.1,  3.6,  0.927, 39.8, 38.5, 7.85, 69,  0.30,  1.50, 71.2, 2.45, 3.4),
    "paraguay":           (4.5,  4.6,  5.6,  0.731, 45.1, 27.0, 6.24, 28,  0.10, -0.40, 60.0, 1.95, 0.9),
    "australia":          (2.1,  5.6,  3.7,  0.946, 34.3, 37.5, 8.66, 75,  0.95,  1.55, 79.0, 1.52, 1.9),
    "turkiye":            (4.5,  53.9, 9.4,  0.855, 41.9, 33.5, 4.33, 34, -0.95,  0.10, 41.0, 2.78, 1.5),
    "germany":            (-0.3, 6.0,  3.0,  0.950, 31.7, 45.7, 8.80, 78,  0.65,  1.45, 84.6, 1.55, 1.5),
    "curacao":            (None, None, None, None,  None, None, None, None, None, None, None, None, None),
    "cote-divoire":       (6.2,  4.4,  2.4,  0.550, 35.3, 18.9, 4.22, 40, -0.70, -0.40, 59.0, 2.20, 1.1),
    "ecuador":            (2.4,  2.2,  3.8,  0.765, 45.4, 28.8, 5.99, 34, -0.55, -0.40, 60.0, 2.40, 2.3),
    "netherlands":        (0.1,  4.1,  3.6,  0.946, 29.2, 42.8, 9.00, 79,  0.95,  1.75, 87.7, 1.40, 1.4),
    "japan":              (1.9,  3.3,  2.6,  0.920, 32.9, 49.5, 8.40, 73,  1.00,  1.55, 64.7, 1.34, 1.2),
    "sweden":             (-0.2, 8.5,  7.7,  0.952, 29.8, 41.0, 9.39, 82,  1.05,  1.80, 88.2, 1.50, 1.5),
    "tunisia":            (0.4,  9.3,  16.0, 0.732, 32.8, 33.0, 5.51, 40, -0.65,  0.00, 53.0, 2.00, 2.7),
    "belgium":            (1.5,  2.3,  5.5,  0.942, 26.6, 41.9, 7.64, 73,  0.65,  1.30, 84.0, 1.55, 1.2),
    "egypt":              (3.8,  24.4, 7.2,  0.728, 31.5, 24.6, 2.93, 35, -0.85, -0.50, 33.0, 2.35, 1.2),
    "iran":               (4.7,  40.0, 9.0,  0.780, 40.9, 33.8, 1.96, 24, -1.10, -0.60, 21.3, 2.85, 2.1),
    "new-zealand":        (0.6,  5.7,  3.7,  0.939, 33.9, 38.1, 9.61, 85,  1.30,  1.65, 84.0, 1.31, 1.5),
    "spain":              (2.5,  3.5,  12.1, 0.911, 34.3, 44.9, 8.07, 60,  0.55,  1.05, 78.0, 1.60, 1.5),
    "cabo-verde":         (5.0,  3.7,  12.0, 0.661, 42.4, 27.0, 7.65, 64,  0.85,  0.10, 78.0, 1.85, 0.5),
    "saudi-arabia":       (-0.8, 2.3,  4.9,  0.875, 45.9, 31.8, 2.08, 52, -0.30,  0.40, 28.0, 2.20, 7.1),
    "uruguay":            (0.4,  5.9,  8.3,  0.830, 40.6, 35.8, 8.66, 73,  1.00,  0.70, 80.0, 1.80, 2.0),
    "france":             (0.9,  4.9,  7.3,  0.910, 30.7, 42.6, 8.07, 71,  0.30,  1.30, 78.6, 1.65, 1.9),
    "senegal":            (4.1,  5.9,  3.0,  0.517, 38.1, 19.0, 5.96, 43, -0.20, -0.10, 62.0, 2.10, 1.5),
    "iraq":               (-2.2, 4.4,  16.5, 0.673, 29.5, 21.2, 3.13, 23, -1.40, -1.20, 41.0, 2.70, 3.5),
    "norway":             (0.5,  5.5,  3.6,  0.966, 27.7, 39.8, 9.81, 84,  1.10,  1.85, 91.9, 1.40, 1.9),
    "argentina":          (-1.6, 133.5, 6.2, 0.849, 40.7, 32.4, 6.62, 37,  0.00,  0.10, 60.0, 1.90, 0.8),
    "algeria":            (4.1,  9.3,  12.0, 0.745, 27.6, 28.9, 3.66, 36, -0.85, -0.50, 41.0, 2.30, 8.2),
    "austria":            (-0.8, 7.7,  5.1,  0.926, 30.2, 44.5, 8.20, 71,  1.00,  1.50, 80.0, 1.30, 0.8),
    "jordan":             (2.6,  2.1,  22.0, 0.736, 33.7, 24.0, 3.17, 46, -0.55,  0.10, 38.0, 1.95, 4.7),
    "portugal":           (2.3,  4.3,  6.5,  0.874, 33.5, 46.8, 7.95, 61,  1.00,  1.10, 84.0, 1.30, 1.5),
    "dr-congo":           (6.2,  19.9, 4.6,  0.481, 42.1, 16.7, 1.40, 20, -1.80, -1.50, 48.0, 3.20, 0.7),
    "uzbekistan":         (6.0,  10.0, 6.8,  0.727, 31.2, 28.6, 2.12, 33, -0.10, -0.40, 33.0, 2.05, 2.5),
    "colombia":           (0.6,  11.7, 10.2, 0.758, 54.8, 31.8, 6.55, 40, -0.80,  0.00, 56.0, 2.70, 3.4),
    "england":            (0.1,  6.8,  4.0,  0.940, 32.6, 40.5, 8.28, 71,  0.40,  1.30, 78.0, 1.60, 2.3),  # UK proxy
    "croatia":            (2.8,  8.4,  6.1,  0.878, 28.9, 44.3, 6.50, 50,  0.65,  0.55, 71.0, 1.55, 1.8),
    "ghana":              (2.9,  39.2, 4.7,  0.602, 43.5, 21.5, 6.30, 43, -0.05, -0.10, 65.0, 1.75, 0.4),
    "panama":             (7.3,  1.5,  7.4,  0.820, 48.9, 30.5, 7.18, 37,  0.20,  0.10, 70.0, 1.95, 0.0),
}


def ordered_with_indicators(team, values):
    """Return team dict with the indicator fields inserted just before squad."""
    out = {}
    for key, val in team.items():
        if key == "squad":
            for field, v in zip(FIELDS, values):
                # HDI now has its own dataset-backed refresh path. Do not regress
                # a newer value when this legacy mixed-indicator seeder is rerun.
                if field == "hdi" and team.get("hdi_year"):
                    out[field] = team.get("hdi")
                else:
                    out[field] = v
            out["indicators_year"] = None if all(v is None for v in values) else INDICATORS_YEAR
        out[key] = val
    return out


def main():
    apply = "--apply" in sys.argv[1:]
    tournament = load_tournament()
    slugs = [s for L in GROUP_LETTERS for s in tournament["groups"].get(L, [])]

    missing = [s for s in slugs if s not in DATA]
    if missing:
        sys.exit(f"no indicator data for: {', '.join(missing)}")

    # Compact preview: a representative subset of the columns.
    print(f"{'team':22s} {'hdi':>5} {'demo':>5} {'cpi':>4} {'gdp%':>6} {'infl%':>7}")
    for slug in slugs:
        values = DATA[slug]
        v = dict(zip(FIELDS, values))
        def cell(x, w, fmt):
            return (fmt % x).rjust(w) if x is not None else "—".rjust(w)
        print(f"{slug:22s} "
              f"{cell(v['hdi'], 5, '%.3f')} "
              f"{cell(v['democracy_index'], 5, '%.2f')} "
              f"{cell(v['corruption_perceptions_index'], 4, '%d')} "
              f"{cell(v['gdp_growth_pct'], 6, '%.1f')} "
              f"{cell(v['inflation_pct'], 7, '%.1f')}")
        if apply:
            path = team_path(slug)
            team = json.loads(open(path, encoding="utf-8").read())
            team = ordered_with_indicators(team, values)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(team, ensure_ascii=False, indent=2) + "\n")

    print(f"\n{'WROTE' if apply else 'DRY RUN'} {len(slugs)} teams"
          + ("" if apply else "  (pass --apply to write)"))


if __name__ == "__main__":
    main()
