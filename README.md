# Upwork jobs data

Aggregated statistics of new Upwork job posts collected by [flconsole](https://flconsole.com).
Rates by skill, posting times by weekday and hour, client countries and categories, as plain CSV files.

**Version 2026.10** (generated 2026-10-26)

| | |
|---|---|
| Analysis window | 2026-09-14 to 2026-10-25 (42 days, 6 full weeks, UTC dates) |
| Job posts in the window | 133,568 (about 3,180 per day) |
| Skills with rates | 685 (each with at least 200 jobs in the window) |
| Skills with posting-time profiles | top 100 by volume |
| Daily counts | 2025-06-16 to 2026-10-25 (478,505 job posts in the database on 2026-10-26) |

Headline numbers for the window:

- Median hourly rate offered: **$20/h** (P25 $11, P75 $30; 49,664 jobs with an hourly range).
- Median fixed-price budget: **$100** (P25 $28, P75 $350; 53,613 jobs with a budget).
- Busiest hour: **12:00 to 13:00 US Eastern**, 191 new jobs per hour on average, 2.2 times the quietest hour (01:00 ET, 87).
- Busiest weekday: **Tuesday** (17.4% of weekly jobs); quietest: Saturday (9.3%). Weekends: 19.3%.
- Clients from the United States post 41.8% of jobs; 77.1% of jobs come from clients with a verified payment method.
- Most posted skills: Graphic Design (13,033 jobs), Video Editing (12,779), Social Media Marketing (10,357).

Interactive versions: [Upwork rates by skill](https://flconsole.com/tools/upwork-rates) and
[Best time to apply on Upwork](https://flconsole.com/tools/upwork-best-time).

## Files

All files are UTF-8 CSV with a header row. Money is in whole US dollars, shares are fractions from 0 to 1.
An empty cell means the value was suppressed (fewer than 20 jobs, see Methodology).

### `data/rates-by-skill.csv`

One row per skill with at least 200 jobs in the window, sorted by `jobs`.

| Column | Meaning |
|---|---|
| `skill` | Skill tag as shown on Upwork |
| `jobs` | Jobs with this skill in the window |
| `jobs_per_day` | `jobs` / 42 |
| `hourly_n` | Jobs with an hourly range |
| `hourly_p25`, `hourly_median`, `hourly_p75` | Percentiles of the hourly rate (midpoint of the client range) |
| `fixed_n` | Jobs with a fixed-price budget above 0 |
| `fixed_p25`, `fixed_median`, `fixed_p75` | Percentiles of the fixed-price budget |
| `us_client_share` | Share of jobs from clients in the United States |
| `payment_verified_share` | Share of jobs from clients with a verified payment method |

### `data/best-time-overall.csv`

168 rows: every weekday and hour of the week. The `et_*` columns describe that weekday and hour in
US Eastern time, the `utc_*` columns the same weekday and hour in UTC (so one row holds two different moments).

| Column | Meaning |
|---|---|
| `weekday`, `hour` | Monday to Sunday, 0 to 23 (hour 12 = 12:00 to 12:59) |
| `et_jobs`, `utc_jobs` | Jobs posted in that hour over the observed hours of the window |
| `et_hours_observed`, `utc_hours_observed` | How many times that hour was observed (6 at most, see Coverage) |
| `et_avg_jobs_per_hour`, `utc_avg_jobs_per_hour` | `jobs` / `hours_observed` |
| `et_share_of_week`, `utc_share_of_week` | The hour's average divided by the sum of all 168 averages |

### `data/best-time-by-skill.csv`

One row per skill for the 100 skills with the most jobs. A full weekday x hour grid is too sparse at the
skill level (many cells would fall under 20 jobs), so each skill gets its peaks and shares by weekday and by
4-hour block, all in US Eastern time.

| Column | Meaning |
|---|---|
| `skill`, `jobs` | As in `rates-by-skill.csv` |
| `jobs_in_observed_hours` | Jobs used for the timing columns |
| `peak_weekday_et`, `quietest_weekday_et` | Weekday with the highest and lowest average |
| `peak_hour_et` | Hour of the day (0 to 23) with the highest average |
| `share_mon` ... `share_sun`, `share_weekend` | Share of the skill's weekly jobs posted on that day |
| `share_00_04_et` ... `share_20_24_et` | Share of the skill's jobs posted in that 4-hour block of the day |

### `data/jobs-per-day.csv`

Every UTC date from 2025-06-16 to 2026-10-25.

| Column | Meaning |
|---|---|
| `date` | UTC date |
| `jobs`, `hourly_jobs`, `fixed_jobs` | Job posts that day, in total and by job type |
| `longest_gap_minutes` | Longest pause between two consecutive tracked job posts that overlaps the day |
| `in_window` | The date is inside the analysis window |
| `full_collection` | `in_window` and no pause longer than 60 minutes that day |

### `data/clients-by-country.csv`

| Column | Meaning |
|---|---|
| `client_country` | Client country as shown on the job post; countries under 20 jobs are merged into one "Other" row |
| `jobs`, `share` | Jobs in the window and share of all jobs in the window |
| `hourly_n`, `hourly_median` | Jobs with an hourly range and their median hourly rate |

### `data/categories.csv`

| Column | Meaning |
|---|---|
| `level` | `category` (a total row) or `subcategory` |
| `category`, `subcategory` | Upwork category and subcategory |
| `jobs`, `share` | Jobs in the window and share of all jobs in the window |
| `hourly_n`, `hourly_median` | Jobs with an hourly range and their median hourly rate |

Subcategories under 20 jobs are left out but stay counted in their category row.

### `data/meta.json`

Window, totals, coverage (every pause in the window), summary numbers, definitions and row counts per file.

## Methodology

- **Source.** New public Upwork job posts tracked by flconsole. Each post is counted once.
- **Time.** Every job is placed at its Upwork publish time (UTC). US Eastern times use America/New_York;
  the whole window falls in daylight saving time (UTC-4).
- **Hourly rate.** The midpoint of the client's hourly range, `(from + to) / 2`, or the upper bound when only
  that is given. Jobs without a range are not in the hourly columns. This is the rate the client offers,
  not what the contract ended up paying. Percentiles are continuous (`percentile_cont`).
- **Skills.** A job tagged with several skills counts once for each of them, so skill counts add up to more than
  the number of jobs. 131,274 of the 133,568 jobs in the window have at least one skill tag.
- **Suppression.** Any count under 20 is left empty, and so is any percentile, median or share computed from
  under 20 jobs. This keeps small, noisy samples out and avoids pointing at individual clients.
- **No row-level data.** The files contain aggregates only: no job titles, descriptions, links or client details.

### Window and coverage

Tracking started on 2025-06-16 but was partial until September 2026: before 2026-09-10 the daily volume is
roughly a third of today's, and 2026-09-07 to 2026-09-13 have long pauses. All rates, shares and timing figures
therefore use only **2026-09-14 to 2026-10-25**, six full weeks in which every weekday occurs six times.

Inside the window there were 11 pauses longer than 60 minutes (the longest about 6 hours; all listed in
`meta.json`). Rates and shares use every job in the window. The timing files drop the 34 hours (of 1,008)
that fall mostly inside a pause and divide by the hours actually observed, so a pause does not make an hour look
quieter. Earlier dates in `jobs-per-day.csv` are kept for reference; do not compare their volume with the window.

These are jobs tracked by flconsole, not every job on Upwork, so treat counts as relative (which skill, hour or
country is bigger) rather than as the absolute size of the marketplace.

## Updates

Refreshed monthly. Each release moves the window forward and records its version and dates in `meta.json`.
`scripts/export.py` regenerates every file from the database.

## How to cite

> flconsole, Upwork jobs data, October 2026, https://flconsole.com

Please link to https://flconsole.com when you use the data.

## License

[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): you may share and adapt the data for any purpose,
including commercially, as long as you give credit. See [LICENSE](LICENSE).
