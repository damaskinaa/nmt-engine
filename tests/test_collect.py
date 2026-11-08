"""Collector tests: VCR replays of real public APIs, mock transports for keyed APIs."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

import httpx
import pytest

from nmt_engine.collect import (
    adzuna,
    appstore,
    companies_house,
    cso,
    dataforseo,
    datasets,
    eurostat,
    github,
    googleplay,
    hackernews,
    ons,
    procurement,
    reddit,
    sec_edgar,
    stackexchange,
    wayback,
    web,
    youtube,
)
from nmt_engine.collect.base import (
    FORBIDDEN_HOSTS,
    Collector,
    ForbiddenHostError,
    HostNotAllowedError,
    MissingKeyError,
    is_forbidden,
    operator_hosts,
    redact,
    scrub_pii,
)
from nmt_engine.collect.run import CollectPlan, run_collect
from nmt_engine.collect.stats import jsonstat_frame
from nmt_engine.schema import ALLOWED_ACCESS_BASIS, KIND_FAMILY
from nmt_engine.store import load_run
from nmt_engine.util import sha256_text
from tests.vcr_util import CASSETTES, SECRET_QUERY, cassette

SINCE = date(2023, 1, 1)
KEYS = [
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT",
    "YOUTUBE_API_KEY",
    "GITHUB_TOKEN",
    "STACKEXCHANGE_KEY",
    "DATAFORSEO_LOGIN",
    "DATAFORSEO_PASSWORD",
    "COMPANIES_HOUSE_API_KEY",
    "ADZUNA_APP_ID",
    "ADZUNA_APP_KEY",
    "PRODUCTHUNT_TOKEN",
    "FIRECRAWL_API_KEY",
]


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SEC_USER_AGENT", "nmt-engine tests research@example.org")


# hosts the tests pass as if from `--competitors`
TEST_HOSTS = operator_hosts(
    ["a.example.org", "api.example.org", "short.example.org", "rebind.example.org"]
    + ["blocked.example.org", "evil.example.org", "invoiceninja.com"]
)


def make(tmp_path: Path, handler=None, hosts: frozenset[str] = TEST_HOSTS) -> Collector:
    client = httpx.Client(transport=httpx.MockTransport(handler)) if handler else None
    return Collector(
        tmp_path / "run",
        as_of=date(2026, 11, 7),
        min_interval_s=0,
        salt="t",
        client=client,
        extra_hosts=hosts,
    )


def log(c: Collector) -> list[dict]:
    path = c.run_dir / "retrieval_log.jsonl"
    return [json.loads(ln) for ln in path.read_text().splitlines()]


# Evidence family per platform (and kind, where one platform yields more than one family).
FAMILY = {
    "hackernews": "discussion",
    "reddit": "discussion",
    "github-discussions": "discussion",
    "youtube-comments": "discussion",
    "github": "support_issue",
    "stackexchange": "qa",
    "appstore": "review",
    "youtube": "market_record",
    ("web", "pricing"): "vendor_page",
    ("web", "web"): "vendor_page",
    ("web", "changelog"): "change_history",
    ("wayback", "pricing"): "vendor_page",
    ("wayback", "changelog"): "change_history",
    "producthunt": "vendor_page",
    "dataforseo": "search_demand",
    "ted": "market_record",
    "contracts_finder": "market_record",
    "eurostat": "market_record",
    "cso": "market_record",
    "ons": "market_record",
    "sec_edgar": "market_record",
    "companies_house": "market_record",
    "adzuna": "market_record",
    "npm": "market_record",
    "pypi": "market_record",
    "huggingface": "market_record",
}
CUSTOMER = {"discussion", "support_issue", "qa", "review"}


def expected_family(s) -> str:
    base = s.platform.split(":")[0]
    return FAMILY.get((base, s.kind)) or FAMILY.get(base) or KIND_FAMILY[s.kind]


@pytest.fixture(autouse=True)
def _family_checked(monkeypatch):
    """Every source any adapter stores in these tests gets the expected evidence family."""
    seen: list = []
    orig = Collector.add_source

    def add_source(self, **kw):
        src = orig(self, **kw)
        if src is not None:
            assert src.evidence_family == expected_family(src), (src.platform, src.kind)
            seen.append(src.platform.split(":")[0])
        return src

    monkeypatch.setattr(Collector, "add_source", add_source)
    yield seen


def test_every_family_mapping_is_exercised(tmp_path, _family_checked):
    c = make(tmp_path)
    with cassette("run_invoicing"):
        run_collect(CollectPlan("invoicing", SINCE, "IE"), c.run_dir, c)
    assert {"hackernews", "github", "stackexchange", "appstore"} <= set(_family_checked)


def check_sources(c: Collector, minimum: int = 1) -> dict:
    srcs = c.store.current("source")
    assert len(srcs) >= minimum
    logged = {e.get("source_id") for e in log(c)}
    for s in srcs.values():
        text = (c.run_dir / s.text_path).read_text()
        assert sha256_text(text) == s.sha256
        assert s.access_basis in ALLOWED_ACCESS_BASIS and s.terms_url and s.as_of_date
        assert s.id in logged
        assert s.author_hash is None or s.author_hash.startswith("a_")
        assert not is_forbidden(s.url)
        assert s.evidence_family == expected_family(s), (s.platform, s.kind)
        assert s.customer_voice == (s.evidence_family in CUSTOMER)
    return srcs


# --- acceptance: recorded run for one sample category ---------------------------------------


def test_recorded_run_yields_500_trace_sources(tmp_path):
    c = make(tmp_path)
    with cassette("run_invoicing"):
        summary = run_collect(CollectPlan("invoicing", SINCE, "IE"), c.run_dir, c)
    assert summary["trace_sources"] >= 500, summary
    assert summary["adapters"]["reddit"]["status"] == "skipped"
    srcs = check_sources(c, 500)
    assert {"review", "forum", "qa", "issue"} <= {s.kind for s in srcs.values()}
    assert (c.run_dir / "collect_summary.json").is_file()
    data = load_run(c.run_dir)  # the run loads with the PR 1 schema and log validators
    assert len(data.sources) == len(srcs) and len(data.retrieval_log) > len(srcs)


def test_retrieval_log_has_no_forbidden_hosts(tmp_path):
    c = make(tmp_path)
    with cassette("run_invoicing"):
        run_collect(CollectPlan("invoicing", SINCE, "IE"), c.run_dir, c)
    hosts = {e["host"] for e in log(c)}
    assert hosts and not any(f in h for h in hosts for f in FORBIDDEN_HOSTS)


# --- per-adapter VCR replays -----------------------------------------------------------------


def test_hackernews(tmp_path):
    c = make(tmp_path)
    with cassette("hackernews"):
        out = hackernews.collect(c, "invoice software", SINCE, 20)
    assert len(out) == 20 and all(s.platform == "hackernews" for s in out)
    check_sources(c, 20)


def test_stackexchange(tmp_path):
    c = make(tmp_path)
    with cassette("stackexchange"):
        out = stackexchange.collect(c, "invoice", SINCE, "softwarerecs", 10)
    assert out and all(s.kind == "qa" for s in out)
    check_sources(c)


def test_appstore(tmp_path):
    c = make(tmp_path)
    with cassette("appstore"):
        out = appstore.collect(c, "invoice", "ie", apps=1, pages=1)
        recent = appstore.collect(make(tmp_path / "b"), "invoice", "ie", 1, 1, date(2023, 7, 19))
    assert 0 < len(recent) < len(out)
    assert all(s.published_at.date() >= date(2023, 7, 19) for s in recent)
    assert out and all(
        s.kind == "review" and "Rating:" in (c.run_dir / s.text_path).read_text() for s in out
    )
    check_sources(c)


def test_github_issues(tmp_path):
    c = make(tmp_path)
    with cassette("github"):
        out = github.collect(c, "invoice pdf", SINCE, 10)
    assert len(out) == 10 and all(s.kind == "issue" for s in out)
    with pytest.raises(MissingKeyError):
        github.discussions(c, "invoice", SINCE)


def test_wayback_snapshots_and_diffs(tmp_path):
    c = make(tmp_path)
    with cassette("wayback"):
        out = wayback.collect(c, "invoiceninja.com/pricing", SINCE, 3)
    kinds = [s.kind for s in out]
    assert kinds.count("pricing") >= 2
    check_sources(c)


def test_web_page_respects_robots(tmp_path):
    c = make(tmp_path)
    with cassette("web"):
        out = web.competitor_pages(c, "invoiceninja.com", paths=("pricing",))
    assert len(out) == 1 and out[0].kind == "pricing"
    check_sources(c)


def test_eurostat(tmp_path):
    c = make(tmp_path)
    with cassette("eurostat"):
        df = eurostat.dataset(c, "sbs_sc_ovw", geo="IE", nace_r2="J62", time="2021")
    assert {"value", "source_id", "geo"} <= set(df.columns) and len(df) > 0
    check_sources(c)
    with cassette("eurostat"):
        again = eurostat.dataset(c, "sbs_sc_ovw", geo="IE", nace_r2="J62", time="2021")
    assert set(again["source_id"]) == set(df["source_id"]) == {df.loc[0, "source_id"]}


def test_cso(tmp_path):
    c = make(tmp_path)
    with cassette("cso"):
        df = cso.topic(c, "business_demography")
    assert len(df) > 0 and df["source_id"].notna().all()


def test_ons(tmp_path):
    c = make(tmp_path)
    with cassette("ons"):
        df = ons.topic(c, "uk_business_counts")
        with pytest.raises(ValueError, match="observations"):
            ons.topic(c, "ashe_earnings_by_occupation")
    assert len(df) > 100 and df["source_id"].notna().all()


def test_sec_edgar(tmp_path):
    c = make(tmp_path)
    with cassette("sec_edgar"):
        df = sec_edgar.company_facts(c, 1352010)  # HubSpot
    assert "Revenues" in set(df["concept"]) or len(df) > 0
    assert (df["value"] > 0).any()


def test_procurement(tmp_path):
    c = make(tmp_path)
    with cassette("procurement"):
        out = procurement.ted(c, "accounting software", SINCE, 5)
        cf = procurement.contracts_finder(c, "software", date(2026, 10, 1), 5, max_pages=5)
    assert len(out) == 5 and all(s.kind == "procurement" for s in out)
    assert cf and all(s.platform == "contracts_finder" for s in cf)


def test_package_downloads_and_twin(tmp_path):
    c = make(tmp_path)
    with cassette("datasets"):
        npm = datasets.npm_downloads(c, "invoice-pdf", date(2026, 9, 1), date(2026, 9, 30))
        pypi = datasets.pypi_downloads(c, "invoice2data")
        twin = datasets.twin2k(c, length=5)
    assert len(npm) == 30 and len(pypi) > 0 and len(twin) == 5


# --- keyed adapters (mock transports with documented response shapes) ------------------------


def _router(routes: dict[str, object]):
    def handler(request: httpx.Request) -> httpx.Response:
        for frag, body in routes.items():
            if frag in str(request.url):
                return httpx.Response(200, json=body)
        return httpx.Response(404, json={})

    return handler


def test_reddit_oauth(tmp_path, monkeypatch):
    for k, v in {
        "REDDIT_CLIENT_ID": "id",
        "REDDIT_CLIENT_SECRET": "sec",
        "REDDIT_USER_AGENT": "nmt/0.1",
    }.items():
        monkeypatch.setenv(k, v)
    post = {
        "data": {
            "title": "Invoicing hurts",
            "selftext": "I export to Excel every week",
            "permalink": "/r/smallbusiness/comments/x/y/",
            "author": "u1",
            "subreddit": "smallbusiness",
            "created_utc": 1700000000,
        }
    }
    c = make(
        tmp_path,
        _router(
            {
                "access_token": {"access_token": "tok"},
                "oauth.reddit.com/search": {"data": {"children": [post]}},
            }
        ),
    )
    out = reddit.collect(c, "invoicing", SINCE)
    assert len(out) == 1 and out[0].platform == "reddit:r/smallbusiness"
    assert out[0].author_hash.startswith("a_")


def test_youtube_redacts_key(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "SECRET123")
    c = make(
        tmp_path,
        _router(
            {
                "/search": {
                    "items": [
                        {
                            "id": {"videoId": "v1"},
                            "snippet": {
                                "title": "Best invoicing app",
                                "description": "review",
                                "channelTitle": "ch",
                                "publishedAt": "2024-01-01T00:00:00Z",
                            },
                        }
                    ]
                },
                "/commentThreads": {
                    "items": [
                        {
                            "snippet": {
                                "topLevelComment": {
                                    "id": "c1",
                                    "snippet": {
                                        "textOriginal": "I switched from FreshBooks",
                                        "authorChannelId": {"value": "UC1"},
                                        "publishedAt": "2024-01-02T00:00:00Z",
                                    },
                                }
                            }
                        }
                    ]
                },
            }
        ),
    )
    out = youtube.collect(c, "invoicing", SINCE)
    assert [s.platform for s in out] == ["youtube", "youtube-comments"]
    raw = (c.run_dir / "retrieval_log.jsonl").read_text()
    assert "SECRET123" not in raw and "REDACTED" in raw


def test_dataforseo(tmp_path, monkeypatch):
    monkeypatch.setenv("DATAFORSEO_LOGIN", "l")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "p")
    c = make(
        tmp_path,
        _router(
            {
                "search_volume": {
                    "tasks": [
                        {
                            "result": [
                                {
                                    "keyword": "invoice app",
                                    "search_volume": 1900,
                                    "cpc": 4.2,
                                    "competition": "HIGH",
                                    "monthly_searches": [
                                        {"year": 2026, "month": 9, "search_volume": 2000}
                                    ],
                                }
                            ]
                        }
                    ]
                },
                "autocomplete": {
                    "tasks": [{"result": [{"items": [{"suggestion": "invoice app free"}]}]}]
                },
                "organic": {
                    "tasks": [
                        {
                            "result": [
                                {
                                    "items": [
                                        {
                                            "type": "people_also_ask",
                                            "items": [{"title": "What is the best invoice app?"}],
                                        },
                                        {"type": "related_searches", "items": ["invoice template"]},
                                    ]
                                }
                            ]
                        }
                    ]
                },
            }
        ),
    )
    df = dataforseo.search_volume(c, ["invoice app"])
    assert df.loc[0, "cpc"] == 4.2 and df.loc[0, "month"] == "2026-09"
    assert dataforseo.autocomplete(c, "invoice app") == ["invoice app free"]
    assert dataforseo.serp_questions(c, "invoice app")["related"] == ["invoice template"]
    from nmt_engine.collect.run import _dfs

    fresh = Collector(tmp_path / "b", as_of=c.as_of, min_interval_s=0, salt="t", client=c.client)
    assert len(_dfs(fresh, "invoice app", "IE")) == 2  # autocomplete + SERP question sources


def test_companies_house(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "k")
    doc = (
        '<ix:nonFraction name="uk-core:TurnoverRevenue" scale="3" unitRef="GBP">1,234'
        "</ix:nonFraction>"
    )

    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if "advanced-search" in u:
            return httpx.Response(200, json={"hits": 4321})
        if "filing-history" in u:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "links": {
                                "document_metadata": "https://document-api.company-information.service.gov.uk/document/D1"
                            }
                        }
                    ]
                },
            )
        if "/document/D1/content" in u:
            return httpx.Response(200, text=doc)
        return httpx.Response(404)

    c = make(tmp_path, handler)
    assert companies_house.count_by_sic(c, "62012") == 4321
    assert companies_house.turnover(c, "01234567") == 1_234_000


def test_adzuna(tmp_path, monkeypatch):
    monkeypatch.setenv("ADZUNA_APP_ID", "id")
    monkeypatch.setenv("ADZUNA_APP_KEY", "SECRETKEY")
    c = make(tmp_path, _router({"adzuna": {"count": 812, "mean": 41000.5}}))
    r = adzuna.role_stats(c, "bookkeeper", "gb")
    assert r["count"] == 812 and r["source_id"]
    assert "SECRETKEY" not in (c.run_dir / "retrieval_log.jsonl").read_text()


def test_keyed_adapters_refuse_without_keys(tmp_path):
    c = make(tmp_path, _router({}))
    for call in (
        lambda: reddit.collect(c, "q", SINCE),
        lambda: youtube.collect(c, "q", SINCE),
        lambda: dataforseo.autocomplete(c, "q"),
        lambda: adzuna.role_stats(c, "r"),
        lambda: companies_house.count_by_sic(c, "1"),
        lambda: datasets.producthunt_posts(c, "t"),
    ):
        with pytest.raises(MissingKeyError):
            call()


def test_malformed_payloads_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCTHUNT_TOKEN", "t")
    monkeypatch.setenv("NMT_PRODUCTHUNT_TERMS_OK", "1")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "l")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "p")
    ph = {
        "data": {
            "posts": {
                "edges": [{"node": {"name": "x"}}, {"node": {"url": "https://a.example.org"}}]
            }
        }
    }
    assert (
        datasets.producthunt_posts(make(tmp_path / "ph", _router({"producthunt": ph})), "x") == []
    )
    ted = {"notices": [{"notice-title": {"eng": "No id"}}]}
    assert procurement.ted(make(tmp_path / "ted", _router({"ted": ted})), "x", SINCE, 5) == []
    vol = {
        "tasks": [
            {
                "result": [
                    {"keyword": "k", "monthly_searches": [{"year": 2026}, {"month": 3}]},
                ]
            }
        ]
    }
    df = dataforseo.search_volume(make(tmp_path / "dfs", _router({"search_volume": vol})), ["k"])
    assert df["month"].isna().all()


def test_malformed_sec_and_youtube_items_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "nmt test@example.org")
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    fact = {"fy": 2025, "fp": "FY", "form": "10-K", "end": "2025-12-31"}
    facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [fact, {**fact, "val": 7}]}}}}}
    df = sec_edgar.company_facts(make(tmp_path / "sec", _router({"companyfacts": facts})), 1)
    assert df["value"].tolist() == [7.0]
    yt = {"items": [{"id": {"kind": "youtube#channel"}, "snippet": {}}, {"snippet": {}}]}
    c = make(tmp_path / "yt", _router({"/search": yt, "/commentThreads": {"items": []}}))
    assert youtube.collect(c, "x", SINCE) == []
    yt = {"items": [{"id": {"videoId": "v1"}, "snippet": {"title": "t"}}]}
    threads = {"items": [{"snippet": {}}, {"snippet": {"topLevelComment": {"snippet": {}}}}]}
    c = make(tmp_path / "yt2", _router({"/search": yt, "/commentThreads": threads}))
    assert [s.platform for s in youtube.collect(c, "x", SINCE)] == ["youtube"]


def test_opt_in_dns_egress_check(tmp_path, monkeypatch):
    import socket

    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("169.254.169.254", 0))]
    )
    seen = []
    handler = lambda req: seen.append(req) or httpx.Response(200, text="x")  # noqa: E731
    assert make(tmp_path / "off", handler).fetch("https://a.example.org/", "t") == "x"
    monkeypatch.setenv("NMT_EGRESS_RESOLVE", "1")
    with pytest.raises(ForbiddenHostError):
        make(tmp_path / "on", handler).fetch("https://rebind.example.org/", "t")
    assert len(seen) == 1


def test_producthunt_needs_terms_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("PRODUCTHUNT_TOKEN", "t")
    with pytest.raises(MissingKeyError):
        datasets.producthunt_posts(make(tmp_path, _router({})), "invoicing")


def test_googleplay_disabled():
    assert googleplay.ENABLED is False
    with pytest.raises(NotImplementedError):
        googleplay.collect()


# --- shared plumbing ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/in/x",
        "https://www.glassdoor.ie/x",
        "https://www.g2.com/products/x",
        "https://uk.trustpilot.com/r",
    ],
)
def test_forbidden_hosts_refused(tmp_path, url):
    c = make(tmp_path, _router({}))
    with pytest.raises(ForbiddenHostError):
        c.fetch(url, "t")
    with pytest.raises(ForbiddenHostError):
        c.add_source(
            adapter="t",
            kind="web",
            platform="x",
            url=url,
            text="hi",
            access_basis="public_page_terms_ok",
            terms_url="x",
        )


def test_cache_retry_and_dedupe(tmp_path):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(
            429 if len(calls) == 1 else 200, headers={"Retry-After": "0"}, json={"ok": True}
        )

    c = make(tmp_path, handler)
    assert c.fetch_json("https://api.example.org/x", "t") == {"ok": True}
    assert c.fetch_json("https://api.example.org/x", "t") == {"ok": True}
    assert len(calls) == 2  # one retry, then a cache hit
    kw = dict(
        adapter="t",
        kind="web",
        platform="x",
        url="https://e.org/a",
        text="same",
        access_basis="public_page_terms_ok",
        terms_url="x",
    )
    assert c.add_source(**kw) is not None and c.add_source(**kw) is None
    assert make(tmp_path, handler).add_source(**kw) is None  # dedupe survives a new Collector


def test_robots_disallow(tmp_path):
    c = make(tmp_path, lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /"))
    with pytest.raises(web.RobotsDisallowedError):
        web.page(c, "https://blocked.example.org/pricing")


def test_redact_and_scrub():
    assert "SECRET" not in redact("https://x.org/a?key=SECRET&q=1") and "q=1" in redact(
        "https://x.org/a?key=SECRET&q=1"
    )
    out = scrub_pii("Mail jo.bloggs@example.com or +353 1 234 5678; v2.0.1 on 2024-01-05, $12,000")
    assert out == "Mail [email] or [phone]; v2.0.1 on 2024-01-05, $12,000"


def test_jsonstat_and_ixbrl_and_diff():
    js = {
        "id": ["geo", "time"],
        "size": [2, 1],
        "dimension": {
            "geo": {"category": {"index": {"IE": 0, "FR": 1}, "label": {"IE": "Ireland"}}},
            "time": {"category": {"index": ["2021"]}},
        },
        "value": {"1": 7.0},
    }
    df = jsonstat_frame(js)
    assert df.to_dict("records") == [
        {"geo": "FR", "geo_code": "FR", "time": "2021", "time_code": "2021", "value": 7.0}
    ]
    neg = '<ix:nonFraction name="core:Revenue" sign="-">500</ix:nonFraction>'
    assert companies_house.ixbrl_turnover(neg) == -500
    assert companies_house.ixbrl_turnover("<p/>") is None
    ctx = (
        '<xbrli:context id="{}"><xbrli:period><xbrli:startDate>{}-01-01</xbrli:startDate>'
        "<xbrli:endDate>{}-12-31</xbrli:endDate></xbrli:period>{}</xbrli:context>"
    )
    seg = "<xbrli:segment><xbrldi:explicitMember>x</xbrldi:explicitMember></xbrli:segment>"
    doc = (
        ctx.format("py", 2022, 2022, "")
        + ctx.format("cy", 2023, 2023, "")
        + ctx.format("cy_seg", 2023, 2023, seg)
        + '<ix:nonFraction name="core:Turnover" contextRef="py" scale="3">1,000</ix:nonFraction>'
        + '<ix:nonFraction name="core:Turnover" contextRef="cy_seg">7</ix:nonFraction>'
        + '<ix:nonFraction name="core:Turnover" contextRef="cy" scale="3">1,250</ix:nonFraction>'
    )
    assert companies_house.ixbrl_turnover(doc) == 1_250_000
    scen = "<xbrli:scenario><xbrldi:explicitMember>x</xbrldi:explicitMember></xbrli:scenario>"
    doc2 = (
        ctx.format("cy_scen", 2023, 2023, scen)
        + ctx.format("cy", 2023, 2023, "")
        + '<ix:nonFraction name="core:Turnover" contextRef="cy_scen">7</ix:nonFraction>'
        + '<ix:nonFraction name="core:Turnover" contextRef="cy">9</ix:nonFraction>'
    )
    assert companies_house.ixbrl_turnover(doc2) == 9
    only_dims = ctx.format("cy_scen", 2023, 2023, scen) + (
        '<ix:nonFraction name="core:Turnover" contextRef="cy_scen">7</ix:nonFraction>'
    )
    assert companies_house.ixbrl_turnover(only_dims) is None
    assert wayback.diff("a\nPrice 10", "Price 12\na") == "+Price 12\n-Price 10"


def test_cli_collect_requires_salt(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from nmt_engine.cli import app

    monkeypatch.delenv("NMT_AUTHOR_SALT", raising=False)
    args = ["collect", "--category", "x", "--since", "2023-01-01", "--run-dir", str(tmp_path)]
    res = CliRunner().invoke(app, args)
    assert res.exit_code == 2 and "NMT_AUTHOR_SALT" in res.output


def test_redirect_to_forbidden_host_refused(tmp_path):
    seen = []

    def handler(req):
        seen.append(req.url.host)
        if req.url.host == "short.example.org":
            return httpx.Response(302, headers={"Location": "https://www.linkedin.com/in/x"})
        return httpx.Response(200, text="ok")

    c = make(tmp_path, handler)
    with pytest.raises(ForbiddenHostError):
        c.fetch("https://short.example.org/a", "t")
    assert seen == ["short.example.org"]


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8080/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "http://intranet.internal/",
        "http://2130706433/",
        "http://0x7f.1/",
        "http://127.1/",
    ],
)
def test_internal_hosts_refused(tmp_path, url):
    seen = []
    c = make(tmp_path, lambda req: seen.append(req) or httpx.Response(200, text="x"))
    with pytest.raises(ForbiddenHostError):
        c.fetch(url, "t")
    assert not seen


def test_redirect_to_internal_host_refused(tmp_path):
    def handler(req):
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/"})

    with pytest.raises(ForbiddenHostError):
        make(tmp_path, handler).fetch("https://a.example.org/x", "t")


def test_download_follows_redirects_with_host_checks(tmp_path):
    from nmt_engine.collect import datasets

    def handler(req):
        if req.url.host == "webrobots.io":
            if req.url.path == "/d.zip":
                return httpx.Response(302, headers={"Location": "/files/d.zip"})
            return httpx.Response(200, content=b"PK-zip")
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/d.zip"})

    c = make(tmp_path, handler)
    out = datasets.kickstarter_download(c, "https://webrobots.io/d.zip", tmp_path / "d.zip")
    assert out.read_bytes() == b"PK-zip"
    with pytest.raises(ForbiddenHostError):
        c.download("https://evil.example.org/d.zip", "t", tmp_path / "e.zip")


def test_interrupted_download_not_logged_as_success(tmp_path):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield b"PK-part"
            raise httpx.ReadError("connection reset")

    c = make(tmp_path, lambda req: httpx.Response(200, stream=Broken()))
    with pytest.raises(httpx.ReadError):
        c.download("https://a.example.org/d.zip", "t", tmp_path / "d.zip")
    assert not list(tmp_path.glob("d.zip*"))
    assert [e.get("status_code") for e in log(c)] == [None]


def test_redirect_without_location_is_an_http_error(tmp_path):
    c = make(tmp_path, lambda req: httpx.Response(302))
    with pytest.raises(httpx.HTTPStatusError):
        c.fetch("https://a.example.org/x", "t")
    with pytest.raises(httpx.HTTPStatusError):
        c.download("https://a.example.org/d.zip", "t", tmp_path / "d.zip")


def test_redirect_followed_to_allowed_host(tmp_path):
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new"})
        return httpx.Response(200, text="moved")

    assert make(tmp_path, handler).fetch("https://a.example.org/old", "t") == "moved"


def test_cache_holds_masked_payload(tmp_path):
    body = {"text": "mail <jo@example.com> or +353 1 234 5678", "n": 3}
    c = make(tmp_path, lambda r: httpx.Response(200, json=body))
    assert c.fetch_json("https://api.example.org/p", "t")["text"] == "mail <[email]> or [phone]"
    raw = "".join(f.read_text() for f in c.cache_dir.iterdir())
    assert "jo@example.com" not in raw and "234 5678" not in raw


def test_contracts_finder_follows_cursor_pages(tmp_path):
    def rel(i, title):
        return {"ocid": f"ocds-b5fd17-{i}", "tender": {"title": title}, "awards": []}

    def handler(req):
        if "cursor" not in str(req.url):
            assert req.url.params["publishedFrom"] == "2026-10-01T00:00:00"
            nxt = (
                "https://www.contractsfinder.service.gov.uk/Published/Notices/OCDS/Search?cursor=2"
            )
            return httpx.Response(200, json={"releases": [rel(1, "Roads")], "links": {"next": nxt}})
        return httpx.Response(200, json={"releases": [rel(2, "Invoicing software")], "links": {}})

    out = procurement.contracts_finder(make(tmp_path, handler), "invoicing", date(2026, 10, 1))
    assert [s.url.rsplit("/", 1)[1] for s in out] == ["2"]


def test_cache_is_partitioned_by_credentials(tmp_path):
    def handler(req):
        return httpx.Response(200, text=f"data for {req.headers.get('Authorization')}")

    c = make(tmp_path, handler)
    url = "https://api.example.org/private"
    assert c.fetch(url, "t", headers={"Authorization": "Bearer A"}) == "data for Bearer A"
    assert c.fetch(url, "t", headers={"Authorization": "Bearer B"}) == "data for Bearer B"
    assert c.fetch(url, "t", headers={"Authorization": "Bearer A"}) == "data for Bearer A"
    raw = "".join(f.name + f.read_text() for f in c.cache_dir.iterdir())
    assert "Bearer" not in raw.replace("data for Bearer", "")


def test_redirect_drops_credentials_on_https_downgrade(tmp_path):
    seen = []

    def handler(req):
        seen.append((req.url.scheme, req.headers.get("Authorization")))
        if req.url.scheme == "https":
            return httpx.Response(302, headers={"Location": "http://api.example.org/x"})
        return httpx.Response(200, text="ok")

    make(tmp_path, handler).fetch("https://api.example.org/a", "t", headers={"Authorization": "k"})
    assert seen == [("https", "k"), ("http", None)]


def test_default_collector_only_fetches_builtin_or_operator_hosts(tmp_path):
    seen = []

    def handler(req):
        seen.append(req.url.host)
        if req.url.host == "api.example.org":  # cross-host, even to a built-in API host
            return httpx.Response(302, headers={"Location": "https://api.github.com/x"})
        return httpx.Response(200, text="ok")

    bare = make(tmp_path / "bare", handler, hosts=frozenset())
    with pytest.raises(HostNotAllowedError):
        bare.fetch("https://rebind.example.org/", "t")
    with pytest.raises(HostNotAllowedError):
        bare.download("https://rebind.example.org/d.zip", "t", tmp_path / "d.zip")
    assert bare.fetch("https://hn.algolia.com/api/v1/search", "t") == "ok"
    assert seen == ["hn.algolia.com"]
    op = make(tmp_path / "op", handler, hosts=operator_hosts(["api.example.org", "www.b.io"]))
    assert {"api.example.org", "www.api.example.org", "b.io", "www.b.io"} <= op.allowed_hosts()
    with pytest.raises(HostNotAllowedError, match="another host"):
        op.fetch("https://api.example.org/a", "t")
    assert seen[-1] == "api.example.org" and "api.github.com" not in seen


def test_apex_redirect_is_refused_and_page_fetched_on_www(tmp_path):
    from nmt_engine.collect import web

    hits = []

    def handler(req):
        hits.append(str(req.url))
        if req.url.host == "invoiceninja.com":
            return httpx.Response(
                301, headers={"Location": f"https://www.invoiceninja.com{req.url.path}"}
            )
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /changelog\n")
        return httpx.Response(200, text="<p>Pro plan 10 EUR per month</p>")

    c = make(tmp_path, handler)
    c.extra_hosts = operator_hosts(["invoiceninja.com"])
    srcs = web.competitor_pages(c, "invoiceninja.com")
    assert [s.url for s in srcs] == ["https://www.invoiceninja.com/pricing"]
    assert "https://www.invoiceninja.com/robots.txt" in hits  # destination robots consulted
    assert "https://www.invoiceninja.com/changelog" not in hits  # www robots forbids it


def test_www_redirect_to_apex_is_refused_and_page_fetched_on_apex(tmp_path):
    from nmt_engine.collect import web

    def handler(req):
        if req.url.host == "www.invoiceninja.com":
            return httpx.Response(
                301, headers={"Location": f"https://invoiceninja.com{req.url.path}"}
            )
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<p>Pro plan</p>")

    c = make(tmp_path, handler)
    c.extra_hosts = operator_hosts(["www.invoiceninja.com"])
    srcs = web.competitor_pages(c, "www.invoiceninja.com")
    assert [s.url for s in srcs] == [
        "https://invoiceninja.com/pricing",
        "https://invoiceninja.com/changelog",
    ]


def test_run_collect_allows_only_competitor_hosts(tmp_path, monkeypatch):
    from nmt_engine.collect import run

    monkeypatch.setenv("NMT_AUTHOR_SALT", "s")
    captured = {}
    monkeypatch.setattr(run, "_steps", lambda p: [])
    real = run.Collector

    def spy(*a, **k):
        captured["c"] = real(*a, **k)
        return captured["c"]

    monkeypatch.setattr(run, "Collector", spy)
    plan = run.CollectPlan(category="x", since=SINCE, competitors=["invoiceninja.com"])
    run.run_collect(plan, tmp_path)
    assert captured["c"].extra_hosts == {"invoiceninja.com", "www.invoiceninja.com"}


def test_redirect_keeps_put_method_and_body(tmp_path):
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, req.content))
        if req.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new"})
        return httpx.Response(200, text="ok")

    make(tmp_path, handler).fetch(
        "https://a.example.org/old", "t", method="PUT", json_body={"x": 1}
    )
    assert seen[1][:2] == ("PUT", "/new") and seen[1][2] == seen[0][2] != b""


def test_cassettes_carry_no_credentials_or_contact_details():
    secret_headers = {"authorization", "proxy-authorization", "cookie", "x-api-key", "user-agent"}
    for path in CASSETTES.glob("*.json.gz"):
        for i in json.loads(gzip.decompress(path.read_bytes()))["interactions"]:
            assert not secret_headers & {k.lower() for k in i["request"]["headers"]}, path
            assert "set-cookie" not in {k.lower() for k in i["response"]["headers"]}, path
            query = dict(parse_qsl(urlparse(i["request"]["uri"]).query))
            assert all(query.get(k, "REDACTED") == "REDACTED" for k in SECRET_QUERY), path
            body = i["response"]["body"].get("string") or ""
            assert scrub_pii(body) == body, path


def test_turnover_skips_only_http_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "k")
    meta = "https://document-api.company-information.service.gov.uk/document/D1"

    def handler(req: httpx.Request) -> httpx.Response:
        if "filing-history" in str(req.url):
            return httpx.Response(200, json={"items": [{"links": {"document_metadata": meta}}]})
        return httpx.Response(406)

    assert companies_house.turnover(make(tmp_path, handler), "01234567") is None
