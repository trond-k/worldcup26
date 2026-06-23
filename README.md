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
  raw/hdi/hdi-2025.csv       # normalized, tracked UNDP source dataset
schema/
  tournament.schema.json
  team.schema.json     # JSON Schema describing a team file
  results.schema.json  # JSON Schema describing a results file
  match-detail.schema.json  # JSON Schema describing a per-match detail file
docs/                  # GENERATED — do not edit by hand (run the scripts)
  README.md            # browsable index of all groups
  group-a.md … group-l.md
  stats.md             # market-value rankings and totals
  results.md           # match results + standings (gitignored; published via site/results.html)
  favourites.md        # favourite/underdog comparison models (see Favourites below)
scripts/
  validate.py          # structural validation (CI-friendly, exits non-zero on error)
  generate_markdown.py # regenerate docs/ from the JSON
  stats.py             # compute aggregate market-value stats → docs/stats.md
  generate_results.py  # results + computed standings → docs/results.md
  favourites.py        # model rankings → docs/favourites.md
  odds.py              # the two-model scoring engine (self-test: python3 scripts/odds.py)
  harvest.py           # harvest scores and match detail from ESPN
  harvest_market_values.py  # refresh market_value_eur/age from Transfermarkt API
  resolve_bracket.py   # resolve known knockout slots (dry-run by default)
  convert_hdi.py       # normalize the UNDP source workbook
  seed_hdi.py          # refresh team HDI from the normalized dataset
  seed_wc_history.py   # seed wc_* World Cup history fields on the team files
  seed_politico_economic.py  # seed political & economic indicator fields on the team files
  generate_site.py     # build the static website → site/ (see Website below)
  assets/style.css     # stylesheet for the generated site
  common.py            # shared helpers
site/                  # GENERATED, git-ignored — the static website (run generate_site.py)
tests/                 # standings, bracket, schema, model and source-data regressions
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
  comparison models — see [Favourites](#favourites--comparison-models) below.
- `wc_titles` / `wc_appearances` / `wc_best_finish` capture each nation's men's
  World Cup record through 2022 (predecessor states folded in, e.g. West Germany
  → Germany, Czechoslovakia → Czechia). `wc_best_finish` is one of `winners`,
  `runner-up`, `third`, `fourth`, `semi-final`, `quarter-final`, `round-16`,
  `round-32`, `group-stage`, `never-qualified`. They feed the football model's
  pedigree term and are seeded by `scripts/seed_wc_history.py`.
- `elo_rating` / `elo_rank` are the team's World Football Elo rating and world
  rank from [eloratings.net](https://www.eloratings.net/), with `elo_source` and
  `elo_harvested_at` (UTC ISO timestamp) recording provenance. `elo_rating` feeds
  the football model as a results-based strength signal; all four are harvested
  by `scripts/harvest_elo_ratings.py --apply` and may be `null` if unmatched.
- The remaining descriptive indicators are seeded by
  `scripts/seed_politico_economic.py`. Surfaced as a grouped
  Economy/Development/Governance/Society dossier on each team page, with HDI also
  shown on every match card, and documented on the site's **Methodology** page
  (sources + how to read each one). These are **purely descriptive: the
  comparison models do not consume them** — a card's HDI highlight never moves
  the percentages beside it. All are nullable. Legacy fields retain a shared `indicators_year`;
  HDI records its precise reference year in `hdi_year` (other source years are
  listed in the seed script):
  - Economic: `gdp_growth_pct`, `inflation_pct`, `unemployment_pct` (all %),
    `hdi` (UNDP, 0–1; separately refreshed by `seed_hdi.py`), `gini_index`
    (0–100), `median_age_years`.
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
- Knockout matches may add `match_number`, `decision`, `home_penalties` and
  `away_penalties`. Every match has a `kickoff_at` ISO-8601 timestamp sourced
  from FIFA's official schedule; the stored offset is Eastern Time (`-04:00`),
  matching FIFA's published schedule convention.
- Group standings exclude knockout results and use the FIFA 2026 tie-break order.
  Conduct ordering is provisional because team-official cards are not recorded.

Each completed match may also have a rich detail file at
`data/results/matches/<id>.json` (the `id` matches the match's `id` in the date
file). It holds goal scorers (with minute, type and assist), starting lineups,
substitutions, cards, team statistics, attendance and referee. All detail fields
are optional/partial — only corroborated data is included, and unknown values are
left `null`. Validation enforces that listed goals reconcile to the final score.

## Usage

The generators and harvesters use the Python standard library. Validation has
one dependency so the checked-in JSON Schemas remain authoritative:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/validate.py            # check every file is well-formed
python3 -m unittest discover -v        # run regression tests
python3 scripts/generate_markdown.py   # rebuild docs/ from the JSON
python3 scripts/stats.py               # rebuild docs/stats.md
python3 scripts/generate_results.py    # rebuild docs/results.md (results + standings)
python3 scripts/favourites.py          # rebuild docs/favourites.md (model rankings)
python3 scripts/odds.py                # run the scoring-engine self-test
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

The site is branded **Pitchonomics** (a banner above the header). The home page
leads with **the day's matches** — today's fixtures, or the next matchday,
resolved in the tournament's own timezone — showing each team's squad value and
population; CI rebuilds the site daily so this tracks the real date during the
tournament. The home page is also the calendar entry point: its matchday strip
opens per-date pages (`day-<date>.html`) with prev/next navigation. The site also
produces a full fixture list, live standings and results, a knockout bracket, an
alphabetical team index, the 12 group pages, and a page per team (metadata, full
squad, fixtures). An **Insights** hub collects **Favourites**, **Statistics** and
the **Methodology** explaining how the models are weighted and computed (its
weight tables are generated from `odds.CONFIG`, so they always match the live
engine). Rich detail pages cover every match that has a detail file (goals,
lineups, substitutions, cards, team statistics, sources).

The generated `site/` directory is **not** committed (it is in `.gitignore`);
it is built fresh on demand and by CI. The site is published to **GitHub Pages**
by `.github/workflows/pages.yml`, which validates and tests the data, refreshes
the World Football Elo ratings, validates again, and deploys `site/` on every
push (and daily). The Elo refresh is **ephemeral** — it updates the working
tree for that build only, never committed — so the published model always uses
current ratings while the repo's `elo_*` fields stay a stable seed (refresh
them in source with `harvest_elo_ratings.py --apply`). If eloratings.net is
unreachable the step is skipped and the build falls back to the committed
values. To enable Pages for a fork, open the repository's **Settings → Pages**
and set **Source = GitHub Actions** (one-time).

## Favourites / comparison models

`scripts/odds.py` turns the data into a favourite/underdog read. It runs **two
independent models**, each scoring every team 0–100, and converts a pair of team
scores into home/draw/away outlook shares for a fixture. The two models are
**never blended** — the gap between them is the interesting part (a poor-but-
talented nation, or a rich one with a thin squad).

- **Football model** — squad market value (the strongest single signal), World
  Football Elo rating (`elo_rating`), FIFA ranking, World Cup pedigree (`wc_*`),
  squad age/peak profile and depth.
- **Socio-economic model** — GNP per capita, population (talent pool), total
  GNP, the share of the squad playing abroad and in the big-5 leagues, plus a
  bump for the host nations.

Scores become heuristic outlook shares via an Elo-style expected-score curve,
with a draw carved out around even matchups; the home side gets a small venue
edge when it is a host.

Every weight and constant lives in one `CONFIG` dict at the top of `odds.py`, so
the models are retuned without touching the logic. Run `python3 scripts/odds.py`
for a self-test plus a printout of the current favourites.

The outlook appears on match cards and match-detail pages of the website, on a
dedicated **Favourites** page (two ranked tables side by side, plus "punching
above their weight" and talent-density highlights), and in
[docs/favourites.md](docs/favourites.md). The website also has a **Methodology**
page that surfaces the full weighting and the score → outlook conversion for
readers (built straight from `odds.CONFIG`).

> These are field-relative toy estimates, not calibrated probabilities or
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
mostly 2022–2024). HDI comes from the UNDP Human Development Report 2025
(reference year 2023), normalized by `convert_hdi.py` and applied by
`seed_hdi.py`; its year is stored separately as `hdi_year`. Other source years
are listed in the mixed-indicator seeder. Values are **best-effort and accurate
in scale** rather than authoritative; England/Scotland use UK proxies and
Curaçao is left `null`. They
are descriptive only — the comparison models do not use them. See `docs/stats.md` for
the rankings.

```bash
python3 scripts/seed_politico_economic.py            # preview the table
python3 scripts/seed_politico_economic.py --apply    # write the team files
python3 scripts/seed_hdi.py                           # preview current UNDP HDI
python3 scripts/seed_hdi.py --apply                   # write HDI + hdi_year
```

## Contributing

The JSON files under `data/` are the source of truth — edit those, never the
generated files in `docs/`. After editing:

1. Install `requirements.txt`, then run `python3 scripts/validate.py` and
   `python3 -m unittest discover -v`.
2. Run `python3 scripts/generate_markdown.py`, `python3 scripts/stats.py`,
   `python3 scripts/generate_results.py` and `python3 scripts/favourites.py` to
   refresh the generated docs.
3. Commit both the data change and the regenerated docs.

### Updating results during the tournament

Each matchday is updated in the same shape, so the steps are repeatable:

1. **Confirm the fixtures and what actually finished.** Late (ET) kickoffs may
   still be in progress — don't assume a scheduled match has a result yet.
2. Run `python3 scripts/harvest.py --date YYYYMMDD --dry-run`, inspect it, then
   rerun without `--dry-run`. It writes ESPN scores and detail together. Existing
   differing detail is preserved unless `--overwrite-details` is explicitly used.
3. Add or correct the human-written `venue` and `note`, corroborating conflicts
   against FIFA or another strong source. Never guess missing detail.
4. After group or knockout results settle, run `resolve_bracket.py`, then
   `resolve_bracket.py --apply` for slots it can determine. Best-third candidate
   slots remain placeholders until FIFA publishes the actual assignment.
5. **Validate and regenerate**, then commit data + regenerated docs:

   ```bash
   python3 scripts/validate.py            # enforces format + goals↔score reconciliation
   python3 scripts/generate_results.py    # docs/results.md + standings
   python3 scripts/generate_site.py       # rebuild site/ (match + day pages)
   ```

**Source playbook:**

- **ESPN JSON API** — automated source used by `harvest.py` for final scores,
  events, lineups and statistics. Its exact endpoint is stored in each detail file.
- **FIFA Match Centre** — official confirmation for fixtures and disputed results.
- **Wikipedia group pages** — useful secondary source for shirt numbers and
  lineups; may lag after a match.
- **FotMob** or **Opta / The Analyst** — for the team-stats block (possession,
  shots, saves, pass accuracy) and to resolve conflicts.
- **Sky Sports and other reporting** — narrative and conflict resolution.

Standings in `docs/results.md` are computed from completed matches, so they
update automatically once the scores are in.
