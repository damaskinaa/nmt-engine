"""Seeded known-truth markets for testing the synthetic-evidence maths (PR 2).

Each world has segments with true Q1-Q4. Every method family estimates each quantity with a
multiplicative bias and lognormal noise. Family errors share a common market shock with
correlation `rho` (methods read the same market, so their errors are not independent). Each
family also gets a reference class of past cases with known truth, drawn from the same error
process, for calibration. Stated method intervals are deliberately overconfident.
"""

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from nmt_engine.schema import BacktestCase, Calc, CalcInput, Calibration, Quantity
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


@dataclass
class World:
    config: WorldConfig
    truth: dict[tuple[str, str], float]  # (segment, quantity) -> true value
    methods: dict[tuple[str, str], list[MethodInput]]  # (segment, quantity) -> estimates
    reference: dict[tuple[str, str], list[BacktestCase]]  # (family, quantity) -> cases
    calcs: list[Calc]
    family_bias: dict[str, float]
    family_noise: dict[str, float]


def _errors(rng: np.random.Generator, noise: list[float], rho: float, size: int) -> np.ndarray:
    """(size, k) log errors: unit normals sharing one common factor with correlation rho."""
    common = rng.standard_normal((size, 1))
    own = rng.standard_normal((size, len(noise)))
    return (math.sqrt(rho) * common + math.sqrt(1 - rho) * own) * np.array(noise)


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
    reference: dict[tuple[str, str], list[BacktestCase]] = {}
    calcs: list[Calc] = []
    for q in QUANTITIES:
        unit = TRUTH_RANGE[q][2]
        ref_truth = draw_truth(q, cfg.n_reference)
        ref_pred = ref_truth[:, None] * np.exp(
            log_bias + _errors(rng, noise_l, cfg.rho, cfg.n_reference)
        )
        for j, f in enumerate(fams):
            reference[(f, q)] = [
                BacktestCase(
                    case=f"ref-{q}-{i}",
                    as_of=date(2020 + i % 5, 1 + i % 12, 1),
                    known_outcome=float(ref_truth[i]),
                    predicted=float(ref_pred[i, j]),
                )
                for i in range(cfg.n_reference)
            ]
        seg_truth = draw_truth(q, cfg.n_segments)
        seg_pred = seg_truth[:, None] * np.exp(
            log_bias + _errors(rng, noise_l, cfg.rho, cfg.n_segments)
        )
        for s in range(cfg.n_segments):
            seg = f"SEG{s + 1}"
            truth[(seg, q)] = float(seg_truth[s])
            ms = []
            for j, f in enumerate(fams):
                med = float(seg_pred[s, j])
                h = Z80 * cfg.stated_sigma_ratio * noise[f]
                cid = f"W{cfg.seed}-{seg}-{q}-{f}"
                ms.append(MethodInput(f, cid, med, med * math.exp(-h), med * math.exp(h)))
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
                        interval_80=(med * math.exp(-h), med * math.exp(h)),
                        unit=unit,
                        geography="WORLD",
                    )
                )
            methods[(seg, q)] = ms
    return World(cfg, truth, methods, reference, calcs, bias, noise)


def calibrations_for(world: World) -> dict[str, dict[str, Calibration]]:
    """Quantity -> family -> Calibration fitted on the world's reference classes."""
    from nmt_engine.synth.calibrate import calibration_record

    out: dict[str, dict[str, Calibration]] = {}
    for (f, q), cases in sorted(world.reference.items()):
        out.setdefault(q, {})[f] = calibration_record(
            f"CAL-W{world.config.seed}-{f}-{q}",
            f,
            f"world {world.config.seed} {q}",
            f"cases dated <= {AS_OF}",
            cases,
            quantity=q,
            as_of=AS_OF,
        )
    return out


def coverage(world: World) -> float:
    """Share of (segment, quantity) truths inside the calibrated triangulated 80% interval."""
    from nmt_engine.synth.estimate import estimate

    cals = calibrations_for(world)
    hits = 0
    for (seg, q), ms in world.methods.items():
        syn, _ = estimate(f"Y-{seg}-{q}", q, "WORLD", ms, cals[q], rho=world.config.rho)
        lo, hi = syn.combined.interval_80  # type: ignore[union-attr]
        hits += lo <= world.truth[(seg, q)] <= hi
    return hits / len(world.methods)
