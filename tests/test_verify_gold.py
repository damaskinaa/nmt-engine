"""L3 author gate / element tags (verbatim guard, retries) and the committed gold-set CI gate."""

from __future__ import annotations

import json

import pytest

from nmt_engine.llm import LLM, LLMError
from nmt_engine.verify import gold, prompts
from nmt_engine.verify.author import Post, author_gate, parse_author, tag_elements

POSTS = [
    Post(
        "a", "invoicing", "I switched from FreshBooks to a spreadsheet because it got too pricey."
    ),
    Post("b", "invoicing", "We are building an open source invoicing app, feedback welcome."),
]


class Scripted(LLM):
    """Answers from a queue of JSON payloads; records prompts."""

    def __init__(self, tmp_path, answers):
        super().__init__(tmp_path, no_llm=False, cache_dir=tmp_path / "c")
        self.answers, self.prompts = list(answers), []

    def complete_json(self, prompt, system="", purpose=""):
        self.prompts.append(prompt)
        ans = self.answers.pop(0)
        if isinstance(ans, Exception):
            raise ans
        return ans


def test_author_gate_keeps_only_verbatim_answers_and_retries(tmp_path):
    bad = {"id": 0, "role": "USER", "role_quote": "I moved off FreshBooks", "names_solution": False}
    good_b = {"id": 1, "role": "BUILDER", "role_quote": "We are building", "names_solution": False}
    good_a = {
        "id": 0,
        "role": "USER",
        "role_quote": "I switched from  FreshBooks",
        "names_solution": True,
        "solution": "spreadsheet",
        "solution_quote": "a spreadsheet",
    }
    llm = Scripted(tmp_path, [{"posts": [bad, good_b]}, {"posts": [good_a]}])
    a, b = author_gate(llm, POSTS)
    assert a.role == "USER" and a.continues and b.role == "BUILDER" and not b.continues
    assert "Retry 1" in llm.prompts[1] and llm.prompts[0] != llm.prompts[1]


def test_unanswered_posts_stay_none(tmp_path):
    llm = Scripted(tmp_path, [LLMError("x"), {"posts": "nope"}, {"posts": [{"id": 9}]}])
    assert author_gate(llm, POSTS) == [None, None]


def test_parse_author_rejects_unknown_role_and_unquoted_solution():
    text = POSTS[0].text
    assert (
        parse_author({"role": "FAN", "role_quote": "I switched", "names_solution": False}, text)
        is None
    )
    row = {
        "role": "USER",
        "role_quote": "I switched",
        "names_solution": True,
        "solution_quote": "Xero",
    }
    assert parse_author(row, text) is None


def test_element_yes_needs_a_quote(tmp_path):
    row = {e: False for e in prompts.ELEMENTS} | {"id": 0}
    yes = row | {"problem": True, "problem_quote": "it got too pricey"}
    fake = row | {"aha": True, "aha_quote": "loved it instantly"}
    llm = Scripted(tmp_path, [{"posts": [yes]}])
    assert tag_elements(llm, POSTS[:1], rounds=1)[0]["problem"] is True
    llm = Scripted(tmp_path, [{"posts": [fake]}])
    assert tag_elements(llm, POSTS[:1], rounds=1) == [None]


def test_committed_gold_has_no_post_text_or_emails():
    for name in ("items.jsonl", "gold.jsonl"):
        for line in (gold.GOLD_DIR / name).read_text().splitlines():
            row = json.loads(line)
            assert not {"text", "role_quote"} & set(row) and "@" not in json.dumps(row)


def test_gold_split_is_200_dev_100_test():
    rows = [json.loads(x) for x in (gold.GOLD_DIR / "items.jsonl").read_text().splitlines()]
    assert len(rows) == 300 and sum(r["split"] == "test" for r in rows) == 100


def test_ci_precision_gate_on_current_prompts():
    """§8 A1: a prompt change without a re-recording fails here; so does test precision < 85%."""
    res = gold.check()
    assert "error" not in res, f"{res['error']}: run `nmt gold record` and commit the file"
    failing = {k: v["test"] for k, v in res["classes"].items() if not res["passed"]}
    assert res["passed"], json.dumps(failing, indent=1)


def test_prompt_change_changes_hash(monkeypatch):
    h = gold.prompt_hash()
    monkeypatch.setattr(prompts, "AUTHOR_PROMPT", prompts.AUTHOR_PROMPT + " ")
    assert gold.prompt_hash() != h
    with pytest.raises(AssertionError):
        assert "error" not in gold.check()


def test_small_counts_are_not_measured_not_passed():
    res = gold.check()
    for name, c in res["classes"].items():
        t = c["test"]
        assert (t["status"] == "NOT MEASURED") == (t["called"] < gold.MIN_CALLS), name
        assert (name in res["t1_passed_for"]) == (t["status"] == "PASS")


def test_cross_agreement_is_reported_per_class(tmp_path):
    rec = {
        "model": "z-ai/glm-5.3",
        "answers": {
            g["id"]: {k: g[k] for k in ("role", "names_solution", "elements")}
            for g in gold._read_jsonl(gold.GOLD_DIR / "gold.jsonl")
        },
    }
    path = tmp_path / "cross.json"
    path.write_text(json.dumps(rec), "utf-8")
    res = gold.cross_agreement(path)
    assert res["kind"].startswith("cross-model agreement")
    assert res["role"]["agreement"] == 1.0 and res["role"]["kappa"] == 1.0 and res["passed"]
    assert set(res["classes"]) >= {"USER", "BUILDER", "VENDOR", "OTHER", "problem", "aha"}


def test_build_keeps_one_copy_of_a_source_shared_by_two_runs(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS

    runs = {}
    for name in ("r1", "r2"):
        rd = tmp_path / name
        (rd / "t").mkdir(parents=True)
        srcs = {}
        for i in range(6):
            (rd / "t" / f"s{i}.txt").write_text(f"post {i}")
            srcs[f"s{i}"] = NS(
                id=f"s{i}",
                retracted=False,
                customer_voice=True,
                platform="hackernews",
                evidence_family="discussion",
                url=f"https://x/{i}",
                text_path=f"t/s{i}.txt",
            )
        runs[rd] = NS(sources=srcs)
    monkeypatch.setattr(gold, "load_run", lambda rd: runs[rd])
    monkeypatch.setattr(gold, "N_GOLD", 6)
    monkeypatch.setattr(gold, "N_TEST", 3)
    monkeypatch.setattr(gold, "CACHE_DIR", tmp_path / "cache")
    gold.build(list(runs), "invoicing", out=tmp_path / "gold")
    rows = [json.loads(x) for x in (tmp_path / "gold" / "items.jsonl").read_text().splitlines()]
    assert sorted(r["source_id"] for r in rows) == [f"s{i}" for i in range(6)]
