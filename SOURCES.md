# Indicator Sources

This document is the canonical list of **every indicator** stored in this
repository, with a link to the original source (or source dataset) for each one.
The long-term goal is a maintainable dataset covering **all countries** and
**all indicators**, refreshable on a regular cadence. For each indicator below
you'll find: the JSON field it populates, the script that seeds it, the
authoritative source, a direct link to the source data, the reference year(s)
currently loaded, and notes on update cadence and known caveats.

> **Convention.** All values are *best-effort and accurate in scale* rather than
> authoritative — matching the rest of the dataset. Verify against the linked
> primary source before relying on any single figure. England and Scotland have
> no separate entry in most country-level indices and use **United Kingdom**
> figures as a proxy; **Curaçao** is not covered by most indices and is left
> `null`.

---

## 1. Football / squad indicators

These drive the team pages and the odds models (`scripts/odds.py`).

| Indicator | JSON field(s) | Source | Link | Year | Notes |
|---|---|---|---|---|---|
| Squad membership, position, club, club country | `squad[].name`, `squad[].position`, `squad[].club`, `squad[].club_country` | Official squad announcements, cross-checked across FIFA, ESPN, national federations, Wikipedia | [FIFA – Teams](https://www.fifa.com/fifaplus/en/tournaments/mens/worldcup/canadamexicousa2026) · [ESPN Soccer](https://www.espn.com/soccer/) · [Wikipedia: 2026 FIFA World Cup squads](https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_squads) | May–Jun 2026 | Compiled by hand; well-corroborated. |
| Player market value | `squad[].market_value_eur` | Transfermarkt (community API) | [transfermarkt.com](https://www.transfermarkt.com/) · API: [transfermarkt-api.fly.dev](https://transfermarkt-api.fly.dev) | Jun 2026 | Harvested by `scripts/harvest_market_values.py`. ~96% matched at high confidence; remainder are best-effort estimates. Values in euros (Transfermarkt convention). |
| Player age | `squad[].age` | Transfermarkt (community API) | [transfermarkt-api.fly.dev](https://transfermarkt-api.fly.dev) | Jun 2026 | Same harvester as market value. |
| Head coach | `coach` | National federation announcements / Wikipedia | [Wikipedia: 2026 FIFA World Cup](https://en.wikipedia.org/wiki/2026_FIFA_World_Cup) | 2026 | |
| FIFA / Coca-Cola World Ranking | `fifa_ranking` | FIFA Men's World Ranking | [FIFA World Ranking](https://www.fifa.com/fifa-world-ranking/men) | 2026 | |
| Group & confederation | `group`, `confederation` | FIFA official draw | [FIFA – Tournament](https://www.fifa.com/fifaplus/en/tournaments/mens/worldcup/canadamexicousa2026) | 2026 | |
| World Cup titles | `wc_titles` | FIFA World Cup records | [Wikipedia: FIFA World Cup](https://en.wikipedia.org/wiki/FIFA_World_Cup) | through 2022 | Seeded by `scripts/seed_wc_history.py`. Predecessor states folded in (West Germany → Germany, Czechoslovakia → Czechia). |
| World Cup appearances | `wc_appearances` | FIFA World Cup records | [Wikipedia: National teams' WC records](https://en.wikipedia.org/wiki/National_team_appearances_in_the_FIFA_World_Cup) | through 2022 | Seeded by `scripts/seed_wc_history.py`. |
| World Cup best finish | `wc_best_finish` | FIFA World Cup records | [Wikipedia: FIFA World Cup](https://en.wikipedia.org/wiki/FIFA_World_Cup) | through 2022 | Enum in `schema/team.schema.json`. |

---

## 2. Economic indicators

Seeded by `scripts/seed_politico_economic.py` (and `gnp_*` / `population` per the
team files). Descriptive only — **not consumed by the odds models**.

| Indicator | JSON field | Source | Source dataset (link) | Year | Notes |
|---|---|---|---|---|---|
| Gross National Income (total) | `gnp_usd` | World Bank, GNI Atlas method (current US$) | [NY.GNP.ATLS.CD](https://data.worldbank.org/indicator/NY.GNP.ATLS.CD) | 2024 | Labelled "GNP" in the dataset. England/Scotland use UK ONS regional GDP-based estimates. |
| GNI per capita | `gnp_per_capita_usd` | World Bank, GNI per capita Atlas method (current US$) | [NY.GNP.PCAP.CD](https://data.worldbank.org/indicator/NY.GNP.PCAP.CD) | 2024 | |
| Total population | `population` | World Bank | [SP.POP.TOTL](https://data.worldbank.org/indicator/SP.POP.TOTL) | mostly 2024 | ONS mid-2023 for England & Scotland; latest available for Curaçao. |
| GDP growth (annual %) | `gdp_growth_pct` | World Bank | [NY.GDP.MKTP.KD.ZG](https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG) | 2023 | |
| Inflation, consumer prices (annual %) | `inflation_pct` | World Bank | [FP.CPI.TOTL.ZG](https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG) | 2023 | |
| Unemployment (% of labour force) | `unemployment_pct` | ILO modelled estimates / World Bank | [SL.UEM.TOTL.ZS](https://data.worldbank.org/indicator/SL.UEM.TOTL.ZS) · [ILOSTAT](https://ilostat.ilo.org/data/) | 2023 | |
| Gini index | `gini_index` | World Bank | [SI.POV.GINI](https://data.worldbank.org/indicator/SI.POV.GINI) | latest available | 0–100, lower = more equal. |

---

## 3. Development & demographic indicators

| Indicator | JSON field | Source | Source dataset (link) | Year | Notes |
|---|---|---|---|---|---|
| Human Development Index | `hdi` | UNDP, Human Development Report | [UNDP HDI](https://hdr.undp.org/data-center/human-development-index) | 2022 | 0–1, higher = more developed. Also surfaced on every match card. |
| Median age | `median_age_years` | UN, World Population Prospects | [UN WPP](https://population.un.org/wpp/) | 2023 | |

---

## 4. Governance & political indicators

| Indicator | JSON field | Source | Source dataset (link) | Year | Notes |
|---|---|---|---|---|---|
| Democracy Index | `democracy_index` | Economist Intelligence Unit (EIU) | [EIU Democracy Index](https://www.eiu.com/n/campaigns/democracy-index-2023/) | 2023 | 0–10, higher = more democratic. |
| Corruption Perceptions Index | `corruption_perceptions_index` | Transparency International | [Transparency International CPI](https://www.transparency.org/en/cpi) | 2023 | 0–100, higher = cleaner. |
| Political stability (WGI) | `political_stability` | World Bank, Worldwide Governance Indicators | [World Bank WGI](https://www.worldbank.org/en/publication/worldwide-governance-indicators) | 2022 | ≈ −2.5…+2.5, higher = more stable. |
| Government effectiveness (WGI) | `government_effectiveness` | World Bank, Worldwide Governance Indicators | [World Bank WGI](https://www.worldbank.org/en/publication/worldwide-governance-indicators) | 2022 | ≈ −2.5…+2.5, higher = more effective. |

---

## 5. Society & security indicators

| Indicator | JSON field | Source | Source dataset (link) | Year | Notes |
|---|---|---|---|---|---|
| Press Freedom score | `press_freedom_score` | Reporters Without Borders (RSF), World Press Freedom Index | [RSF Index](https://rsf.org/en/index) | 2024 | 0–100, higher = freer. |
| Global Peace Index | `global_peace_index` | Institute for Economics & Peace (IEP) | [Vision of Humanity – GPI](https://www.visionofhumanity.org/maps/) | 2024 | ≈ 1–5, **lower = more peaceful**. |
| Military expenditure (% of GDP) | `military_expenditure_pct_gdp` | SIPRI Military Expenditure Database | [SIPRI](https://www.sipri.org/databases/milex) | 2023 | |

---

## 6. Match-result indicators

Per-match detail files (`data/results/matches/<id>.json`) and result files
(`data/results/<date>.json`) are compiled live during the tournament. Source
playbook, in priority order:

| Use | Source | Link | Notes |
|---|---|---|---|
| Lineups (shirt numbers), goals, subs, cards, referee, attendance | Wikipedia group pages | [2026 FIFA World Cup](https://en.wikipedia.org/wiki/2026_FIFA_World_Cup) | Primary; only reliable source for shirt numbers. May lag a few hours. |
| Team statistics (possession, shots, saves, pass accuracy) | FotMob / Opta (The Analyst) | [FotMob](https://www.fotmob.com/) · [The Analyst](https://theanalyst.com/) | For the stats block and to resolve conflicts. |
| Score, scorers, attendance, narrative | ESPN / Sky Sports | [ESPN](https://www.espn.com/soccer/) · [Sky Sports](https://www.skysports.com/football) | Quick confirmation; ESPN stat figures least consistent (tiebreaker only). |

---

## Maintaining & updating the dataset

The JSON files under `data/` are the **source of truth**. The seeders are
idempotent and dry-run by default — run without flags to preview, with `--apply`
to write:

```bash
python3 scripts/harvest_market_values.py --all --apply   # market value + age (Transfermarkt)
python3 scripts/seed_politico_economic.py --apply        # economic/political/social indicators
python3 scripts/seed_wc_history.py --apply               # World Cup history
python3 scripts/validate.py                              # enforce schema after any change
```

### Suggested refresh cadence

| Source | Typical release | Suggested refresh |
|---|---|---|
| Transfermarkt (market value, age) | Continuous | Monthly, or before/during the tournament |
| FIFA World Ranking | ~Quarterly | On each FIFA release |
| World Bank (GNI, GDP, inflation, unemployment, Gini, population) | Annual | Annual |
| UNDP HDI | Annual | Annual |
| UN World Population Prospects | Biennial | On each revision |
| EIU Democracy Index | Annual (early year) | Annual |
| Transparency International CPI | Annual (early year) | Annual |
| World Bank WGI | Annual | Annual |
| RSF World Press Freedom Index | Annual (~May) | Annual |
| IEP Global Peace Index | Annual (~mid-year) | Annual |
| SIPRI Military Expenditure | Annual (~April) | Annual |

### Toward all-country coverage

The current dataset is scoped to the 48 qualified nations. To extend toward
**all countries**:

1. The World Bank, UNDP, UN, Transparency International, RSF and SIPRI sources
   above all publish complete cross-country tables — most offer bulk
   CSV/JSON downloads or APIs (e.g. the [World Bank API](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392)),
   so a programmatic seeder can cover every country rather than the hand-curated
   table in `seed_politico_economic.py`.
2. Keep each indicator keyed by ISO country code to join sources cleanly.
3. Record the per-indicator reference year alongside each value so mixed-vintage
   data stays auditable (the dataset currently uses a single `indicators_year`
   per team — moving to per-indicator years is the natural next step).
