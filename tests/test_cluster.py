import json

import numpy as np
import pytest

from nmt_engine.llm import LLM
from nmt_engine.miner import cluster as cl
from nmt_engine.miner.extract import JobInstance


def inst(statement, level="core", job=None, sid=None):
    spans = {"job": [job]} if job else {}
    return JobInstance(
        sid or f"s_{statement}", "other", statement, level, "regular", None, None, spans
    )


def test_instance_text_uses_first_job_span():
    assert cl.instance_text(inst("I want to x", job="span one")) == "I want to x\nspan one"
    assert cl.instance_text(inst("I want to x")) == "I want to x"


def test_pair_index_inverts_condensed_order():
    n, k = 7, 0
    for i in range(n):
        for j in range(i + 1, n):
            assert cl.pair_index(k, n) == (i, j)
            k += 1


def test_majority_level_ties_follow_prereg_order():
    assert cl.majority_level(["big", "small"]) == "small"
    assert cl.majority_level(["micro", "big"]) == "big"
    assert cl.majority_level(["big", "big", "core"]) == "big"
    assert cl.majority_level(["small", "core"]) == "core"


def test_choose_threshold_max_f1_smaller_t_on_ties():
    th = cl.choose_threshold([0.1, 0.2, 0.5, 0.6], [True, True, False, False])
    assert th.t == pytest.approx(0.2) and th.f1 == 1.0 and th.precision == th.recall == 1.0
    curve = {p["t"]: p["f1"] for p in th.curve}
    assert curve[0.49] == 1.0  # same F1 further right, smaller t kept


def test_sample_pairs_bands_and_even_split():
    rng = np.random.default_rng(0)
    vecs = {c: rng.normal(size=(40, 5)) for c in ("a", "b", "c")}
    dists = {c: cl.cosine_linkage(v)[0] for c, v in vecs.items()}
    pairs, edges = cl.sample_pairs(dists, {c: 40 for c in vecs}, bands=4, per_band=6, seed=1)
    pooled = np.concatenate(list(dists.values()))
    assert edges[0] == 0 and edges[-1] == pytest.approx(np.median(pooled))
    for b in range(4):
        band = [p for p in pairs if p.band == b]
        assert len(band) == 6 and all(edges[b] <= p.distance <= edges[b + 1] + 1e-9 for p in band)
    for p in pairs:  # distance matches the instances it names
        d = 1 - vecs[p.category][p.a] @ vecs[p.category][p.b] / (
            np.linalg.norm(vecs[p.category][p.a]) * np.linalg.norm(vecs[p.category][p.b])
        )
        assert d == pytest.approx(p.distance, abs=1e-5)
    assert pairs == cl.sample_pairs(dists, {c: 40 for c in vecs}, bands=4, per_band=6, seed=1)[0]


def unit(*xs):
    v = np.array(xs, dtype=float)
    return v / np.linalg.norm(v)


# 0,1 tight; 2 joins them only in the loose cut; 3 far away.
VECS = np.stack([unit(1, 0, 0), unit(1, 0.05, 0), unit(1, 0.45, 0), unit(0, 0, 1)])
INSTS = [
    inst("I want to a", "core"),
    inst("I want to a2", "big"),
    inst("I want to b", "big"),
    inst("I want to z", "micro"),
]


class Scripted(LLM):
    def __init__(self, tmp, confirm, name):
        super().__init__(tmp, provider="openai", model="m")
        self.answers = {"miner.confirm": confirm, "miner.name": name}
        self.prompts = []

    def complete(self, prompt, system="", purpose="", json_mode=False, check=None):
        self.prompts.append((purpose, prompt))
        return json.dumps(self.answers[purpose])


def test_cut_tight_and_loose_and_no_llm_keeps_tight(tmp_path):
    _, tree = cl.cosine_linkage(VECS)
    d02 = 1 - VECS[0] @ VECS[2]
    t = float(d02)  # loose cut (t + 0.05) joins 2, tight (t - 0.05) does not
    res = cl.cluster_category(INSTS, VECS, t, None, "x", tree)
    assert sorted(c.members for c in res.clusters) == [[0, 1], [2], [3]]
    assert {tuple(c.members): c.level for c in res.clusters}[(0, 1)] == "core"


def test_confirm_merges_only_inside_loose_cluster(tmp_path):
    t = float(1 - VECS[0] @ VECS[2])
    llm = Scripted(
        tmp_path,
        {"groups": [{"ids": [0, 1]}]},
        {"clusters": [{"id": 0, "name": "I want to do a", "mixed": True}]},
    )
    res = cl.cluster_category(INSTS, VECS, t, llm, "x")
    assert sorted(c.members for c in res.clusters) == [[0, 1, 2], [3]]
    confirms = [p for k, p in llm.prompts if k == "miner.confirm"]
    assert len(confirms) == 1 and "I want to z" not in confirms[0]  # 3 is never offered
    big = res.clusters[0]
    assert big.name == "I want to do a" and big.mixed and res.merges == 1


def test_bad_names_keep_representative(tmp_path):
    t = float(1 - VECS[0] @ VECS[2])
    llm = Scripted(tmp_path, {"groups": []}, {"clusters": [{"id": 0, "name": "Track habits"}]})
    res = cl.cluster_category(INSTS, VECS, t, llm, "x")
    assert res.clusters[0].members == [0, 1] and res.clusters[0].name.startswith("I want to a")
    assert res.clusters[0].mixed  # no verdict on its outcomes: it cannot pass


def test_naming_shows_every_distinct_member(tmp_path):
    insts = [inst(f"I want to do thing {k % 12}", sid=f"s{k}") for k in range(15)]
    clusters = [cl.Cluster(list(range(15)), insts[0].statement)]
    llm = Scripted(tmp_path, {}, {"clusters": [{"id": 0, "name": "I want to do", "mixed": False}]})
    cl.name_clusters(llm, clusters, insts, "x")
    prompt = llm.prompts[0][1]
    assert all(f"thing {k}\n" in prompt or prompt.endswith(f"thing {k}") for k in range(12))
    assert prompt.count("thing 0") == 1 and not clusters[0].mixed


def test_to_groups_keys_are_stable_and_carry_level_and_mixed():
    res = cl.ClusterResult([cl.Cluster([0, 1], "I want to a", True, "core")], 0.2)
    g1 = cl.to_groups(res, INSTS)[0]
    g2 = cl.to_groups(res, INSTS)[0]
    assert g1.key == g2.key and g1.key.startswith("cl_") and g1.mixed and g1.level == "core"
