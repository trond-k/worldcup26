# World Cup 2026 — Teams, Groups & Players

A structured dataset of the **2026 FIFA World Cup** (hosted by Canada, Mexico and
the United States): all 48 qualified teams organized into the 12 groups (A–L),
with a full 26-player squad for each team listing **position**, **club** and
**assumed market value**.

> ⚠️ **Data accuracy:** Squads, clubs and market values are compiled from public
> web sources (FIFA, ESPN, Wikipedia, Transfermarkt-style market valuations) and
> are **best-effort**. Market values are expressed in euros following the
> Transfermarkt convention. Verify against a primary source before relying on
> this data, and see *Contributing* below to submit corrections.

## Layout

```
data/
  tournament.json      # hosts, dates, format, and the group → team index
  teams/<slug>.json    # one file per team: metadata + 26-man squad (source of truth)
  results/<date>.json  # one file per matchday date: match results (source of truth)
  results/matches/<id>.json  # rich per-match detail: goals, lineups, subs, cards, stats
schema/
  tournament.schema.json
  team.schema.json     # JSON Schema describing a team file
  results.schema.json  # JSON Schema describing a results file
  match-detail.schema.json  # JSON Schema describing a per-match detail file
docs/                  # GENERATED — do not edit by hand (run the scripts)
  README.md            # browsable index of all groups
  group-a.md … group-l.md
  stats.md             # market-value rankings and totals
  results.md           # match results and live group standings
scripts/
  validate.py          # structural validation (CI-friendly, exits non-zero on error)
  generate_markdown.py # regenerate docs/ from the JSON
  stats.py             # compute aggregate market-value stats → docs/stats.md
  generate_results.py  # results + computed standings → docs/results.md
  common.py            # shared helpers
```

## Data model

Each `data/teams/<slug>.json` file:

```json
{
  "name": "Argentina",
  "slug": "argentina",
  "confederation": "CONMEBOL",
  "group": "J",
  "fifa_ranking": 1,
  "coach": "Lionel Scaloni",
  "gnp_usd": 640000000000,
  "gnp_per_capita_usd": 13900,
  "gnp_year": 2024,
  "squad": [
    {
      "name": "Lionel Messi",
      "position": "FW",
      "club": "Inter Miami",
      "club_country": "USA",
      "age": 38,
      "market_value_eur": 18000000
    }
  ]
}
```

- `position` is one of `GK`, `DF`, `MF`, `FW`.
- `market_value_eur` is a non-negative integer (euros).
- `squad` must contain exactly 26 players.
- `gnp_usd` / `gnp_per_capita_usd` are the country's Gross National Product
  (World Bank GNI — total and per-capita Atlas method — in current US dollars,
  integers), with `gnp_year` the data year. England and Scotland have no
  separate World Bank entry, so they use UK ONS regional GDP-based estimates
  (flagged in commit history); `gnp_*` may be `null` if unavailable. See
  `docs/stats.md` for the economy rankings.
- `population` / `population_year` are the country's total population (World Bank
  estimates, mostly 2024; ONS mid-2023 for England and Scotland; latest available
  year for Curaçao). These socio-economic fields (GNP, GNP per capita, population)
  alongside `fifa_ranking` and squad market value are intended as inputs to a
  favourite/underdog estimate for matches.

Each `data/results/<date>.json` file holds the matches played (or scheduled) on
that date:

```json
{
  "date": "2026-06-11",
  "matches": [
    {
      "stage": "group",
      "group": "A",
      "matchday": 1,
      "home": "mexico",
      "away": "south-africa",
      "home_score": 2,
      "away_score": 0,
      "status": "completed",
      "venue": "Estadio Azteca, Mexico City",
      "note": "Tournament opener."
    }
  ]
}
```

- `home` / `away` reference team slugs; group matches must use teams from that group.
- `status` is `completed` (integer scores) or `scheduled` (null scores).
- Group standings in `docs/results.md` are computed from completed matches.

Each completed match may also have a rich detail file at
`data/results/matches/<id>.json` (the `id` matches the match's `id` in the date
file). It holds goal scorers (with minute, type and assist), starting lineups,
substitutions, cards, team statistics, attendance and referee. All detail fields
are optional/partial — only corroborated data is included, and unknown values are
left `null`. Validation enforces that listed goals reconcile to the final score.

## Usage

All scripts use only the Python 3 standard library (no dependencies):

```bash
python3 scripts/validate.py            # check every file is well-formed
python3 scripts/generate_markdown.py   # rebuild docs/ from the JSON
python3 scripts/stats.py               # rebuild docs/stats.md
python3 scripts/generate_results.py    # rebuild docs/results.md (results + standings)
```

Start browsing at [docs/README.md](docs/README.md).

## Data sources & accuracy

Squad membership, clubs, coaches and groups were gathered from live web research
against the official squad announcements (late May / early June 2026), cross-
checked across FIFA, ESPN, federation announcements, Wikipedia and other
outlets. These fields are well-corroborated.

The `market_value_eur` and `age` fields are **Transfermarkt-style estimates**,
not values read directly from a structured source. An attempt was made to pull
exact figures programmatically, but the build environment enforces a **network
egress allowlist** that blocked every candidate source — Transfermarkt, the
community Transfermarkt APIs, and Wikipedia/Wikidata all returned `HTTP 403`
through both direct HTTP requests and the fetch tooling. The only working web
channel was keyword search, which returns result snippets rather than full pages
or JSON. Values were therefore assembled from search summaries plus knowledge of
each player and are accurate in scale/ballpark but not authoritative; the least
certain are lower-profile players from domestic leagues (e.g. parts of the
Tunisia, Jordan, Qatar and Cabo Verde squads).

To refresh these fields with exact data in future, add the relevant data-source
hosts to the environment's network egress allowlist, then fetch values in bulk
and overwrite only `market_value_eur` / `age` — `validate.py` already enforces
the required format, so the squad lists can stay untouched.

## Contributing

The JSON files under `data/` are the source of truth — edit those, never the
generated files in `docs/`. After editing:

1. Run `python3 scripts/validate.py` and fix any reported errors.
2. Run `python3 scripts/generate_markdown.py`, `python3 scripts/stats.py` and
   `python3 scripts/generate_results.py` to refresh the generated docs.
3. Commit both the data change and the regenerated docs.

To add new match results, edit (or create) the relevant `data/results/<date>.json`
file — set `status` to `completed` and fill in the integer scores — then
regenerate the docs. Standings update automatically.
