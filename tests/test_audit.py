import json

from nmt_engine.llm import LLM
from nmt_engine.miner import audit, prompts
from nmt_engine.miner.extract import JobInstance


class Scripted(LLM):
    def __init__(self, tmp, answer):
        super().__init__(tmp, provider="openai", model="m")
        self.answer, self.prompts = answer, []

    def complete(self, prompt, system="", purpose="", json_mode=False, check=None):
        self.prompts.append(prompt)
        return json.dumps(self.answer(prompt))


def test_label_pairs_batches_by_category_and_ignores_bad_rows(tmp_path):
    def answer(prompt):
        return {
            "pairs": [{"id": 0, "same": True}, {"id": 1, "same": "yes"}, {"id": 9, "same": True}]
        }

    llm = Scripted(tmp_path, answer)
    pairs = [("a", "x", "y"), ("b", "p", "q"), ("a", "u", "v")]
    assert audit.label_pairs(llm, pairs, rounds=1) == [True, True, None]
    assert len(llm.prompts) == 2 and "Category: a" in llm.prompts[0]


def inst(n, **spans):
    return JobInstance(
        f"s{n}",
        "other",
        f"I want to {n}",
        "core",
        "regular",
        None,
        None,
        dict(spans),
        [("fast", f"crit {n}")],
        [("X", f"alt {n}")],
    )


def test_sample_spans_is_seeded_and_capped_per_element():
    insts = {"c": [inst(i, trigger=[f"trig {i}"], job=[f"job {i}"]) for i in range(8)]}
    a = audit.sample_spans(insts, per=5, seed=3)
    assert a == audit.sample_spans(insts, per=5, seed=3)
    by = {el: sum(s.element == el for s in a) for el in prompts.ELEMENTS}
    assert by["trigger"] == by["job"] == by["success_criteria"] == by["alternatives"] == 5
    assert by["context"] == 0


def test_audit_spans_and_wilson_exclusion(tmp_path):
    spans = [audit.Span("c", f"s{i}", "I want to x", "trigger", f"q{i}") for i in range(20)]
    spans += [audit.Span("c", f"t{i}", "I want to x", "job", f"j{i}") for i in range(20)]

    def answer(prompt):  # every trigger is wrong, every job right
        body = prompt.split("labelled as that element:\n\n", 1)[1].split("\n\nFor each item")[0]
        rows = [{"id": n, "correct": "element: job" in b} for n, b in enumerate(body.split("\n\n"))]
        return {"items": rows}

    v = audit.audit_spans(Scripted(tmp_path, answer), spans, batch=7)
    assert None not in v
    rates = audit.mislabel_rates(spans, v)
    assert rates["trigger"]["rate"] == 1.0 and rates["trigger"]["excluded"]
    assert rates["job"]["rate"] == 0.0 and not rates["job"]["excluded"]
    assert rates["context"]["n"] == 0 and not rates["context"]["excluded"]
    lo, hi = rates["trigger"]["wilson95"]
    assert 0.8 < lo < 0.85 and hi == 1.0


def test_blind_sample_and_agreement():
    s = audit.blind_sample(10, 4, 1, exclude=[0, 1])
    assert len(s) == 4 and not {0, 1} & set(s) and s == audit.blind_sample(10, 4, 1, [0, 1])
    assert audit.agreement([True, False, True], [True, True, True]) == 0.6667


def test_unanswered_items_are_asked_again(tmp_path):
    seen = []

    def answer(prompt):  # first request drops item 1; later requests answer everything
        seen.append(prompt)
        rows = [{"id": n, "same": True} for n in range(3)]
        return {"pairs": rows[:1] + rows[2:] if len(seen) == 1 else rows}

    llm = Scripted(tmp_path, answer)
    pairs = [("a", "x", "y"), ("a", "p", "q"), ("a", "u", "v")]
    assert audit.label_pairs(llm, pairs) == [True, True, True]
    assert len(seen) == 2 and "A: p" in seen[1] and "A: x" not in seen[1]
    stubborn = Scripted(tmp_path / "s", lambda p: {"pairs": []})
    assert audit.label_pairs(stubborn, pairs[:1]) == [None]
    assert len(stubborn.prompts) == audit.ROUNDS
    assert len(set(stubborn.prompts)) == audit.ROUNDS  # retries never hit the cache key


def test_author_roles_batches_by_category(tmp_path):
    llm = Scripted(tmp_path, lambda p: {"posts": [{"id": 0, "builder": "I built" in p}]})
    posts = [("a", "I built this app"), ("b", "looking for an app")]
    assert audit.author_roles(llm, posts) == [True, False]
    assert len(llm.prompts) == 2 and "Category: a" in llm.prompts[0]
