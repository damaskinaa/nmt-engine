"""Print the misspecification coverage matrix (markdown) over seeded known-truth worlds."""

import sys

from nmt_engine.synth.world import FALLBACK_CELLS, MATRIX_CELLS, mean_coverage


def main(n_worlds: int = 200) -> None:
    print("| true ρ | stated/true σ | errors | coverage |")
    print("|---|---|---|---|")
    for c in MATRIX_CELLS:
        tails = f"Student-t df={c['t_df']:g}" if "t_df" in c else "normal"
        cov = mean_coverage(c, n_worlds)
        print(f"| {c['rho']:g} | {c['stated_sigma_ratio']:g} | {tails} | {cov:.1%} |", flush=True)
    for c in FALLBACK_CELLS:
        print(f"| fallback {c} | | | {mean_coverage(c, n_worlds):.1%} |", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
