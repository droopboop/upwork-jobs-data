#!/usr/bin/env python3
"""Regenerate every file in data/ from the jobs database.

Read-only and aggregates only: the session is READ ONLY, and no job titles, descriptions, URLs or client
identifiers are ever selected. Any count below --suppress (default 20) is written as an empty cell.

Usage:
  export UPWORK_DB_URL=postgresql://...        # connection string, kept out of this repo
  pip install psycopg2-binary
  python scripts/export.py --start 2026-09-14 --end 2026-10-25 --version 2026.10

--start / --end are inclusive UTC dates of the analysis window (the fully collected period).
jobs-per-day.csv always covers the whole history up to --end.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
ET = ZoneInfo('America/New_York')
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
BLOCKS = ['00-04', '04-08', '08-12', '12-16', '16-20', '20-24']

# Hourly rate of a job = midpoint of the client's range; only the upper bound if that is all there is.
MID = """case when hourly_rate_from > 0 and hourly_rate_to > 0 then (hourly_rate_from + hourly_rate_to) / 2.0
              when hourly_rate_to > 0 then hourly_rate_to end"""
W = "publish_at >= %(start)s and publish_at < %(stop)s"

# Some client countries arrive as ISO-3 codes; merge them with the full names.
ISO3 = {
    'USA': 'United States', 'GBR': 'United Kingdom', 'CAN': 'Canada', 'AUS': 'Australia', 'IND': 'India',
    'PAK': 'Pakistan', 'ARE': 'United Arab Emirates', 'DEU': 'Germany', 'NLD': 'Netherlands', 'PHL': 'Philippines',
    'FRA': 'France', 'NGA': 'Nigeria', 'SAU': 'Saudi Arabia', 'ESP': 'Spain', 'ITA': 'Italy', 'IRL': 'Ireland',
    'NZL': 'New Zealand', 'SGP': 'Singapore', 'ISR': 'Israel', 'CHE': 'Switzerland', 'SWE': 'Sweden',
    'BEL': 'Belgium', 'DNK': 'Denmark', 'NOR': 'Norway', 'POL': 'Poland', 'ZAF': 'South Africa', 'BRA': 'Brazil',
    'MEX': 'Mexico', 'BGD': 'Bangladesh', 'EGY': 'Egypt', 'KEN': 'Kenya', 'HKG': 'Hong Kong', 'JPN': 'Japan',
    'KOR': 'South Korea', 'MYS': 'Malaysia', 'IDN': 'Indonesia', 'VNM': 'Vietnam', 'TUR': 'Turkey', 'UKR': 'Ukraine',
    'AUT': 'Austria', 'PRT': 'Portugal', 'QAT': 'Qatar', 'KWT': 'Kuwait', 'LKA': 'Sri Lanka', 'NPL': 'Nepal',
    'CHN': 'China', 'TWN': 'Taiwan', 'ARG': 'Argentina', 'COL': 'Colombia', 'CHL': 'Chile', 'FIN': 'Finland',
    'CZE': 'Czech Republic', 'ROU': 'Romania', 'GRC': 'Greece', 'HUN': 'Hungary', 'EST': 'Estonia', 'CYP': 'Cyprus',
    'MAR': 'Morocco', 'JOR': 'Jordan', 'OMN': 'Oman', 'BHR': 'Bahrain', 'LUX': 'Luxembourg', 'MLT': 'Malta',
    'SVN': 'Slovenia', 'LTU': 'Lithuania', 'LVA': 'Latvia', 'THA': 'Thailand', 'PER': 'Peru', 'BGR': 'Bulgaria',
    'GEO': 'Georgia', 'LBN': 'Lebanon', 'KAZ': 'Kazakhstan', 'PAN': 'Panama', 'ETH': 'Ethiopia', 'MDA': 'Moldova',
    'HRV': 'Croatia', 'SRB': 'Serbia', 'SVK': 'Slovakia', 'ARM': 'Armenia', 'AZE': 'Azerbaijan', 'UZB': 'Uzbekistan',
    'DZA': 'Algeria', 'TUN': 'Tunisia', 'GHA': 'Ghana', 'TZA': 'Tanzania', 'UGA': 'Uganda', 'RWA': 'Rwanda',
    'ZMB': 'Zambia', 'ZWE': 'Zimbabwe', 'CMR': 'Cameroon', 'CRI': 'Costa Rica', 'DOM': 'Dominican Republic',
    'ECU': 'Ecuador', 'URY': 'Uruguay', 'VEN': 'Venezuela', 'SLV': 'El Salvador', 'JAM': 'Jamaica', 'PRI': 'Puerto Rico',
    'ISL': 'Iceland', 'ALB': 'Albania', 'BIH': 'Bosnia and Herzegovina', 'MNE': 'Montenegro', 'MKD': 'North Macedonia',
    'KHM': 'Cambodia', 'MUS': 'Mauritius', 'TTO': 'Trinidad and Tobago', 'BHS': 'Bahamas', 'HTI': 'Haiti',
    'CYM': 'Cayman Islands', 'SOM': 'Somalia', 'YEM': 'Yemen', 'IRQ': 'Iraq', 'MMR': 'Myanmar', 'GTM': 'Guatemala',
    'HND': 'Honduras', 'NIC': 'Nicaragua', 'BOL': 'Bolivia', 'PRY': 'Paraguay', 'BLR': 'Belarus', 'RUS': 'Russia',
    'Macedonia': 'North Macedonia',
}
COUNTRY = """coalesce(m.name, nullif(trim(j.cl_country), ''), '(not specified)')"""

SQL = {
    'totals': """select count(*) all_rows, count(publish_at) with_time, min(publish_at) first, max(publish_at) last
        from db_models_jobpost""",
    # Whole history by UTC date, with the longest pause between two consecutive new jobs that overlaps the day.
    'per_day': """with x as (select publish_at t, job_type, lag(publish_at) over (order by publish_at) p
          from db_models_jobpost where publish_at is not null and publish_at < %(stop)s),
        d as (select (t at time zone 'UTC')::date d, count(*) n,
            count(*) filter (where job_type ilike 'hourly%%') hourly_n,
            count(*) filter (where job_type ilike 'fixed%%') fixed_n
          from x group by 1),
        g as (select s::date d, max(extract(epoch from t - p) / 60) max_gap from x,
            generate_series((p at time zone 'UTC')::date, (t at time zone 'UTC')::date, interval '1 day') s
          where p is not null group by 1)
        select d, coalesce(n, 0) n, coalesce(hourly_n, 0) hourly_n, coalesce(fixed_n, 0) fixed_n, max_gap
        from d full join g using (d) order by 1""",
    # Pauses longer than --gap-minutes inside the window (used to drop those hours from timing stats).
    'gaps': f"""with x as (select publish_at t, lag(publish_at) over (order by publish_at) p
          from db_models_jobpost where publish_at >= %(start)s - interval '1 day' and publish_at < %(stop)s + interval '1 day')
        select p, t from x where t - p > %(gap)s * interval '1 minute' and t > %(start)s and p < %(stop)s order by p""",
    'hours': f"""select date_trunc('hour', publish_at) h, count(*) n from db_models_jobpost where {W} group by 1""",
    'overall': f"""select count(*) n, count(*) filter (where job_type ilike 'hourly%%') hourly_type_n,
          count({MID}) hourly_n,
          percentile_cont(array[0.25, 0.5, 0.75]) within group (order by {MID}) hourly_q,
          count(*) filter (where fixed_budget > 0) fixed_n,
          percentile_cont(array[0.25, 0.5, 0.75]) within group (order by fixed_budget) filter (where fixed_budget > 0) fixed_q,
          avg(case when cl_country in ('United States', 'USA') then 1 else 0 end) us_share,
          avg(case when cl_payment_verified then 1 else 0 end) verified_share
        from db_models_jobpost where {W}""",
    'skills': f"""with js as (select s.name skill, j.* from db_models_jobpost j
          join db_models_jobpost_skills k on k.jobpost_id = j.id join db_models_skill s on s.id = k.skill_id
          where j.{W.replace(' and publish_at', ' and j.publish_at')})
        select skill, count(*) n,
          count({MID}) hourly_n,
          percentile_cont(array[0.25, 0.5, 0.75]) within group (order by {MID}) hourly_q,
          count(*) filter (where fixed_budget > 0) fixed_n,
          percentile_cont(array[0.25, 0.5, 0.75]) within group (order by fixed_budget) filter (where fixed_budget > 0) fixed_q,
          avg(case when cl_country in ('United States', 'USA') then 1 else 0 end) us_share,
          avg(case when cl_payment_verified then 1 else 0 end) verified_share
        from js group by 1 having count(*) >= %(min)s order by 2 desc, 1""",
    'skill_hours': f"""select s.name skill, date_trunc('hour', j.publish_at) h, count(*) n from db_models_jobpost j
          join db_models_jobpost_skills k on k.jobpost_id = j.id join db_models_skill s on s.id = k.skill_id
          where j.{W.replace(' and publish_at', ' and j.publish_at')} and s.name = any(%(skills)s) group by 1, 2""",
    'skills_any': f"""select count(distinct j.id) n from db_models_jobpost j
          join db_models_jobpost_skills k on k.jobpost_id = j.id where j.{W.replace(' and publish_at', ' and j.publish_at')}""",
    'countries': f"""with m as (select * from unnest(%(codes)s::text[], %(names)s::text[]) as m(code, name))
        select {COUNTRY} country, count(*) n, count({MID}) hourly_n,
          percentile_cont(0.5) within group (order by {MID}) hourly_median
        from db_models_jobpost j left join m on m.code = j.cl_country where j.{W.replace(' and publish_at', ' and j.publish_at')}
        group by 1 order by 2 desc, 1""",
    'categories': f"""with x as (select coalesce(p.name, c.name, '(none)') category,
            case when p.id is not null then c.name end subcategory, {MID.replace('hourly_', 'j.hourly_')} mid
          from db_models_jobpost j left join db_models_jobcategory c on c.id = j.category_id
          left join db_models_jobcategory p on p.id = c.parent_category_id
          where j.{W.replace(' and publish_at', ' and j.publish_at')})
        select category, subcategory, grouping(subcategory) is_total, count(*) n, count(mid) hourly_n,
          percentile_cont(0.5) within group (order by mid) hourly_median
        from x group by grouping sets ((category), (category, subcategory)) order by 1, 3 desc, 4 desc""",
}


def num(x, nd=0):
    """Whole dollars (as on flconsole.com) or a rounded share; None stays empty."""
    if x is None:
        return None
    return round(float(x), nd) if nd else int(round(float(x)))


class Suppress:
    def __init__(self, k: int):
        self.k = k

    def n(self, n):
        """A count below the threshold becomes an empty cell (0 stays 0)."""
        return n if n == 0 or n >= self.k else None

    def q(self, n, value, nd=0):
        """A statistic is only published when it rests on at least k jobs."""
        return num(value, nd) if n >= self.k else None


def write_csv(path: str, header: list, rows: list) -> int:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(header)
        for r in rows:
            w.writerow(['' if v is None else ('true' if v is True else 'false' if v is False else v) for v in r])
    return len(rows)


def covered_hours(start: dt.datetime, stop: dt.datetime, gaps: list) -> tuple[list, float]:
    """UTC hours of the window that are not mostly (>= 30 min) inside a pause in collection."""
    hours, t = [], start
    lost = 0.0
    while t < stop:
        e = t + dt.timedelta(hours=1)
        inside = sum(max(0.0, (min(e, b) - max(t, a)).total_seconds()) for a, b in gaps)
        if inside < 1800:
            hours.append(t)
        else:
            lost += 1
        t = e
    return hours, lost


def grid(counts: dict, hours: list, tz) -> tuple[list, list]:
    """Weekday x hour (local to tz): jobs and number of observed hours per cell, index = weekday * 24 + hour."""
    n, occ = [0] * 168, [0] * 168
    for h in hours:
        lt = h.astimezone(tz)
        i = lt.weekday() * 24 + lt.hour
        occ[i] += 1
        n[i] += counts.get(h, 0)
    return n, occ


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True, help='first UTC date of the window (inclusive)')
    ap.add_argument('--end', required=True, help='last UTC date of the window (inclusive)')
    ap.add_argument('--version', required=True)
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data'))
    ap.add_argument('--min-skill', type=int, default=200, help='skills with fewer jobs in the window are left out')
    ap.add_argument('--top', type=int, default=100, help='skills in best-time-by-skill.csv')
    ap.add_argument('--suppress', type=int, default=20)
    ap.add_argument('--gap-minutes', type=int, default=60)
    a = ap.parse_args()
    import psycopg2
    import psycopg2.extras
    url = os.environ.get('UPWORK_DB_URL')
    if not url:
        sys.exit('UPWORK_DB_URL is not set')
    start = dt.datetime.fromisoformat(a.start).replace(tzinfo=UTC)
    stop = dt.datetime.fromisoformat(a.end).replace(tzinfo=UTC) + dt.timedelta(days=1)
    days = (stop - start).days
    S = Suppress(a.suppress)
    p = {'start': start, 'stop': stop, 'min': a.min_skill, 'gap': a.gap_minutes,
         'codes': list(ISO3), 'names': list(ISO3.values())}
    conn = psycopg2.connect(url)
    conn.set_session(readonly=True)
    q = {}
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for k in ('totals', 'per_day', 'gaps', 'hours', 'overall', 'skills', 'skills_any', 'countries', 'categories'):
            cur.execute(SQL[k], p)
            q[k] = cur.fetchall()
        top = [x['skill'] for x in q['skills'][:a.top]]
        cur.execute(SQL['skill_hours'], {**p, 'skills': top})
        q['skill_hours'] = cur.fetchall()
    conn.close()
    os.makedirs(a.out, exist_ok=True)
    out = lambda name: os.path.join(a.out, name)  # noqa: E731
    files = {}
    total = q['overall'][0]['n']

    # jobs-per-day.csv — whole history.
    gaps = [(g['p'], g['t']) for g in q['gaps']]
    seen = {r['d']: r for r in q['per_day']}
    rows, d = [], min(seen)
    while d < stop.date():
        r = seen.get(d, {'n': 0, 'hourly_n': 0, 'fixed_n': 0, 'max_gap': None})
        in_window = start.date() <= d < stop.date()
        gap = None if r['max_gap'] is None else int(round(float(r['max_gap'])))
        rows.append([d.isoformat(), S.n(r['n']), S.n(r['hourly_n']), S.n(r['fixed_n']), gap,
                     in_window, in_window and gap is not None and gap <= a.gap_minutes])
        d += dt.timedelta(days=1)
    files['jobs-per-day.csv'] = write_csv(out('jobs-per-day.csv'), [
        'date', 'jobs', 'hourly_jobs', 'fixed_jobs', 'longest_gap_minutes', 'in_window', 'full_collection'], rows)

    # rates-by-skill.csv
    rows = []
    for x in q['skills']:
        hq, fq = x['hourly_q'] or [None] * 3, x['fixed_q'] or [None] * 3
        rows.append([x['skill'], x['n'], round(x['n'] / days, 1), x['hourly_n'],
                     *(S.q(x['hourly_n'], v) for v in hq), x['fixed_n'], *(S.q(x['fixed_n'], v) for v in fq),
                     num(x['us_share'], 4), num(x['verified_share'], 4)])
    files['rates-by-skill.csv'] = write_csv(out('rates-by-skill.csv'), [
        'skill', 'jobs', 'jobs_per_day', 'hourly_n', 'hourly_p25', 'hourly_median', 'hourly_p75',
        'fixed_n', 'fixed_p25', 'fixed_median', 'fixed_p75', 'us_client_share', 'payment_verified_share'], rows)

    # best-time-overall.csv — weekday x hour, ET columns and UTC columns (each local to its own zone).
    hours, lost = covered_hours(start, stop, gaps)
    counts = {r['h']: r['n'] for r in q['hours']}
    covered_jobs = sum(counts.get(h, 0) for h in hours)

    def cells(tz):
        n, occ = grid(counts, hours, tz)
        avg = [c / o if o else 0.0 for c, o in zip(n, occ)]
        s = sum(avg) or 1
        return n, occ, avg, [v / s for v in avg]
    et, utc = cells(ET), cells(UTC)
    rows = []
    for i in range(168):
        rows.append([DAYS[i // 24], i % 24,
                     S.n(et[0][i]), et[1][i], S.q(et[0][i], et[2][i], 1), S.q(et[0][i], et[3][i], 5),
                     S.n(utc[0][i]), utc[1][i], S.q(utc[0][i], utc[2][i], 1), S.q(utc[0][i], utc[3][i], 5)])
    files['best-time-overall.csv'] = write_csv(out('best-time-overall.csv'), [
        'weekday', 'hour', 'et_jobs', 'et_hours_observed', 'et_avg_jobs_per_hour', 'et_share_of_week',
        'utc_jobs', 'utc_hours_observed', 'utc_avg_jobs_per_hour', 'utc_share_of_week'], rows)
    et_hour = [sum(et[2][d * 24 + h] for d in range(7)) for h in range(24)]
    et_day = [sum(et[2][d * 24:(d + 1) * 24]) for d in range(7)]

    # best-time-by-skill.csv — top skills: peak day/hour (ET) and shares by weekday and 4-hour block.
    by_skill = {}
    for r in q['skill_hours']:
        by_skill.setdefault(r['skill'], {})[r['h']] = r['n']
    rows = []
    jobs_of = {x['skill']: x['n'] for x in q['skills']}
    for s in top:
        n, occ = grid(by_skill.get(s, {}), hours, ET)
        avg = [c / o if o else 0.0 for c, o in zip(n, occ)]
        tot = sum(avg) or 1
        day_n = [sum(n[d * 24:(d + 1) * 24]) for d in range(7)]
        day_a = [sum(avg[d * 24:(d + 1) * 24]) for d in range(7)]
        hr_a = [sum(avg[d * 24 + h] for d in range(7)) for h in range(24)]
        blk_n = [sum(n[d * 24 + h] for d in range(7) for h in range(b * 4, b * 4 + 4)) for b in range(6)]
        blk_a = [sum(hr_a[b * 4:b * 4 + 4]) for b in range(6)]
        rows.append([s, jobs_of[s], sum(n), DAYS[day_a.index(max(day_a))], hr_a.index(max(hr_a)),
                     DAYS[day_a.index(min(day_a))],
                     *(S.q(day_n[d], day_a[d] / tot, 4) for d in range(7)),
                     S.q(day_n[5] + day_n[6], (day_a[5] + day_a[6]) / tot, 4),
                     *(S.q(blk_n[b], blk_a[b] / tot, 4) for b in range(6))])
    files['best-time-by-skill.csv'] = write_csv(out('best-time-by-skill.csv'), [
        'skill', 'jobs', 'jobs_in_observed_hours', 'peak_weekday_et', 'peak_hour_et', 'quietest_weekday_et',
        *(f'share_{d[:3].lower()}' for d in DAYS), 'share_weekend',
        *(f'share_{b.replace("-", "_")}_et' for b in BLOCKS)], rows)

    # clients-by-country.csv — countries under the threshold go into one "Other" row.
    rows, other = [], {'n': 0, 'k': 0}
    for x in q['countries']:
        if x['n'] >= a.suppress:
            rows.append([x['country'], x['n'], round(x['n'] / total, 4), x['hourly_n'],
                         S.q(x['hourly_n'], x['hourly_median'])])
        else:
            other['n'] += x['n']
            other['k'] += 1
    rows.sort(key=lambda r: (-r[1], r[0]))
    if other['n']:
        rows.append([f"Other ({other['k']} countries with fewer than {a.suppress} jobs each)", S.n(other['n']),
                     S.q(other['n'], other['n'] / total, 4), None, None])
    files['clients-by-country.csv'] = write_csv(out('clients-by-country.csv'), [
        'client_country', 'jobs', 'share', 'hourly_n', 'hourly_median'], rows)

    # categories.csv — one "category" row per category, then its subcategories.
    rows = []
    small = {}
    for x in q['categories']:
        if x['is_total']:
            rows.append(['category', x['category'], None, S.n(x['n']), S.q(x['n'], x['n'] / total, 4),
                         x['hourly_n'], S.q(x['hourly_n'], x['hourly_median'])])
        elif x['subcategory'] is None:
            continue  # jobs filed directly under a top-level category; counted in its category row
        elif x['n'] >= a.suppress:
            rows.append(['subcategory', x['category'], x['subcategory'], x['n'], round(x['n'] / total, 4),
                         x['hourly_n'], S.q(x['hourly_n'], x['hourly_median'])])
        else:
            small[x['category']] = small.get(x['category'], 0) + x['n']
    cat_n = {r[1]: r[3] or 0 for r in rows if r[0] == 'category'}
    rows.sort(key=lambda r: (-cat_n.get(r[1], 0), r[1], r[0] != 'category', -(r[3] or 0), r[2] or ''))
    files['categories.csv'] = write_csv(out('categories.csv'), [
        'level', 'category', 'subcategory', 'jobs', 'share', 'hourly_n', 'hourly_median'], rows)

    o = q['overall'][0]
    t = q['totals'][0]
    hq, fq = o['hourly_q'], o['fixed_q']
    full_days = sum(1 for r in csv.reader(open(out('jobs-per-day.csv'))) if r[-1] == 'true')
    meta = {
        'name': 'Upwork jobs data by flconsole',
        'version': a.version,
        'generated_at': dt.datetime.now(UTC).replace(microsecond=0).isoformat(),
        'source': 'New public Upwork job posts tracked by flconsole (https://flconsole.com)',
        'license': 'CC BY 4.0',
        'window': {'start': start.date().isoformat(), 'end': (stop - dt.timedelta(days=1)).date().isoformat(),
                   'days': days, 'timezone': 'UTC dates; timing files also in America/New_York'},
        'totals': {
            'jobs_in_window': total,
            'jobs_in_database_with_publish_time': t['with_time'],
            'first_job_in_database': t['first'].astimezone(UTC).date().isoformat(),
            'jobs_per_day_in_window': round(total / days, 1),
            'jobs_with_skills_in_window': q['skills_any'][0]['n'],
            'skills_in_rates_file': len(q['skills']),
            'skills_in_best_time_file': len(top),
        },
        'coverage': {
            'gap_threshold_minutes': a.gap_minutes,
            'pauses_in_window': [{'start': g0.astimezone(UTC).isoformat(timespec='minutes'),
                                  'end': g1.astimezone(UTC).isoformat(timespec='minutes')} for g0, g1 in gaps],
            'hours_excluded_from_timing_files': int(lost),
            'hours_in_window': days * 24,
            'jobs_in_observed_hours': covered_jobs,
            'window_days_without_pauses': full_days,
        },
        'summary': {
            'hourly_rate_jobs': o['hourly_n'],
            'hourly_rate_p25_median_p75_usd': [num(v) for v in hq],
            'fixed_budget_jobs': o['fixed_n'],
            'fixed_budget_p25_median_p75_usd': [num(v) for v in fq],
            'hourly_job_type_share': round(o['hourly_type_n'] / total, 4),
            'us_client_share': num(o['us_share'], 4),
            'payment_verified_share': num(o['verified_share'], 4),
            'busiest_hour_et': et_hour.index(max(et_hour)),
            'quietest_hour_et': et_hour.index(min(et_hour)),
            'busiest_weekday_et': DAYS[et_day.index(max(et_day))],
            'quietest_weekday_et': DAYS[et_day.index(min(et_day))],
            'busiest_hour_vs_quietest_hour': round(max(et_hour) / min(et_hour), 2),
            'weekend_share_of_week_et': round((et_day[5] + et_day[6]) / sum(et_day), 4),
        },
        'definitions': {
            'job': 'One new job post, counted once, at its Upwork publish time (UTC).',
            'hourly_rate': 'Midpoint of the client hourly range ((from + to) / 2); the upper bound when only it is '
                           'given. Jobs without a range are not in hourly_* columns. Whole USD.',
            'fixed_budget': 'Fixed-price budget in USD, jobs with a budget above 0. Whole USD.',
            'percentiles': 'Continuous percentiles (PostgreSQL percentile_cont).',
            'skill': 'Skill tags on the post; a job with several skills counts once for each.',
            'us_client_share': 'Share of jobs whose client country is the United States.',
            'payment_verified_share': 'Share of jobs whose client has a verified payment method.',
            'avg_jobs_per_hour': 'Jobs in a weekday-hour cell divided by the number of times that hour was observed.',
            'share_of_week': 'avg_jobs_per_hour of a cell divided by the sum over all 168 cells.',
            'suppression': f'Counts under {a.suppress} and statistics resting on under {a.suppress} jobs are empty.',
            'min_skill_jobs': a.min_skill,
        },
        'files': files,
    }
    with open(out('meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write('\n')
    json.dump({'files': files, 'totals': meta['totals'], 'coverage': {k: v for k, v in meta['coverage'].items()
               if k != 'pauses_in_window'}, 'summary': meta['summary']}, sys.stdout, indent=1, default=str)
    print()


if __name__ == '__main__':
    main()
