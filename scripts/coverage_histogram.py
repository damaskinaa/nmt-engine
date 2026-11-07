"""Plot per-world coverage of calibrated triangulated 80% intervals over 200 seeded worlds."""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from nmt_engine.synth.world import WorldConfig, coverage, generate_world  # noqa: E402


def main(out: Path, n_worlds: int = 200) -> float:
    cov = np.array([coverage(generate_world(WorldConfig(seed=s))) for s in range(n_worlds)])
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(cov, bins=np.arange(0.375, 1.0626, 0.05), color="#4a7abc", edgecolor="white")
    ax.axvline(0.8, color="black", ls="--", label="nominal 80%")
    ax.axvline(cov.mean(), color="#c0392b", label=f"pooled {cov.mean():.1%}")
    ax.axvspan(0.75, 0.85, color="#2ecc71", alpha=0.15, label="acceptance band 75-85%")
    ax.set_xlabel("per-world coverage (10 segments x Q1-Q4 = 40 truths per world)")
    ax.set_ylabel("worlds")
    ax.set_title(f"Calibrated triangulated 80% intervals, {n_worlds} seeded worlds")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    return float(cov.mean())


if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/img/coverage_histogram.png")
    print(f"pooled coverage {main(path):.3f} -> {path}")
