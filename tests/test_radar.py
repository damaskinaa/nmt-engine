import numpy as np

from nmt_engine.radar import build


class FakeEmb:
    def embed(self, texts, purpose=""):
        rng = np.random.default_rng(len(texts))
        base = rng.normal(size=(3, 8))
        return np.array([base[i % 3] + 0.01 * rng.normal(size=8) for i in range(len(texts))])


def test_allow_list_drops_unrelated_listings():
    assert build.app_of("https://apps.apple.com/us/app/id584606479#review-1") == "QuickBooks"
    assert build.app_of("https://apps.apple.com/us/app/id1523884528#review-1") is None


def test_alternatives_one_vote_per_author_and_not_self():
    posts = [
        {"app": "Xero", "author": "a", "text": "Moved from QuickBooks to Xero"},
        {"app": "Xero", "author": "a", "text": "QuickBooks again"},
        {"app": "Xero", "author": "b", "text": "I used a spreadsheet and QuickBooks"},
    ]
    alt = build.alternatives(posts)["Xero"]
    assert alt["QuickBooks"] == 2 and "Xero" not in alt


def test_groups_are_deterministic_and_flag_thin():
    posts = [
        {
            "id": f"p{i}",
            "author": f"a{i % 4}",
            "app": "Xero" if i % 2 else "Bonsai",
            "year": 2025,
            "country": "US",
            "text": f"post {i}",
        }
        for i in range(30)
    ]
    k = build.K
    build.K = 3
    try:
        a, b = build.groups(FakeEmb(), posts), build.groups(FakeEmb(), posts)
    finally:
        build.K = k
    assert [g["members"] for g in a] == [g["members"] for g in b]
    assert sum(g["posts"] for g in a) == 30
    assert all(g["thin"] == (g["authors"] < 3 or len(g["apps"]) < 2) for g in a)


def test_source_text_cannot_leave_run_dir(tmp_path):
    import pytest

    from nmt_engine.store import read_text_in

    (tmp_path / "a.txt").write_text("ok", "utf-8")
    assert read_text_in(tmp_path, "a.txt") == "ok"
    with pytest.raises(ValueError):
        read_text_in(tmp_path / "sub", "../a.txt")
