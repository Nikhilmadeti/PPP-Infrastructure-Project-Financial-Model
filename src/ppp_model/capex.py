"""Capital expenditure: phasing, escalation, contingency, pre-operative costs, overrun (README §9.2).

    Hard[t]  = C0 x p[t] x (1 + e_c)^(t-1) x (1 + overrun)
    Cont[t]  = cont  x Hard[t]
    PreOp[t] = preop x Hard[t]
    Capex[t] = Hard[t] + Cont[t] + PreOp[t]          (before IDC and fees)

Construction delay: the phasing is spread over ``Tc + delay`` years. Unless the scenario gives an
explicit ``stress.delay_phasing``, the cumulative S-curve is stretched by linear interpolation
(30/40/30 over 3 years becomes 22.5/27.5/27.5/22.5 over 4). Escalation follows the model year, so a
delay also raises the cost when ``e_c > 0``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .inputs import ModelInputs
from .timeline import Timeline


@dataclass(frozen=True)
class CapexSchedule:
    phasing: np.ndarray  # effective phasing by model year (0 in operations)
    escalation_factor: np.ndarray
    hard_cost_before_overrun: np.ndarray
    hard_cost: np.ndarray  # including overrun
    contingency: np.ndarray
    preop: np.ndarray
    capex: np.ndarray  # hard + contingency + pre-op, including overrun
    capex_before_overrun: np.ndarray
    overrun: np.ndarray  # capex - capex_before_overrun
    cumulative_capex: np.ndarray
    phasing_source: str  # 'base', 'explicit delay phasing' or 'stretched S-curve'

    @property
    def total(self) -> float:
        return float(self.capex.sum())

    @property
    def total_overrun(self) -> float:
        return float(self.overrun.sum())


def stretch_phasing(phasing: Sequence[float], years: int) -> np.ndarray:
    """Re-spread a phasing profile over ``years`` periods by stretching its cumulative S-curve."""
    p = np.asarray(phasing, dtype=float)
    if years == p.size:
        return p.copy()
    x_old = np.linspace(0.0, 1.0, p.size + 1)
    cum_old = np.concatenate([[0.0], np.cumsum(p)])
    cum_new = np.interp(np.linspace(0.0, 1.0, years + 1), x_old, cum_old)
    return np.diff(cum_new)


def effective_phasing(inp: ModelInputs, tl: Timeline) -> tuple[np.ndarray, str]:
    """Phasing over the (possibly delayed) construction period."""
    if tl.delay_years == 0:
        return np.asarray(inp.capex.phasing, dtype=float), "base"
    if inp.stress.delay_phasing is not None:
        return np.asarray(inp.stress.delay_phasing, dtype=float), "explicit delay phasing"
    return stretch_phasing(inp.capex.phasing, tl.construction_years), "stretched S-curve"


def build_capex(inp: ModelInputs, tl: Timeline) -> CapexSchedule:
    cx = inp.capex
    phasing_c, source = effective_phasing(inp, tl)
    phasing = np.zeros(tl.model_years)
    phasing[: tl.construction_years] = phasing_c

    esc = (1.0 + cx.escalation) ** (tl.year - 1)
    hard_before = cx.base_cost * phasing * esc
    hard = hard_before * (1.0 + inp.stress.cost_overrun)
    contingency = cx.contingency * hard
    preop = cx.preop * hard
    capex = hard + contingency + preop
    capex_before = hard_before * (1.0 + cx.contingency + cx.preop)

    return CapexSchedule(
        phasing=phasing,
        escalation_factor=esc * tl.is_construction,
        hard_cost_before_overrun=hard_before,
        hard_cost=hard,
        contingency=contingency,
        preop=preop,
        capex=capex,
        capex_before_overrun=capex_before,
        overrun=capex - capex_before,
        cumulative_capex=np.cumsum(capex),
        phasing_source=source,
    )
