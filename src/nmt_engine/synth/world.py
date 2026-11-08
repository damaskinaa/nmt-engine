"""Seeded known-truth markets for testing the synthetic-evidence maths (PR 2).

Each world has segments with true Q1-Q4. Every method family estimates each quantity with a
multiplicative bias and lognormal noise. Family errors share a common market shock with
correlation `rho` (methods read the same market, so their errors are not independent); with
`t_df` set, errors are multivariate Student-t (heavy tails) with the same sd. Each quantity has
a JOINT reference class: past cases with known truth that every family estimated, drawn from the
same error process. The estimator never sees `rho`; it estimates it from those cases.
Stated method intervals are overconfident by `stated_sigma_ratio`.
"""

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from nmt_engine.schema import Calc, CalcInput, Calibration, JointCalibration, JointCase, Quantity
from nmt_engine.synth.estimate import MethodInput
from nmt_engine.synth.logform import Z80

QUANTITIES: tuple[Quantity, ...] = ("Q1", "Q2", "Q3", "Q4")
FAMILIES: tuple[str, ...] = ("statistical", "supply", "revealed_price", "behavioural")
# log-uniform truth ranges and units
TRUTH_RANGE: dict[str, tuple[float, float, str]] = {
    "Q1": (5e3, 5e5, "businesses"),
    "Q2": (1.0, 50.0, "1/year"),
    "Q3": (100.0, 10_000.0, "EUR/year"),
    "Q4": (5.0, 200.0, "EUR/month"),
}
AS_OF = date(2026, 1, 1)


@dataclass(frozen=True)
class WorldConfig:
    seed: int
    n_segments: int = 10
    n_reference: int = 30
    families: tuple[str, ...] = FAMILIES[:3]
    bias: dict[str, float] = field(default_factory=dict)  # family -> multiplicative bias
    noise: tuple[float, float] = (0.2, 0.45)  # range of per-family log-noise sd
    stated_sigma_ratio: float = 0.6  # stated interval sd / true noise sd (overconfident)
    rho: float = 0.3
    t_df: float | None = None  # Student-t errors with this many degrees of freedom
    partial_reference: dict[str, int] = field(default_factory=dict)  # family -> cases it estimated


@dataclass
class World:
    config: WorldConfig
    truth: dict[tuple[str, str], float]  # (segment, quantity) -> true value
    methods: dict[tuple[str, str], list[MethodInput]]  # (segment, quantity) -> estimates
    reference: dict[str, list[JointCase]]  # quantity -> joint reference cases
    calcs: list[Calc]
    family_bias: dict[str, float]
    family_noise: dict[str, float]


def _errors(
    rng: np.random.Generator, noise: list[float], rho: float, size: int, t_df: float | None
) -> np.ndarray:
    """(size, k) log errors with sd `noise` and pairwise correlation rho: normals sharing one
    common factor, or multivariate Student-t (unit-variance scaled) when t_df is set."""
    common = rng.standard_normal((size, 1))
    own = rng.standard_normal((size, len(noise)))
    z = math.sqrt(rho) * common + math.sqrt(1 - rho) * own
    if t_df is not None:
        z *= np.sqrt((t_df - 2) / rng.chisquare(t_df, (size, 1)))
    return z * np.array(noise)


def _stated(med: float, noise: float, cfg: WorldConfig) -> tuple[float, float]:
    h = Z80 * cfg.stated_sigma_ratio * noise
    return med * math.exp(-h), med * math.exp(h)


def generate_world(cfg: WorldConfig) -> World:
    rng = np.random.default_rng(cfg.seed)
    fams = list(cfg.families)
    bias = {f: cfg.bias.get(f, float(np.exp(rng.normal(0, 0.15)))) for f in fams}
    noise_l = [float(rng.uniform(*cfg.noise)) for _ in fams]
    noise = dict(zip(fams, noise_l, strict=True))
    log_bias = np.array([math.log(bias[f]) for f in fams])

    def draw_truth(q: str, size: int) -> np.ndarray:
        lo, hi, _ = TRUTH_RANGE[q]
        return np.exp(rng.uniform(math.log(lo), math.log(hi), size))

    truth: dict[tuple[str, str], float] = {}
    methods: dict[tuple[str, str], list[MethodInput]] = {}
    reference: dict[str, list[JointCase]] = {}
    calcs: list[Calc] = []
    for q in QUANTITIES:
        unit = TRUTH_RANGE[q][2]
        ref_truth = draw_truth(q, cfg.n_reference)
        ref_pred = ref_truth[:, None] * np.exp(
            log_bias + _errors(rng, noise_l, cfg.rho, cfg.n_reference, cfg.t_df)
        )
        reference[q] = []
        for i in range(cfg.n_reference):
            has = [f for f in fams if i < cfg.partial_reference.get(f, cfg.n_reference)]
            pred = {f: float(ref_pred[i, fams.index(f)]) for f in has}
            reference[q].append(
                JointCase(
                    case=f"ref-{q}-{i}",
                    as_of=date(2020 + i % 5, 1 + i % 12, 1),
                    known_outcome=float(ref_truth[i]),
                    predicted=pred,
                    stated_interval_80={f: _stated(pred[f], noise[f], cfg) for f in has},
                )
            )
        seg_truth = draw_truth(q, cfg.n_segments)
        seg_pred = seg_truth[:, None] * np.exp(
            log_bias + _errors(rng, noise_l, cfg.rho, cfg.n_segments, cfg.t_df)
        )
        for s in range(cfg.n_segments):
            seg = f"SEG{s + 1}"
            truth[(seg, q)] = float(seg_truth[s])
            ms = []
            for j, f in enumerate(fams):
                med = float(seg_pred[s, j])
                lo, hi = _stated(med, noise[f], cfg)
                cid = f"W{cfg.seed}-{seg}-{q}-{f}"
                ms.append(MethodInput(f, cid, med, lo, hi))
                calcs.append(
                    Calc(
                        id=cid,
                        quantity=q,
                        method_family=f,
                        formula="estimate",
                        inputs=[
                            CalcInput(
                                name="estimate",
                                value=med,
                                unit=unit,
                                source_id=f"W{cfg.seed}-{f}",
                                as_of_date=AS_OF,
                            )
                        ],
                        median=med,
                        interval_80=(lo, hi),
                        unit=unit,
                        geography="WORLD",
                    )
                )
            methods[(seg, q)] = ms
    return World(cfg, truth, methods, reference, calcs, bias, noise)


def joint_calibrations_for(
    world: World,
) -> dict[str, tuple[JointCalibration, dict[str, Calibration]]]:
    """Quantity -> (JointCalibration, family -> Calibration) fitted on the joint reference."""
    from nmt_engine.synth.calibrate import joint_calibration

    return {
        q: joint_calibration(
            f"CAL-W{world.config.seed}-{q}",
            q,
            f"world {world.config.seed} {q}",
            f"cases dated <= {AS_OF}",
            cases,
            as_of=AS_OF,
        )
        for q, cases in sorted(world.reference.items())
    }


def calibrations_for(world: World) -> dict[str, dict[str, Calibration]]:
    """Quantity -> family -> Calibration fitted on the world's joint reference classes."""
    return {q: cals for q, (_, cals) in joint_calibrations_for(world).items()}


def coverage(world: World) -> float:
    """Share of (segment, quantity) truths inside the calibrated triangulated 80% interval.
    The estimator gets only the methods and the joint reference, never `config.rho`."""
    from nmt_engine.synth.estimate import estimate

    fitted = joint_calibrations_for(world)
    hits = 0
    for (seg, q), ms in world.methods.items():
        joint, cals = fitted[q]
        syn, _ = estimate(f"Y-{seg}-{q}", q, "WORLD", ms, cals, joint=joint)
        lo, hi = syn.combined.interval_80  # type: ignore[union-attr]
        hits += lo <= world.truth[(seg, q)] <= hi
    return hits / len(world.methods)


# misspecification matrix: true rho x stated-interval ratio, plus a heavy-tailed world
MATRIX_CELLS: tuple[dict, ...] = (
    *({"rho": r, "stated_sigma_ratio": s} for r in (0.0, 0.3, 0.6, 0.8) for s in (0.4, 0.6, 1.0)),
    {"rho": 0.3, "stated_sigma_ratio": 0.6, "t_df": 3.0},
)
# calibration-failure fallback: a family with too few reference cases; every family failing
FALLBACK_CELLS: tuple[dict, ...] = (
    {"families": FAMILIES, "partial_reference": {"behavioural": 12}},
    {"n_reference": 15},
)


def mean_coverage(cell: dict, n_worlds: int = 200, seed0: int = 0) -> float:
    return float(
        np.mean(
            [coverage(generate_world(WorldConfig(seed=seed0 + s, **cell))) for s in range(n_worlds)]
        )
    )
