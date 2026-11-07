"""Adzuna job-ads API (optional; needs ADZUNA_APP_ID and ADZUNA_APP_KEY): ad counts and mean
advertised salary by role and country. A labour-demand proxy only.

access_basis: public_api_terms_ok
terms: https://developer.adzuna.com/docs/terms_of_service
"""

from __future__ import annotations

from nmt_engine.collect.base import Collector, env

NAME = "adzuna"
ACCESS_BASIS = "public_api_terms_ok"
TERMS_URL = "https://developer.adzuna.com/docs/terms_of_service"
API = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


def role_stats(c: Collector, role: str, country: str = "gb") -> dict:
    """{'role', 'country', 'count', 'mean_salary', 'source_id'}"""
    params = {
        "app_id": env("ADZUNA_APP_ID", required_by=NAME),
        "app_key": env("ADZUNA_APP_KEY", required_by=NAME),
        "what": role,
        "results_per_page": 1,
        "content-type": "application/json",
    }
    url = API.format(country=country.lower())
    data = c.fetch_json(url, NAME, params=params)
    src = c.add_source(
        adapter=NAME,
        kind="stats",
        platform="adzuna",
        url=f"{url}?what={role}",
        text=f"Adzuna {country.upper()} ads for '{role}': count={data.get('count')}, "
        f"mean advertised salary={data.get('mean')}",
        access_basis=ACCESS_BASIS,
        terms_url=TERMS_URL,
        geography=country.upper(),
    )
    return {
        "role": role,
        "country": country.upper(),
        "count": data.get("count"),
        "mean_salary": data.get("mean"),
        "source_id": src.id if src else None,
    }
