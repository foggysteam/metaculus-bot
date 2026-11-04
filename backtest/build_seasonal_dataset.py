"""
Builds a numeric backtest set of strongly seasonal quantities with known answers, to test
asking the researcher how the same quantity moved over the same weeks in earlier years
(PROGRESS.md, 4 Nov 2026). In the style of Metaculus bot tournament numeric questions, each as
of a date between August and October 2026 (after the models' training data), with a target 2
to 6 weeks later that has passed. Public data only, so it can be committed:
- percent of tests positive for respiratory viruses, CDC (data.cdc.gov rgnm-fkqb and seuz-s2cv)
- Arctic and Antarctic sea ice extent, NSIDC Sea Ice Index version 4
- mean temperature over a week in large cities, ERA5 through the Open-Meteo archive
- US series published without seasonal adjustment, first release (FRED)

Bounds are centred on the latest value known on the as-of date, as a question writer who
ignored the season might set them, and 2 to 3 times the typical change over the same weeks in
the last 5 years on each side, so the season's move stays inside but its direction is not hinted.

Usage: uv run python backtest/build_seasonal_dataset.py
Writes backtest/data/seasonal_questions.jsonl
"""
from __future__ import annotations

import json
import math
import random
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_numeric_dataset import fred, fred_vintage, nice  # noqa: E402

OUT = Path(__file__).parent / "data" / "seasonal_questions.jsonl"
RNG = random.Random(20261104)
FIRST_AS_OF = date(2026, 8, 3)
YEARS_BACK = 5

CDC_POSTED = date(2026, 10, 30)
LAST_CDC_WEEK = date(2026, 10, 24)
# (id, dataset, filter, virus, place)
CDC = [
    ("RSV", "rgnm-fkqb", "level='National' AND pathogen='RSV' AND subtype='Combined Type'", "respiratory syncytial virus (RSV)", "the United States"),
    ("HMPV", "rgnm-fkqb", "level='National' AND pathogen='HMPV' AND subtype='Combined Type'", "human metapneumovirus (HMPV)", "the United States"),
    ("RVEV", "rgnm-fkqb", "level='National' AND pathogen='RV/EV' AND subtype='Combined Type'", "rhinovirus/enterovirus", "the United States"),
    ("PIV", "rgnm-fkqb", "level='National' AND pathogen='PIV' AND subtype='Combined Type'", "parainfluenza viruses (all types)", "the United States"),
    ("HCOV", "rgnm-fkqb", "level='National' AND pathogen='HCOV' AND subtype='Combined Type'", "seasonal human coronaviruses (all types)", "the United States"),
    ("ADENO", "rgnm-fkqb", "level='National' AND pathogen='Adenovirus' AND subtype='Combined Type'", "adenovirus", "the United States"),
    ("SARS2", "rgnm-fkqb", "level='National' AND pathogen='SARS-COV-2'", "SARS-CoV-2", "the United States"),
    ("RSV-R4", "rgnm-fkqb", "level='Region 4' AND pathogen='RSV'", "respiratory syncytial virus (RSV)", "HHS Region 4 (the Southeast)"),
    ("RSV-R9", "rgnm-fkqb", "level='Region 9' AND pathogen='RSV'", "respiratory syncytial virus (RSV)", "HHS Region 9 (the Southwest and Pacific)"),
    ("RSV-R1", "rgnm-fkqb", "level='Region 1' AND pathogen='RSV'", "respiratory syncytial virus (RSV)", "HHS Region 1 (New England)"),
    ("FLU", "seuz-s2cv", "pathogen='Influenza'", "influenza", "the United States"),
    ("COVID", "seuz-s2cv", "pathogen='COVID-19'", "COVID-19", "the United States"),
]
CDC_NAMES = {
    "rgnm-fkqb": "the National Respiratory and Enteric Virus Surveillance System (NREVSS) percent positivity data",
    "seuz-s2cv": "Percent of Tests Positive for Viral Respiratory Pathogens",
}

LAST_ICE_DAY = date(2026, 11, 1)
ICE = [("north", "N", "Arctic", 5), ("south", "S", "Antarctic", 4)]

LAST_WEATHER_DAY = date(2026, 10, 28)
CITIES = [
    ("London", 51.51, -0.13), ("New York", 40.71, -74.01), ("Chicago", 41.88, -87.63), ("Moscow", 55.76, 37.62),
    ("Tokyo", 35.68, 139.69), ("Beijing", 39.90, 116.40), ("Sydney", -33.87, 151.21), ("Toronto", 43.65, -79.38),
    ("Berlin", 52.52, 13.40), ("Buenos Aires", -34.60, -58.38), ("Paris", 48.86, 2.35), ("Seoul", 37.57, 126.98),
    ("Mexico City", 19.43, -99.13), ("Cape Town", -33.92, 18.42), ("Madrid", 40.42, -3.70),
]

LAST_RELEASE = date(2026, 11, 3)
# (series, description, unit, weekly, how many)
FRED_NSA = [
    ("ICNSA", "US initial jobless claims, not seasonally adjusted (Department of Labor)", "claims", True, 3),
    ("CCNSA", "US continued jobless claims, not seasonally adjusted (Department of Labor)", "claims", True, 2),
    ("UNRATENSA", "the US unemployment rate, not seasonally adjusted (BLS)", "percent", False, 1),
    ("HOUSTNSA", "US housing starts, not seasonally adjusted (Census Bureau)", "thousands of units", False, 1),
    ("RSXFSN", "US retail sales excluding food services, not seasonally adjusted (Census Bureau)", "millions of dollars", False, 1),
    ("IPG2211A2N", "the US industrial production index for electric and gas utilities, not seasonally adjusted (Federal Reserve)", "index (2017 = 100)", False, 1),
    ("TOTALNSA", "US total vehicle sales, not seasonally adjusted (BEA)", "thousands of units", False, 1),
]


def shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year - years)
    except ValueError:  # 29 February
        return day.replace(year=day.year - years, day=28)


def value_at(series: dict[date, float], day: date, within: int = 7) -> float | None:
    """The latest value on or before day, if there is one within `within` days."""
    for back in range(within + 1):
        if (day - timedelta(days=back)) in series:
            return series[day - timedelta(days=back)]
    return None


def same_window_moves(series: dict[date, float], start: date, end: date, within: int = 7) -> list[float]:
    moves = []
    for back in range(1, YEARS_BACK + 1):
        a, b = value_at(series, shift_year(start, back), within), value_at(series, shift_year(end, back), within)
        if a is not None and b is not None:
            moves.append(b - a)
    return moves


def bounds(center: float, moves: list[float], floor: float, never_negative: bool) -> tuple[float, float]:
    # The median, so one odd year (RSV in 2022) does not make the range absurdly wide. Seasonal
    # moves are steady rather than random, so 2 to 3 of them on each side is enough.
    typical = max(statistics.median(abs(m) for m in moves) if moves else 0.0, floor)
    k_low, k_high = RNG.uniform(2, 3), RNG.uniform(2, 3)
    span = (k_low + k_high) * typical
    lo, hi = nice(center - k_low * typical, span), nice(center + k_high * typical, span)
    return (max(lo, 0.0) if never_negative else lo), hi


def row(id_: str, question: str, criteria: str, unit: str, outcome: float, as_of: date, resolve: date,
        known: float, moves: list[float], floor: float, source: str, series: str, never_negative: bool = True) -> dict:
    lo, hi = bounds(known, moves, floor, never_negative)
    return {
        "id": id_, "question": question, "resolution_criteria": criteria, "unit": unit,
        "outcome": round(outcome, 6), "outcome_date": resolve.isoformat(), "as_of": as_of.isoformat(),
        "resolve_date": resolve.isoformat(), "lower_bound": lo, "upper_bound": hi, "source": source, "series": series,
        # Not shown to the forecaster: for checking how seasonal the set is.
        "known_value": round(known, 6), "past_moves": [round(m, 6) for m in moves],
    }


def nice_day(day: date) -> str:
    return f"{day:%B} {day.day}, {day.year}"


################################ CDC respiratory viruses ################################


def cdc_series(dataset: str, where: str) -> dict[date, float]:
    week, value = ("mmwrweek_end", "percent_pos") if dataset == "rgnm-fkqb" else ("week_end", "percent_test_positivity")
    r = requests.get(f"https://data.cdc.gov/resource/{dataset}.json", params={"$where": where, "$order": week, "$limit": 5000}, timeout=60)
    r.raise_for_status()
    return {date.fromisoformat(x[week][:10]): float(x[value]) for x in r.json() if x.get(value) not in (None, ".")}


def cdc_questions() -> list[dict]:
    rows = []
    for key, dataset, where, virus, place in CDC:
        series = cdc_series(dataset, where)
        weeks = 7 * RNG.choice((2, 3, 4, 5, 6))
        # Weeks end on Saturdays. On a Monday as-of date the latest posted week ended 9 days earlier.
        targets = [d for d in series if FIRST_AS_OF + timedelta(days=weeks + 9) <= d <= LAST_CDC_WEEK]
        target = RNG.choice(targets)
        as_of = target - timedelta(days=weeks - 2)
        known_week = as_of - timedelta(days=9)
        known = value_at(series, known_week, within=0)
        if known is None:
            print("skip", key, "no value for", known_week)
            continue
        moves = same_window_moves(series, known_week, target)
        rows.append(row(
            f"sq-cdc-{key}-{target.isoformat()}",
            f"What percentage of tests will be positive for {virus} in {place} for the week ending {nice_day(target)}, in CDC data?",
            f"Resolves to the percent of tests positive for {virus} in {place} for the week ending {target.isoformat()} in CDC's {CDC_NAMES[dataset]} (data.cdc.gov dataset {dataset}), as posted on {CDC_POSTED.isoformat()}.",
            "percent", series[target], as_of, CDC_POSTED, known, moves, floor=0.3, source="cdc", series=f"{dataset}:{key}",
        ))
    return rows


###################################### Sea ice ######################################


def ice_series(folder: str, prefix: str) -> dict[date, float]:
    text = requests.get(f"https://noaadata.apps.nsidc.org/NOAA/G02135/{folder}/daily/data/{prefix}_seaice_extent_daily_v4.0.csv", timeout=60).text
    out = {}
    for line in text.splitlines()[2:]:
        parts = [p.strip() for p in line.split(",")[:4]]
        try:
            out[date(int(parts[0]), int(parts[1]), int(parts[2]))] = float(parts[3])
        except (ValueError, IndexError):
            continue
    return out


def ice_questions() -> list[dict]:
    rows = []
    for folder, prefix, name, count in ICE:
        series = ice_series(folder, prefix)
        for _ in range(count):
            days = RNG.choice((14, 21, 28, 35))
            target = FIRST_AS_OF + timedelta(days=days + RNG.randint(0, (LAST_ICE_DAY - FIRST_AS_OF).days - days))
            as_of = target - timedelta(days=days)
            known = value_at(series, as_of - timedelta(days=1), within=2)
            if target not in series or known is None:
                continue
            rows.append(row(
                f"sq-ice-{prefix}-{target.isoformat()}",
                f"What will the {name} sea ice extent be on {nice_day(target)}, according to the NSIDC Sea Ice Index?",
                f"Resolves to the daily {name} sea ice extent for {target.isoformat()} in the NSIDC Sea Ice Index version 4 daily file ({prefix}_seaice_extent_daily_v4.0.csv), in millions of square kilometers.",
                "million square kilometers", series[target], as_of, target + timedelta(days=1), known,
                same_window_moves(series, as_of - timedelta(days=1), target, within=2), floor=0.1, source="nsidc", series=prefix,
            ))
    return rows


#################################### Temperature ####################################


def weekly_mean_temperatures(lat: float, lon: float) -> dict[date, float]:
    """Mean of the daily mean temperatures over the 7 days ending on each day."""
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={"latitude": lat, "longitude": lon, "start_date": "2020-12-01", "end_date": LAST_WEATHER_DAY.isoformat(), "daily": "temperature_2m_mean", "timezone": "UTC"},
        timeout=60,
    )
    r.raise_for_status()
    daily = r.json()["daily"]
    temps = {date.fromisoformat(d): t for d, t in zip(daily["time"], daily["temperature_2m_mean"]) if t is not None}
    out = {}
    for day in temps:
        week = [temps.get(day - timedelta(days=k)) for k in range(7)]
        if None not in week:
            out[day] = sum(week) / 7
    return out


def weather_questions() -> list[dict]:
    rows = []
    for city, lat, lon in CITIES:
        series = weekly_mean_temperatures(lat, lon)
        days = RNG.choice((14, 21, 28, 35))
        target = FIRST_AS_OF + timedelta(days=days + RNG.randint(0, (LAST_WEATHER_DAY - FIRST_AS_OF).days - days))
        as_of = target - timedelta(days=days)
        known = series[as_of - timedelta(days=1)]
        rows.append(row(
            f"sq-temp-{city.replace(' ', '')}-{target.isoformat()}",
            f"What will be the average daily mean temperature in {city} over the 7 days ending {nice_day(target)}, in degrees Celsius?",
            f"Resolves to the mean of the daily mean 2-metre air temperatures from {(target - timedelta(days=6)).isoformat()} to {target.isoformat()} at latitude {lat}, longitude {lon} ({city}), from the ERA5 reanalysis as served by the Open-Meteo historical weather API (archive-api.open-meteo.com), in degrees Celsius.",
            "degrees Celsius", round(series[target], 2), as_of, target + timedelta(days=6), known,
            same_window_moves(series, as_of - timedelta(days=1), target, within=0), floor=0.5, source="open-meteo", series=city,
            never_negative=False,
        ))
        time.sleep(1)
    return rows


############################## FRED, not seasonally adjusted ##############################


def fred_final(series: str) -> dict[date, float]:
    obs = fred("series/observations", series_id=series, observation_start="2019-01-01")["observations"]
    return {date.fromisoformat(o["date"]): float(o["value"]) for o in obs if o["value"] != "."}


def fred_questions() -> list[dict]:
    rows = []
    for series, name, unit, weekly, count in FRED_NSA:
        final = fred_final(series)
        if weekly:
            candidates = [d for d in final if FIRST_AS_OF + timedelta(days=28) <= d <= LAST_RELEASE - timedelta(days=21)]
        else:
            candidates = [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]
        for period in RNG.sample(sorted(candidates), count):
            vintages = [date.fromisoformat(v) for v in fred("series/vintagedates", series_id=series, realtime_start=period.isoformat())["vintage_dates"]]
            release = next((d for d in vintages if d <= LAST_RELEASE and any(p == period for p, _ in fred_vintage(series, d))), None)
            if release is None:
                print("skip", series, period, "not released by", LAST_RELEASE)
                continue
            first_value = dict(fred_vintage(series, release))[period]
            as_of = release - timedelta(days=RNG.choice((7, 10, 14, 21)))
            prior = dict(fred_vintage(series, as_of - timedelta(days=1)))
            last_period = max(prior)
            moves = []
            for back in range(1, YEARS_BACK + 1):
                within = 6 if weekly else 0
                a, b = value_at(final, shift_year(last_period, back), within), value_at(final, shift_year(period, back), within)
                if a is not None and b is not None:
                    moves.append(b - a)
            label = f"the week ending {nice_day(period)}" if weekly else f"{period:%B %Y}"
            rows.append(row(
                f"sq-fred-{series}-{period.isoformat()}",
                f"What will be {name} for {label}, as first published?",
                f"Resolves to the first published value of {name} for {label} (FRED series {series}). Later revisions are ignored.",
                unit, first_value, as_of, release, prior[last_period], moves, floor=abs(prior[last_period]) * 0.01,
                source="fred", series=series,
            ))
            time.sleep(0.5)
    return rows


def main() -> None:
    rows = cdc_questions() + ice_questions() + weather_questions() + fred_questions()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    inside = sum(r["lower_bound"] <= r["outcome"] <= r["upper_bound"] for r in rows)
    print(f"{len(rows)} questions ({inside} with the outcome inside the bounds) -> {OUT}")
    # How seasonal is the set? Error of "no change" against "no change plus the average move over
    # the same weeks in earlier years", each as a share of the question's range.
    gains = []
    for r in rows:
        width = r["upper_bound"] - r["lower_bound"]
        naive = abs(r["outcome"] - r["known_value"]) / width
        seasonal = abs(r["outcome"] - r["known_value"] - (statistics.mean(r["past_moves"]) if r["past_moves"] else 0)) / width
        gains.append(naive - seasonal)
        print(f"{r['id']:<34} as of {r['as_of']}  known {r['known_value']:>10.4g}  outcome {r['outcome']:>10.4g}  "
              f"range {r['lower_bound']:g} to {r['upper_bound']:g}  error no change {naive:.3f}, with past years {seasonal:.3f}")
    better = sum(g > 0 for g in gains)
    print(f"Past years' average move is closer than no change on {better} of {len(gains)} questions; "
          f"median gain {statistics.median(gains):.3f} of the range")


if __name__ == "__main__":
    main()
