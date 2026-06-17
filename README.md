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
  favourites.md        # favourite/underdog odds models (see Favourites below)
scripts/
  validate.py          # structural validation (CI-friendly, exits non-zero on error)
  generate_markdown.py # regenerate docs/ from the JSON
  stats.py             # compute aggregate market-value stats → docs/stats.md
  generate_results.py  # results + computed standings → docs/results.md
  favourites.py        # favourite/underdog odds → docs/favourites.md
  odds.py              # the two-model odds engine (self-test: python3 scripts/odds.py)
  harvest_market_values.py  # refresh market_value_eur/age from Transfermarkt API
  seed_wc_history.py   # seed wc_* World Cup history fields on the team files
  seed_politico_economic.py  # seed political & economic indicator fields on the team files
  generate_site.py     # build the static website → site/ (see Website below)
  assets/style.css     # stylesheet for the generated site
  common.py            # shared helpers
site/                  # GENERATED, git-ignored — the static website (run generate_site.py)
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
  alongside `fifa_ranking` and squad market value feed the favourite/underdog
  odds models — see [Favourites](#favourites--odds-models) below.
- `wc_titles` / `wc_appearances` / `wc_best_finish` capture each nation's men's
  World Cup record through 2022 (predecessor states folded in, e.g. West Germany
  → Germany, Czechoslovakia → Czechia). `wc_best_finish` is one of `winners`,
  `runner-up`, `third`, `fourth`, `semi-final`, `quarter-final`, `round-16`,
  `round-32`, `group-stage`, `never-qualified`. They feed the football model's
  pedigree term and are seeded by `scripts/seed_wc_history.py`.
- **Political & economic indicators** — a descriptive country-level layer seeded
  by `scripts/seed_politico_economic.py` and surfaced in `docs/stats.md`. These
  are **purely descriptive: the odds models do not consume them.** All are
  nullable, with a single `indicators_year` recording the reference year (per-
  source years are listed in the seed script):
  - Economic: `gdp_growth_pct`, `inflation_pct`, `unemployment_pct` (all %),
    `hdi` (UNDP, 0–1), `gini_index` (0–100), `median_age_years`.
  - Political / governance: `democracy_index` (EIU, 0–10), `corruption_perceptions_index`
    (Transparency Int'l, 0–100, higher = cleaner), `political_stability` and
    `government_effectiveness` (World Bank WGI, ≈ −2.5..+2.5), `press_freedom_score`
    (RSF, 0–100), `global_peace_index` (IEP, ≈ 1–5, **lower = more peaceful**),
    `military_expenditure_pct_gdp` (SIPRI, % of GDP).
  - Sources: World Bank, UNDP, UN WPP, EIU, Transparency International, RSF, IEP
    and SIPRI (latest available, mostly 2022–2024). As with `gnp_*`, England and
    Scotland use **UK** figures as a proxy; Curaçao is not covered by these
    indices and is left `null`.

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
python3 scripts/favourites.py          # rebuild docs/favourites.md (odds models)
python3 scripts/odds.py                # run the odds-engine self-test
python3 scripts/generate_site.py       # build the static website into site/
```

Start browsing at [docs/README.md](docs/README.md).

## Website

`scripts/generate_site.py` renders the same data as a small, dependency-free
static website (minimalist documentation style — plain HTML/CSS, no JavaScript)
under `site/`:

```bash
python3 scripts/generate_site.py
open site/index.html   # macOS; or just open the file in a browser
```

The home page leads with **the day's matches** (today's fixtures, or the next
matchday), showing each team's squad value and population; CI rebuilds the site
daily so this tracks the real date during the tournament. A **Calendar** section
adds a per-matchday page (`day-<date>.html`) you can page through via a date
strip and prev/next pager. It also produces the
12 group pages, a page per team
(metadata, full squad, fixtures), aggregate **stats**, **results** with live
standings, a **Favourites** odds page, a **Methodology** page explaining how the
odds models are weighted and computed (its weight tables are generated from
`odds.CONFIG`, so they always match the live engine), and a rich detail page for
every match that has a detail file (goals, lineups, substitutions, cards, team
statistics, sources).

The generated `site/` directory is **not** committed (it is in `.gitignore`);
it is built fresh on demand and by CI. The site is published to **GitHub Pages**
by `.github/workflows/pages.yml`, which validates the data, runs the generator
and deploys `site/` on every push. To enable it for a fork, open the
repository's **Settings → Pages** and set **Source = GitHub Actions** (one-time).

## Favourites / odds models

`scripts/odds.py` turns the data into a favourite/underdog read. It runs **two
independent models**, each scoring every team 0–100, and converts a pair of team
scores into home/draw/away probabilities for a fixture. The two models are
**never blended** — the gap between them is the interesting part (a poor-but-
talented nation, or a rich one with a thin squad).

- **Football model** — squad market value (the strongest single signal), FIFA
  ranking, World Cup pedigree (`wc_*`), squad age/peak profile and depth.
- **Socio-economic model** — GNP per capita, population (talent pool), total
  GNP, the share of the squad playing abroad and in the big-5 leagues, plus a
  bump for the host nations.

Scores become odds via an Elo-style expected-score curve with a draw carved out
around even matchups; the home side gets a small venue edge when it is a host.
Every weight and constant lives in one `CONFIG` dict at the top of `odds.py`, so
the models are retuned without touching the logic. Run `python3 scripts/odds.py`
for a self-test plus a printout of the current favourites.

The odds appear on match cards and match-detail pages of the website, on a
dedicated **Favourites** page (two ranked tables side by side, plus "punching
above their weight" and talent-density highlights), and in
[docs/favourites.md](docs/favourites.md). The website also has a **Methodology**
page that surfaces the full weighting and the score → odds conversion for
readers (built straight from `odds.CONFIG`).

> These are toy estimates built from public data — illustrative only, not
> betting advice.

## Data sources & accuracy

Squad membership, clubs, coaches and groups were gathered from live web research
against the official squad announcements (late May / early June 2026), cross-
checked across FIFA, ESPN, federation announcements, Wikipedia and other
outlets. These fields are well-corroborated.

The `market_value_eur` and `age` fields are sourced from **Transfermarkt** via
the community API at `transfermarkt-api.fly.dev`, harvested by
`scripts/harvest_market_values.py` (June 2026). For each player the script
searches by name and selects the best candidate by nationality + club match;
**1087 of 1248 players (87%)** matched at high confidence on name + nationality +
club and had both `market_value_eur` and `age` written. A further **117 players**
matched on name + nationality but with a different current club (a real transfer
since this dataset's squad was compiled) — these were spot-checked (17/17 correct)
and their **`market_value_eur`** was refreshed too, bringing market-value coverage
to **1204 of 1248 (96%)**; their `age` was left on the prior estimate pending a
full re-run.

The remaining ~44 players retain the earlier **best-effort estimates** (compiled
from search summaries plus player knowledge — accurate in scale, not
authoritative). These are mostly players whose names Transfermarkt indexes under
a different transliteration than this dataset uses, so the name search returned
no result — concentrated in the Arabic-name squads (Egypt, Jordan, Qatar, Saudi
Arabia, Morocco), plus Uzbekistan and a long tail of lower-profile domestic
players. Run the harvester to see the current unmatched set:

```bash
python3 scripts/harvest_market_values.py <slug>          # dry-run one team
python3 scripts/harvest_market_values.py --all           # dry-run all 48 (~35 min)
python3 scripts/harvest_market_values.py --all --apply    # write high-confidence rows
```

The script overwrites **only** `market_value_eur` / `age` and never auto-writes a
low-confidence match, so squad lists stay untouched; `validate.py` enforces the
required format. To improve coverage further, add per-player name aliases (e.g.
correct transliterations) so the search resolves the currently-unmatched names.

The **political & economic indicators** (HDI, democracy index, corruption
perceptions, GDP growth, inflation, etc.) are seeded by
`scripts/seed_politico_economic.py` from public datasets (World Bank, UNDP, UN
WPP, EIU, Transparency International, RSF, IEP, SIPRI — latest available,
mostly 2022–2024). The per-indicator source and reference year are listed in the
script's header. Values are **best-effort and accurate in scale** rather than
authoritative; England/Scotland use UK proxies and Curaçao is left `null`. They
are descriptive only — the odds models do not use them. See `docs/stats.md` for
the rankings.

```bash
python3 scripts/seed_politico_economic.py            # preview the table
python3 scripts/seed_politico_economic.py --apply    # write the team files
```

## Contributing

The JSON files under `data/` are the source of truth — edit those, never the
generated files in `docs/`. After editing:

1. Run `python3 scripts/validate.py` and fix any reported errors.
2. Run `python3 scripts/generate_markdown.py`, `python3 scripts/stats.py`,
   `python3 scripts/generate_results.py` and `python3 scripts/favourites.py` to
   refresh the generated docs.
3. Commit both the data change and the regenerated docs.

To add new match results, edit (or create) the relevant `data/results/<date>.json`
file — set `status` to `completed` and fill in the integer scores — then
regenerate the docs. Standings update automatically.
