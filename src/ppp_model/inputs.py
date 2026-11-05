"""Inputs: load the YAML assumption files, convert them to typed dataclasses and validate them.

README §8 lists every input. The YAML files in ``config/`` mirror the dataclasses below one to
one, so every assumption the calculation uses lives in a config file, not in the code.

Validation is strict: unknown keys, wrong types, out-of-range values and inconsistent
combinations are all reported (together) as an :class:`InputValidationError`. Nothing is
silently clipped or replaced.

Scenario levers (traffic shortfall, cost overrun, delay, rate shock) live in the ``stress``
block, so a scenario is just a small override of that block (README §10.1). The README's
short symbols map to YAML keys as documented in ``docs/model_methodology.md``.
"""

from __future__ import annotations

import copy
import dataclasses
import difflib
import functools
import math
import types
from dataclasses import MISSING, dataclass, field
from pathlib import Path
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

import yaml

from .errors import InputValidationError

RUPEES_PER_CRORE = 1.0e7
"""Unit definition (README §4): 1 crore = 10^7 rupees. Used once, to convert ₹ to ₹ crore."""

PROJECT_TYPES = ("toll", "metro", "ham")
REPAYMENT_PROFILES = ("equal", "annuity", "structured", "sculpted")
SUM_TOLERANCE = 1e-9
"""Tolerance for 'shares must sum to 100%' checks (README §12.1 check 2)."""


# ---------------------------------------------------------------------------------------------
# Dataclasses (one per YAML block)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectInputs:
    name: str
    type: Literal["toll", "metro", "ham"]
    first_fiscal_year: int = 2026  # label only: model year 1 = FY2026-27


@dataclass(frozen=True)
class TimelineInputs:
    construction_years: int  # Tc
    concession_years: int  # Tcon, counted from the appointed date
    concession_end_fixed: bool = True  # README §9.1: a delay shortens operations, never extends the concession
    indexation_basis: Literal["cod", "calendar"] = "cod"  # exponent k-1 (README) or years since scheduled COD


@dataclass(frozen=True)
class CapexInputs:
    base_cost: float  # C0, ₹ Cr at today's prices
    phasing: tuple[float, ...]  # p_t by construction year, sums to 1
    escalation: float  # e_c, p.a.
    contingency: float  # share of hard cost
    preop: float  # pre-operative expenses, share of hard cost


@dataclass(frozen=True)
class FundingInputs:
    gearing: float  # g, debt share of the funding need
    grant_pct: float  # grant / VGF as a share of capex
    grant_covers_overrun: bool  # False: VGF fixed at award, so an overrun is not grant-funded
    equity_mode: Literal["pro_rata", "equity_first"]
    drawdown_timing: float  # m, share of the year a construction drawdown earns interest (0.5 = mid-year)
    upfront_fee: float  # share of debt at COD, paid in model year 1


@dataclass(frozen=True)
class DebtInputs:
    interest_rate: float  # r, all-in p.a.
    tenor_years: int  # n, repayment years after the moratorium
    moratorium_years: int  # mor, interest-only years after COD
    profile: Literal["equal", "annuity", "structured", "sculpted"]
    structured_pct: tuple[float, ...]  # s_k, used only when profile = structured
    target_dscr: float  # sculpting and DSCR-based sizing target
    sizing: Literal["gearing", "gearing_and_dscr"]
    sculpt_negative_principal: Literal["floor", "capitalise"] = "floor"


@dataclass(frozen=True)
class ReserveInputs:
    dsra_months: float = 0.0  # months of next year's debt service held in the DSRA
    dsra_initial_funding: Literal["cash_flow", "construction"] = "cash_flow"
    mmra_enabled: bool = False
    mmra_position: Literal["after_debt_service", "in_cfads"] = "after_debt_service"
    lockup_dscr: float | None = None  # None = no dividend lock-up


@dataclass(frozen=True)
class TollInputs:
    aadt: float  # AADT0, PCU/day at COD (mature level, before ramp-up)
    growth: float  # g_tr
    rate: float  # rate0, ₹ per PCU-trip at COD
    rate_escalation: float  # e_toll
    ramp_up: tuple[float, ...]  # R_k for op years 1, 2, ...; 100% afterwards
    leakage: float  # exempt / non-paying share of vehicles
    capacity: float | None  # PCU/day cap on vehicles using the road; None = no cap
    days_per_year: int


@dataclass(frozen=True)
class MetroInputs:
    ridership: float  # passengers/day at COD (mature level, before ramp-up)
    growth: float
    fare: float  # ₹ per trip at COD
    fare_revision_pct: float
    fare_revision_every: int  # years between fare revisions
    ramp_up: tuple[float, ...]
    non_fare_pct: float  # non-fare revenue as a share of fare revenue
    capacity: float | None  # passengers/day line capacity; None = no cap
    days_per_year: int


@dataclass(frozen=True)
class HamInputs:
    bid_project_cost: float  # BPC, ₹ Cr at bid-date prices
    construction_support_pct: float  # share of BPC paid during construction (40%)
    support_milestones: tuple[float, ...] | None  # share of support by construction year; None = capex phasing
    annuity_instalments: int  # number of instalments after COD (30)
    instalments_per_year: int  # 2 = semi-annual
    annuity_interest_rate: float  # i_ham, p.a., on the reducing annuity balance
    om_payment: float  # O&M payment in op-year-1 prices, ₹ Cr p.a.
    pim_inflation: float  # Price Index Multiple growth p.a.


@dataclass(frozen=True)
class RevenueInputs:
    toll: TollInputs | None = None
    metro: MetroInputs | None = None
    ham: HamInputs | None = None


@dataclass(frozen=True)
class OpexInputs:
    om_base: float  # OM0, op-year-1 prices
    om_escalation: float  # e_om, also escalates major maintenance
    mmr_base: float  # MMR0, op-year-1 prices
    mmr_years: tuple[int, ...]  # operating years with major maintenance
    concession_fee_pct: float  # revenue share paid to the Authority
    concession_premium: float  # fixed premium in op-year-1 prices
    premium_escalation: float


@dataclass(frozen=True)
class TaxInputs:
    rate: float
    depreciation_years: int | None  # None = the operating period
    depreciation_net_of_grant: bool  # True: grant-funded cost is not depreciated
    loss_carry_forward_years: int | None  # None = unlimited (README base)


@dataclass(frozen=True)
class ValuationInputs:
    discount_rate: float  # project discount rate for NPV
    equity_hurdle: float
    terminal_value: float = 0.0  # cash at handback, final year (usually 0)


@dataclass(frozen=True)
class CovenantInputs:
    min_dscr: float = 1.20  # lender covenant: amber below this, red below 1.00x
    min_llcr: float = 1.30


@dataclass(frozen=True)
class StressInputs:
    demand_shortfall: float = 0.0  # traffic (toll) / ridership (metro); HAM revenue does not use it
    cost_overrun: float = 0.0  # on hard cost
    overrun_funding: Literal["pro_rata", "equity"] = "pro_rata"
    delay_years: int = 0  # construction delay, whole years
    delay_phasing: tuple[float, ...] | None = None  # phasing over Tc + delay; None = stretch the S-curve
    rate_shock: float = 0.0  # added to the interest rate (0.01 = +100 bp)


@dataclass(frozen=True)
class SolverInputs:
    tolerance: float = 1e-10  # convergence tolerance for the iterative solves (₹ Cr or ratio)
    max_iterations: int = 200


@dataclass(frozen=True)
class ModelInputs:
    project: ProjectInputs
    timeline: TimelineInputs
    capex: CapexInputs
    funding: FundingInputs
    debt: DebtInputs
    revenue: RevenueInputs
    opex: OpexInputs
    tax: TaxInputs
    valuation: ValuationInputs
    covenants: CovenantInputs = field(default_factory=CovenantInputs)
    reserves: ReserveInputs = field(default_factory=ReserveInputs)
    stress: StressInputs = field(default_factory=StressInputs)
    solver: SolverInputs = field(default_factory=SolverInputs)

    @property
    def project_type(self) -> str:
        return self.project.type

    @property
    def interest_rate(self) -> float:
        """Effective all-in rate: base rate plus any scenario rate shock."""
        return self.debt.interest_rate + self.stress.rate_shock

    @property
    def revenue_block(self) -> TollInputs | MetroInputs | HamInputs:
        block = getattr(self.revenue, self.project.type)
        if block is None:  # guarded by validation; kept for type checkers
            raise InputValidationError([f"revenue.{self.project.type}: block is missing"])
        return block


# ---------------------------------------------------------------------------------------------
# Generic mapping -> dataclass conversion
# ---------------------------------------------------------------------------------------------


def _join(path: str, key: Any) -> str:
    return f"{path}.{key}" if path else str(key)


def _coerce(tp: Any, value: Any, path: str, errors: list[str]) -> Any:
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        args = get_args(tp)
        if value is None:
            if type(None) in args:
                return None
            errors.append(f"{path}: a value is required (got null)")
            return None
        non_none = [a for a in args if a is not type(None)]
        return _coerce(non_none[0], value, path, errors)
    if dataclasses.is_dataclass(tp):
        return _from_mapping(tp, value, path, errors)
    if origin is Literal:
        allowed = get_args(tp)
        if value not in allowed:
            errors.append(f"{path}: must be one of {', '.join(repr(a) for a in allowed)}; got {value!r}")
            return None
        return value
    if origin is tuple:
        elem_type = get_args(tp)[0]
        if not isinstance(value, (list, tuple)):
            errors.append(f"{path}: expected a list; got {type(value).__name__} {value!r}")
            return None
        return tuple(_coerce(elem_type, v, f"{path}[{i}]", errors) for i, v in enumerate(value))
    if tp is bool:
        if not isinstance(value, bool):
            errors.append(f"{path}: expected true or false; got {value!r}")
            return None
        return value
    if tp is int:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path}: expected a whole number; got {value!r}")
            return None
        if isinstance(value, float) and not value.is_integer():
            errors.append(f"{path}: must be a whole number (the model uses annual periods); got {value}")
            return None
        return int(value)
    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{path}: expected a number; got {value!r}")
            return None
        number = float(value)
        if not math.isfinite(number):
            errors.append(f"{path}: must be a finite number; got {value!r}")
            return None
        return number
    if tp is str:
        if not isinstance(value, str):
            errors.append(f"{path}: expected text; got {value!r}")
            return None
        return value
    raise TypeError(f"Unsupported input type {tp!r} at {path}")  # programming error, not user error


@functools.cache
def _type_hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def _from_mapping(cls: type, data: Any, path: str, errors: list[str]) -> Any:
    if not isinstance(data, dict):
        errors.append(f"{path or 'inputs'}: expected a mapping of keys to values; got {type(data).__name__}")
        return None
    hints = _type_hints(cls)
    names = [f.name for f in dataclasses.fields(cls)]
    n_errors_before = len(errors)
    for key in data:
        if key not in names:
            close = difflib.get_close_matches(str(key), names, n=1, cutoff=0.6)
            hint = f" (did you mean '{close[0]}'?)" if close else f" (allowed: {', '.join(names)})"
            errors.append(f"{_join(path, key)}: unknown input key{hint}")
    values: dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        p = _join(path, f.name)
        if f.name in data:
            values[f.name] = _coerce(hints[f.name], data[f.name], p, errors)
        elif f.default is MISSING and f.default_factory is MISSING:
            errors.append(f"{p}: required input is missing")
    if len(errors) > n_errors_before:
        return None
    return cls(**values)


# ---------------------------------------------------------------------------------------------
# Validation rules (cross-field and range checks)
# ---------------------------------------------------------------------------------------------


def _range(errors: list[str], path: str, value: float | None, lo: float, hi: float,
           lo_open: bool = False, hi_open: bool = False) -> None:
    if value is None:
        return
    below = value <= lo if lo_open else value < lo
    above = value >= hi if hi_open else value > hi
    if below or above:
        lb = "(" if lo_open else "["
        rb = ")" if hi_open else "]"
        errors.append(f"{path}: {value!r} is outside the allowed range {lb}{lo}, {hi}{rb}")


def _shares(errors: list[str], path: str, values: tuple[float, ...], expected_len: int | None) -> None:
    if expected_len is not None and len(values) != expected_len:
        errors.append(f"{path}: needs exactly {expected_len} values (one per year); got {len(values)}")
    if any(v < 0 for v in values):
        errors.append(f"{path}: shares cannot be negative")
    total = sum(values)
    if abs(total - 1.0) > SUM_TOLERANCE:
        errors.append(f"{path}: shares must sum to 100%; they sum to {total * 100:.10g}%")


def _ramp(errors: list[str], path: str, ramp: tuple[float, ...], operating_years: int) -> None:
    for i, v in enumerate(ramp):
        if not 0.0 < v <= 1.0:
            errors.append(f"{path}[{i}]: ramp-up factors must be in (0, 1]; got {v}")
    if len(ramp) > operating_years:
        errors.append(f"{path}: {len(ramp)} ramp-up factors but only {operating_years} operating years")


def validate_inputs(inp: ModelInputs) -> list[str]:
    """Return every validation problem found (empty list = valid)."""
    e: list[str] = []
    tl, cx, fu, dt, rs, op, tx, va, cv, st, so = (
        inp.timeline, inp.capex, inp.funding, inp.debt, inp.reserves, inp.opex, inp.tax,
        inp.valuation, inp.covenants, inp.stress, inp.solver,
    )

    # --- timeline -------------------------------------------------------------------------
    if tl.construction_years < 1:
        e.append("timeline.construction_years: must be at least 1")
    if tl.concession_years <= tl.construction_years:
        e.append("timeline.concession_years: must be longer than the construction period")
    to_base = tl.concession_years - tl.construction_years
    if st.delay_years < 0:
        e.append("stress.delay_years: cannot be negative")
    to_eff = to_base - st.delay_years if tl.concession_end_fixed else to_base
    if to_eff < 1:
        e.append(
            f"stress.delay_years: a {st.delay_years}-year delay with a fixed concession end leaves "
            f"{to_eff} operating years; the model needs at least one"
        )

    # --- capex ----------------------------------------------------------------------------
    _range(e, "capex.base_cost", cx.base_cost, 0.0, math.inf, lo_open=True)
    _shares(e, "capex.phasing", cx.phasing, tl.construction_years)
    _range(e, "capex.escalation", cx.escalation, -0.5, 1.0)
    _range(e, "capex.contingency", cx.contingency, 0.0, 1.0)
    _range(e, "capex.preop", cx.preop, 0.0, 1.0)

    # --- funding --------------------------------------------------------------------------
    _range(e, "funding.gearing", fu.gearing, 0.0, 1.0, hi_open=True)
    _range(e, "funding.grant_pct", fu.grant_pct, 0.0, 1.0, hi_open=True)
    _range(e, "funding.drawdown_timing", fu.drawdown_timing, 0.0, 1.0)
    _range(e, "funding.upfront_fee", fu.upfront_fee, 0.0, 0.10)

    # --- debt -----------------------------------------------------------------------------
    _range(e, "debt.interest_rate", dt.interest_rate, 0.0, 0.5)
    _range(e, "stress.rate_shock (effective interest rate)", inp.interest_rate, 0.0, 0.5)
    if dt.tenor_years < 1:
        e.append("debt.tenor_years: must be at least 1")
    if dt.moratorium_years < 0:
        e.append("debt.moratorium_years: cannot be negative")
    if dt.moratorium_years + dt.tenor_years > to_base:
        e.append(
            f"debt: moratorium ({dt.moratorium_years}) + tenor ({dt.tenor_years}) = "
            f"{dt.moratorium_years + dt.tenor_years} years exceeds the {to_base}-year operating period; "
            "the loan would mature after the concession ends (README §12.1 check 10)"
        )
    if dt.profile == "structured":
        _shares(e, "debt.structured_pct", dt.structured_pct, dt.tenor_years)
    _range(e, "debt.target_dscr", dt.target_dscr, 1.0, 10.0)

    # --- reserves -------------------------------------------------------------------------
    _range(e, "reserves.dsra_months", rs.dsra_months, 0.0, 24.0)
    if rs.lockup_dscr is not None:
        _range(e, "reserves.lockup_dscr", rs.lockup_dscr, 1.0, 10.0)

    # --- revenue --------------------------------------------------------------------------
    ptype = inp.project.type
    block = getattr(inp.revenue, ptype)
    if block is None:
        e.append(f"revenue.{ptype}: project type is '{ptype}' but the revenue.{ptype} block is missing")
    elif ptype == "toll":
        _range(e, "revenue.toll.aadt", block.aadt, 0.0, math.inf, lo_open=True)
        _range(e, "revenue.toll.growth", block.growth, -0.5, 0.5)
        _range(e, "revenue.toll.rate", block.rate, 0.0, math.inf, lo_open=True)
        _range(e, "revenue.toll.rate_escalation", block.rate_escalation, -0.5, 0.5)
        _ramp(e, "revenue.toll.ramp_up", block.ramp_up, to_base)
        _range(e, "revenue.toll.leakage", block.leakage, 0.0, 1.0, hi_open=True)
        if block.capacity is not None:
            _range(e, "revenue.toll.capacity", block.capacity, 0.0, math.inf, lo_open=True)
        _range(e, "revenue.toll.days_per_year", block.days_per_year, 1, 366)
    elif ptype == "metro":
        _range(e, "revenue.metro.ridership", block.ridership, 0.0, math.inf, lo_open=True)
        _range(e, "revenue.metro.growth", block.growth, -0.5, 0.5)
        _range(e, "revenue.metro.fare", block.fare, 0.0, math.inf, lo_open=True)
        _range(e, "revenue.metro.fare_revision_pct", block.fare_revision_pct, -0.5, 1.0)
        if block.fare_revision_every < 1:
            e.append("revenue.metro.fare_revision_every: must be at least 1 year")
        _ramp(e, "revenue.metro.ramp_up", block.ramp_up, to_base)
        _range(e, "revenue.metro.non_fare_pct", block.non_fare_pct, 0.0, 1.0)
        if block.capacity is not None:
            _range(e, "revenue.metro.capacity", block.capacity, 0.0, math.inf, lo_open=True)
        _range(e, "revenue.metro.days_per_year", block.days_per_year, 1, 366)
    elif ptype == "ham":
        _range(e, "revenue.ham.bid_project_cost", block.bid_project_cost, 0.0, math.inf, lo_open=True)
        _range(e, "revenue.ham.construction_support_pct", block.construction_support_pct, 0.0, 1.0, hi_open=True)
        if block.support_milestones is not None:
            _shares(e, "revenue.ham.support_milestones", block.support_milestones, tl.construction_years)
        if block.annuity_instalments < 1:
            e.append("revenue.ham.annuity_instalments: must be at least 1")
        if block.instalments_per_year not in (1, 2, 4, 12):
            e.append("revenue.ham.instalments_per_year: must be 1, 2, 4 or 12")
        elif block.annuity_instalments >= 1:
            annuity_years = math.ceil(block.annuity_instalments / block.instalments_per_year)
            if annuity_years > to_base:
                e.append(
                    f"revenue.ham: {block.annuity_instalments} instalments need {annuity_years} operating years "
                    f"but the operating period is {to_base}"
                )
        _range(e, "revenue.ham.annuity_interest_rate", block.annuity_interest_rate, 0.0, 0.5)
        _range(e, "revenue.ham.om_payment", block.om_payment, 0.0, math.inf)
        _range(e, "revenue.ham.pim_inflation", block.pim_inflation, -0.5, 0.5)
        if fu.grant_pct > 0:
            e.append("funding.grant_pct: HAM construction support is the grant; set grant_pct to 0 for HAM")

    # --- operating costs ------------------------------------------------------------------
    _range(e, "opex.om_base", op.om_base, 0.0, math.inf)
    _range(e, "opex.om_escalation", op.om_escalation, -0.5, 0.5)
    _range(e, "opex.mmr_base", op.mmr_base, 0.0, math.inf)
    if len(set(op.mmr_years)) != len(op.mmr_years):
        e.append("opex.mmr_years: years must not repeat")
    for y in op.mmr_years:
        if not 1 <= y <= to_base:
            e.append(f"opex.mmr_years: op year {y} is outside the operating period 1..{to_base}")
    _range(e, "opex.concession_fee_pct", op.concession_fee_pct, 0.0, 1.0, hi_open=True)
    _range(e, "opex.concession_premium", op.concession_premium, 0.0, math.inf)
    _range(e, "opex.premium_escalation", op.premium_escalation, -0.5, 0.5)

    # --- tax ------------------------------------------------------------------------------
    _range(e, "tax.rate", tx.rate, 0.0, 1.0, hi_open=True)
    if tx.depreciation_years is not None and tx.depreciation_years < 1:
        e.append("tax.depreciation_years: must be at least 1 (or null for the operating period)")
    if tx.loss_carry_forward_years is not None and tx.loss_carry_forward_years < 1:
        e.append("tax.loss_carry_forward_years: must be at least 1 (or null for unlimited)")

    # --- valuation and covenants ----------------------------------------------------------
    _range(e, "valuation.discount_rate", va.discount_rate, -0.5, 1.0)
    _range(e, "valuation.equity_hurdle", va.equity_hurdle, -0.5, 1.0)
    _range(e, "covenants.min_dscr", cv.min_dscr, 1.0, 10.0)
    _range(e, "covenants.min_llcr", cv.min_llcr, 1.0, 10.0)

    # --- scenario levers ------------------------------------------------------------------
    _range(e, "stress.demand_shortfall", st.demand_shortfall, -1.0, 1.0, lo_open=True, hi_open=True)
    _range(e, "stress.cost_overrun", st.cost_overrun, -1.0, 3.0, lo_open=True)
    if st.delay_phasing is not None:
        _shares(e, "stress.delay_phasing", st.delay_phasing, tl.construction_years + st.delay_years)

    # --- solver ---------------------------------------------------------------------------
    _range(e, "solver.tolerance", so.tolerance, 0.0, 1e-3, lo_open=True)
    if so.max_iterations < 10:
        e.append("solver.max_iterations: must be at least 10")
    return e


# ---------------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------------


def deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict: ``base`` with ``override`` applied recursively. Neither input is modified.

    Nested mappings merge key by key; any other value (numbers, text, lists) replaces the base value.
    """
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_yaml(path: str | Path) -> dict:
    """Read a YAML file into a plain dict."""
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise InputValidationError([f"{path}: the file must contain a mapping of input blocks"])
    return data


def build_inputs(raw: dict) -> ModelInputs:
    """Convert a raw input dict (as read from YAML) into validated :class:`ModelInputs`."""
    errors: list[str] = []
    inputs = _from_mapping(ModelInputs, copy.deepcopy(raw), "", errors)
    if errors:
        raise InputValidationError(errors)
    errors = validate_inputs(inputs)
    if errors:
        raise InputValidationError(errors)
    return inputs


def load_inputs(path: str | Path, overrides: dict | None = None) -> ModelInputs:
    """Load and validate a base YAML file, optionally with scenario overrides deep-merged on top."""
    raw = load_yaml(path)
    if overrides:
        raw = deep_merge(raw, overrides)
    return build_inputs(raw)


def inputs_to_dict(inputs: ModelInputs) -> dict:
    """Plain-dict (YAML-ready) form of the inputs, with tuples turned back into lists."""

    def plain(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [plain(v) for v in value]
        return value

    return plain(dataclasses.asdict(inputs))


def config_dir() -> Path:
    """The repository's ``config/`` folder (works from any working directory)."""
    return Path(__file__).resolve().parents[2] / "config"


def base_config_path(project_type: str) -> Path:
    if project_type not in PROJECT_TYPES:
        raise InputValidationError([f"project type must be one of {PROJECT_TYPES}; got {project_type!r}"])
    return config_dir() / f"base_{project_type}.yaml"
