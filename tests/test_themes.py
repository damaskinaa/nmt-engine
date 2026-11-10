import numpy as np

from nmt_engine.radar import themes


def test_merge_is_fixed_quantile_and_counts_each_author_once():
    rng = np.random.default_rng(0)
    base = {"a": np.eye(4)[0], "b": np.eye(4)[1]}
    vec, post, groups = {}, {}, []
    spec = [("a", "X"), ("a", "X"), ("b", "Y"), ("b", "Z")]
    for g, (axis, app) in enumerate(spec):
        ids = [f"{g}-{i}" for i in range(5)]
        for i in ids:
            v = base[axis] + 0.01 * rng.normal(size=4)
            vec[i] = v / np.linalg.norm(v)
            post[i] = {"author": f"u{g}-{i[-1]}", "app": app}
        groups.append({"group": g, "members": ids, "authors": 5, "name": f"g{g}"})
    post["1-0"]["author"] = post["0-0"]["author"]  # one author in two merged groups
    doc = themes.themes(groups, vec, post)
    assert doc["quantile"] == 0.25
    assert [t["groups"] for t in doc["themes"]] == [[2, 3], [0, 1]]  # most voices first
    second, first = doc["themes"]
    assert first["authors"] == 9 and first["author_sum_of_groups"] == 10
    assert first["concentration"] == {"top_app": "X", "top_share": 1.0, "flag": "mostly one app: X"}
    assert second["concentration"]["top_share"] == 0.5 and second["concentration"]["flag"] is None
    assert groups[0]["concentration"]["flag"] == "mostly one app: X"
