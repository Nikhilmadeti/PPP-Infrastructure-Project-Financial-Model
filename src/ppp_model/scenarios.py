"""Scenarios and sensitivity analysis (README §10).

A scenario is the base inputs plus a few overrides, deep-merged onto a *fresh copy* of the base
(:func:`ppp_model.inputs.deep_merge` never modifies its arguments), so running scenarios can never
corrupt the base case.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .debt import default_structured_pct
from .errors import InputValidationError, ModelError
from .inputs import REPAYMENT_PROFILES, build_inputs, config_dir, deep_merge, load_yaml
from .metrics import meets
from .model import ModelResults, run_model


# ---------------------------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    description: str = ""
    overrides: dict = field(default_factory=dict)
    by_type: dict = field(default_factory=dict)

    def overrides_for(self, project_type: str) -> dict:
        return deep_merge(self.overrides, self.by_type.get(project_type, {}))

    def applies_to(self, project_type: str) -> bool:
        return bool(self.overrides_for(project_type)) or self.key == "base"


@dataclass(frozen=True)
class ScenarioConfig:
    scenarios: dict[str, Scenario]
    two_way_shortfalls: tuple[float, ...]
    two_way_overruns: tuple[float, ...]
    tornado_shock: float
    tornado_variables: dict[str, tuple[dict, ...]]
    break_even_max_shortfall: float
    break_even_tolerance: float


_SCENARIO_KEYS = {"label", "description", "overrides", "by_type"}


def load_scenarios(path: str | Path | None = None) -> ScenarioConfig:
    """Read ``config/scenarios.yaml``. Structure errors are reported, not ignored."""
    raw = load_yaml(path or config_dir() / "scenarios.yaml")
    errors: list[str] = []
    unknown_top = set(raw) - {"scenarios", "sensitivity"}
    if unknown_top:
        errors.append(f"scenarios.yaml: unknown top-level key(s) {sorted(unknown_top)}")
    scenarios: dict[str, Scenario] = {}
    for key, spec in (raw.get("scenarios") or {}).items():
        if not isinstance(spec, dict):
            errors.append(f"scenarios.{key}: expected a mapping")
            continue
        extra = set(spec) - _SCENARIO_KEYS
        if extra:
            errors.append(f"scenarios.{key}: unknown key(s) {sorted(extra)} (allowed: {sorted(_SCENARIO_KEYS)})")
        by_type = spec.get("by_type") or {}
        bad_types = set(by_type) - {"toll", "metro", "ham"}
        if bad_types:
            errors.append(f"scenarios.{key}.by_type: unknown project type(s) {sorted(bad_types)}")
        scenarios[key] = Scenario(key, spec.get("label", key), spec.get("description", ""),
                                  spec.get("overrides") or {}, by_type)
    if "base" not in scenarios:
        errors.append("scenarios.yaml: a 'base' scenario with no overrides is required")
    sens = raw.get("sensitivity") or {}
    two_way = sens.get("two_way") or {}
    tornado_cfg = sens.get("tornado") or {}
    break_even = sens.get("break_even") or {}
    if errors:
        raise InputValidationError(errors)
    return ScenarioConfig(
        scenarios=scenarios,
        two_way_shortfalls=tuple(float(x) for x in two_way.get("shortfalls", [0.0, 0.1, 0.2, 0.3])),
        two_way_overruns=tuple(float(x) for x in two_way.get("overruns", [0.0, 0.1, 0.2, 0.3])),
        tornado_shock=float(tornado_cfg.get("shock", 0.10)),
        tornado_variables={k: tuple(v) for k, v in (tornado_cfg.get("variables") or {}).items()},
        break_even_max_shortfall=float(break_even.get("max_shortfall", 0.95)),
        break_even_tolerance=float(break_even.get("tolerance", 1e-7)),
    )


def scenario_raw(base_raw: dict, scenario: Scenario) -> dict:
    """Merged raw inputs for a scenario (a new dict; ``base_raw`` is untouched)."""
    project_type = base_raw.get("project", {}).get("type", "")
    return deep_merge(base_raw, scenario.overrides_for(project_type))


def run_scenario(base_raw: dict, scenario: Scenario) -> ModelResults:
    try:
        inputs = build_inputs(scenario_raw(base_raw, scenario))
    except InputValidationError as exc:
        raise InputValidationError([f"scenario '{scenario.key}': {e}" for e in exc.errors]) from exc
    return run_model(inputs)


# ---------------------------------------------------------------------------------------------
# Summary table (README §10.2)
# ---------------------------------------------------------------------------------------------


def verdict(res: ModelResults) -> str:
    """Rule-based bankability verdict used in the scenario table."""
    mt, cov = res.metrics, res.inputs.covenants
    if not mt.debt_fully_repaid:
        return "Not bankable: debt not repaid within the concession"
    if mt.dscr_below_one_years:
        return f"Not bankable: DSCR < 1.00x in op year(s) {', '.join(map(str, mt.dscr_below_one_years))}"
    lender_ok = (mt.min_dscr is None or meets(mt.min_dscr, cov.min_dscr)) and (
        mt.llcr_cod is None or meets(mt.llcr_cod, cov.min_llcr))
    if not lender_ok:
        return f"Below lender covenant ({cov.min_dscr:.2f}x DSCR / {cov.min_llcr:.2f}x LLCR)"
    if mt.equity_meets_hurdle is False or not mt.equity_irr.ok:
        return "Lender metrics pass; equity below hurdle"
    return "Bankable"


def summary_row(key: str, label: str, res: ModelResults) -> dict:
    mt = res.metrics
    return {
        "Key": key,
        "Scenario": label,
        "TPC": mt.total_project_cost,
        "Debt": mt.debt,
        "Equity": mt.equity,
        "IDC": mt.idc,
        "Min DSCR": mt.min_dscr,
        "Min DSCR op year": mt.min_dscr_op_year,
        "Avg DSCR": mt.avg_dscr,
        "LLCR at COD": mt.llcr_cod,
        "Project IRR": mt.project_irr.value,
        "Project IRR (post-grant)": mt.project_irr_post_grant.value,
        "Equity IRR": mt.equity_irr.value,
        "NPV": mt.project_npv,
        "Debt fully repaid?": "Yes" if mt.debt_fully_repaid else "No",
        "Any DSCR < 1.0?": "Yes" if mt.dscr_below_one_years else "No",
        "Equity IRR >= hurdle?": {True: "Yes", False: "No", None: "n/a"}[mt.equity_meets_hurdle],
        "Sponsor support": mt.sponsor_support,
        "Integrity checks": "Pass" if res.integrity_ok else "FAIL",
        "Verdict": verdict(res),
    }


def run_scenarios(base_raw: dict, config: ScenarioConfig,
                  keys: Iterable[str] | None = None) -> tuple[pd.DataFrame, dict[str, ModelResults]]:
    rows, results = [], {}
    for key in keys or config.scenarios:
        scenario = config.scenarios[key]
        res = run_scenario(base_raw, scenario)
        results[key] = res
        rows.append(summary_row(key, scenario.label, res))
    return pd.DataFrame(rows).set_index("Key"), results


# ---------------------------------------------------------------------------------------------
# Sensitivities
# ---------------------------------------------------------------------------------------------


def _get(d: dict, dotted: str):
    node = d
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            raise InputValidationError([f"sensitivity path '{dotted}' does not exist in the inputs"])
        node = node[part]
    return node


def _set(d: dict, dotted: str, value) -> dict:
    out = copy.deepcopy(d)
    node = out
    parts = dotted.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value
    return out


def _metric(res: ModelResults | None, name: str) -> float | None:
    if res is None:
        return None
    mt = res.metrics
    if name == "min_dscr":
        return mt.min_dscr
    if name == "equity_irr":
        return mt.equity_irr.value
    if name == "project_irr":
        return mt.project_irr.value
    if name == "llcr":
        return mt.llcr_cod
    raise ValueError(f"unknown metric {name}")


def _with_stress(base_raw: dict, **stress) -> dict:
    return deep_merge(base_raw, {"stress": stress})


def two_way_table(base_raw: dict, shortfalls: Iterable[float], overruns: Iterable[float],
                  metric: str = "min_dscr") -> pd.DataFrame:
    """README §10.3 two-way table: traffic shortfall (rows) x cost overrun (columns)."""
    shortfalls, overruns = list(shortfalls), list(overruns)
    data = np.full((len(shortfalls), len(overruns)), np.nan)
    for i, s in enumerate(shortfalls):
        for j, o in enumerate(overruns):
            value = _metric(run_model(_with_stress(base_raw, demand_shortfall=s, cost_overrun=o)), metric)
            data[i, j] = np.nan if value is None else value
    return pd.DataFrame(data, index=pd.Index(shortfalls, name="Traffic shortfall"),
                        columns=pd.Index(overruns, name="Cost overrun"))


def tornado(base_raw: dict, variables: Iterable[dict], shock: float) -> pd.DataFrame:
    """Move each input by -/+shock (relative), one at a time; record Equity IRR and minimum DSCR."""
    base = run_model(base_raw)
    base_irr, base_dscr = _metric(base, "equity_irr"), _metric(base, "min_dscr")
    rows = []
    for var in variables:
        path, label = var["path"], var.get("label", var["path"])
        value = float(_get(base_raw, path))
        row = {"Variable": label, "Path": path, "Base value": value,
               "Low value": value * (1 - shock), "High value": value * (1 + shock), "Note": ""}
        for side, factor in (("Low", 1 - shock), ("High", 1 + shock)):
            try:
                res = run_model(_set(base_raw, path, value * factor))
            except (InputValidationError, ModelError) as exc:
                res = None
                row["Note"] = f"{side} case invalid: {exc}"
            irr_v, dscr_v = _metric(res, "equity_irr"), _metric(res, "min_dscr")
            row[f"Equity IRR ({side.lower()})"] = irr_v
            row[f"Min DSCR ({side.lower()})"] = dscr_v
            row[f"Δ Equity IRR ({side.lower()})"] = None if irr_v is None or base_irr is None else irr_v - base_irr
            row[f"Δ Min DSCR ({side.lower()})"] = None if dscr_v is None or base_dscr is None else dscr_v - base_dscr
        if value == 0:
            row["Note"] = "Base value is zero, so a relative shock has no effect."
        rows.append(row)
    df = pd.DataFrame(rows)
    span = (df["Δ Equity IRR (high)"].astype(float) - df["Δ Equity IRR (low)"].astype(float)).abs()
    df["Equity IRR range"] = span
    df = df.sort_values("Equity IRR range", ascending=False, na_position="last").reset_index(drop=True)
    df.attrs.update({"base_equity_irr": base_irr, "base_min_dscr": base_dscr, "shock": shock})
    return df


@dataclass(frozen=True)
class BreakEvenResult:
    status: str  # found | not_reached | already_breached | not_applicable
    value: float | None
    metric: str
    threshold: float
    message: str
    binding_op_year: int | None = None


def break_even_shortfall(base_raw: dict, *, metric: str = "min_dscr", threshold: float = 1.0,
                         max_shortfall: float = 0.95, tol: float = 1e-7, scan_steps: int = 40) -> BreakEvenResult:
    """Traffic shortfall at which ``metric`` falls to ``threshold`` (README §10.3).

    A coarse scan from 0 to ``max_shortfall`` locates the first crossing, which is then refined by
    bisection, so a non-monotonic metric cannot send the search to a later crossing. A missing value
    (no IRR) counts as below the threshold for Equity IRR and as 'no debt service' (infinite cover)
    for DSCR.
    """
    project_type = base_raw.get("project", {}).get("type")
    if project_type == "ham":
        return BreakEvenResult("not_applicable", None, metric, threshold,
                               "HAM revenue is paid by the Authority and does not depend on traffic, so no "
                               "traffic shortfall can breach the threshold.")

    def gap(s: float) -> tuple[float, ModelResults]:
        res = run_model(_with_stress(base_raw, demand_shortfall=s))
        value = _metric(res, metric)
        if value is None:
            value = np.inf if metric == "min_dscr" else -np.inf
        return value - threshold, res

    g0, _ = gap(0.0)
    if g0 < 0:
        return BreakEvenResult("already_breached", 0.0, metric, threshold,
                               f"Already below {threshold:g} with no traffic shortfall.")
    grid = np.linspace(0.0, max_shortfall, scan_steps + 1)
    lo = 0.0
    for s in grid[1:]:
        g, _ = gap(float(s))
        if g < 0:
            hi = float(s)
            break
        lo = float(s)
    else:
        return BreakEvenResult("not_reached", None, metric, threshold,
                               f"Not reached: {metric} stays at or above {threshold:g} up to a "
                               f"{max_shortfall:.0%} traffic shortfall.")
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        if gap(mid)[0] >= 0:
            lo = mid
        else:
            hi = mid
    _, res = gap(lo)
    year = res.metrics.min_dscr_op_year if metric == "min_dscr" else None
    return BreakEvenResult("found", lo, metric, threshold,
                           f"{metric} reaches {threshold:g} at a traffic shortfall of {lo:.2%}.", year)


def ham_traffic_demonstration(ham_raw: dict, shortfall: float = 0.20) -> pd.DataFrame:
    """Show that a traffic shortfall leaves HAM revenue and metrics unchanged (README §3.3)."""
    base = run_model(ham_raw)
    stressed = run_model(_with_stress(ham_raw, demand_shortfall=shortfall))
    rows = []
    for name, res in ((f"Base", base), (f"Traffic -{shortfall:.0%}", stressed)):
        mt = res.metrics
        rows.append({"Case": name, "Total revenue": float(res.revenue.total.sum()),
                     "Min DSCR": mt.min_dscr, "LLCR at COD": mt.llcr_cod, "Equity IRR": mt.equity_irr.value})
    df = pd.DataFrame(rows).set_index("Case")
    df.attrs["max_revenue_difference"] = float(np.max(np.abs(base.revenue.total - stressed.revenue.total)))
    return df


def profile_comparison(base_raw: dict) -> tuple[pd.DataFrame, dict[str, ModelResults]]:
    """Run the same project with each repayment profile (README §11.4)."""
    tenor = int(base_raw["debt"]["tenor_years"])
    configured = tuple(base_raw["debt"].get("structured_pct") or ())
    rows, results = [], {}
    for profile in REPAYMENT_PROFILES:
        overrides: dict = {"debt": {"profile": profile}}
        note = ""
        if profile == "structured" and (len(configured) != tenor or abs(sum(configured) - 1) > 1e-9):
            overrides["debt"]["structured_pct"] = list(default_structured_pct(tenor))
            note = "default rising profile (configured percentages do not match the tenor)"
        res = run_model(deep_merge(base_raw, overrides))
        results[profile] = res
        mt = res.metrics
        rows.append({"Profile": profile, "Min DSCR": mt.min_dscr, "Min DSCR op year": mt.min_dscr_op_year,
                     "Avg DSCR": mt.avg_dscr, "LLCR at COD": mt.llcr_cod, "Equity IRR": mt.equity_irr.value,
                     "Debt fully repaid?": "Yes" if mt.debt_fully_repaid else "No", "Note": note})
    return pd.DataFrame(rows).set_index("Profile"), results
