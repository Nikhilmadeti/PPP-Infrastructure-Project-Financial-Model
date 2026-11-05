"""Timeline: annual model periods and 0/1 flags (README §9.1).

Model year ``t = 1..N``; operating year ``k = t - Tc`` (``k <= 0`` during construction).

Construction delay (README §9.1): ``Tc`` grows by the delay. When ``concession_end_fixed`` is true
(the README rule for Indian concessions, which run from the appointed date) ``N`` stays fixed and
operations shrink to ``To - delay``. The concession is never silently extended; if the delay pushes
the loan's maturity past the concession end, :attr:`Timeline.maturity_within_concession` is false
and the checks report it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import InputValidationError
from .inputs import ModelInputs


@dataclass(frozen=True)
class Timeline:
    scheduled_construction_years: int  # Tc as planned
    delay_years: int
    construction_years: int  # Tc including the delay
    scheduled_operating_years: int  # To as planned
    operating_years: int  # To after the delay
    model_years: int  # N
    moratorium_years: int
    tenor_years: int
    year: np.ndarray  # t = 1..N
    op_year: np.ndarray  # k = t - Tc
    is_construction: np.ndarray  # 0/1
    is_operation: np.ndarray  # 0/1
    is_moratorium: np.ndarray  # 0/1: interest-only operating years
    is_repayment: np.ndarray  # 0/1: contractual repayment years inside the concession
    index_exponent: np.ndarray  # escalation exponent in operating years (0 in construction)
    labels: tuple[str, ...]  # fiscal-year labels, e.g. FY2026-27
    notes: tuple[str, ...]

    @property
    def cod_index(self) -> int:
        """0-based array index of operating year 1."""
        return self.construction_years

    @property
    def maturity_op_year(self) -> int:
        """Contractual final repayment year (operating-year number): mor + n."""
        return self.moratorium_years + self.tenor_years

    @property
    def maturity_within_concession(self) -> bool:
        return self.maturity_op_year <= self.operating_years

    @property
    def last_repayment_op_year(self) -> int:
        """Last repayment year that exists inside the concession."""
        return min(self.maturity_op_year, self.operating_years)

    @property
    def contractual_tail_years(self) -> int:
        """Operating years after contractual maturity (negative if the loan outlives the concession)."""
        return self.operating_years - self.maturity_op_year

    def index_of_op_year(self, k: int) -> int:
        """0-based array index of operating year ``k``."""
        if not 1 <= k <= self.operating_years:
            raise IndexError(f"operating year {k} is outside 1..{self.operating_years}")
        return self.construction_years + k - 1


def fiscal_label(first_fiscal_year: int, t: int) -> str:
    start = first_fiscal_year + t - 1
    return f"FY{start}-{(start + 1) % 100:02d}"


def build_timeline(inp: ModelInputs) -> Timeline:
    tc0 = inp.timeline.construction_years
    delay = inp.stress.delay_years
    to0 = inp.timeline.concession_years - tc0
    tc = tc0 + delay
    if inp.timeline.concession_end_fixed:
        n_years = inp.timeline.concession_years
        to = n_years - tc
    else:
        to = to0
        n_years = tc + to
    if to < 1:
        raise InputValidationError(
            [f"stress.delay_years: the delay leaves {to} operating years before the fixed concession end"]
        )

    mor, ten = inp.debt.moratorium_years, inp.debt.tenor_years
    t = np.arange(1, n_years + 1)
    k = t - tc
    is_c = (t <= tc).astype(float)
    is_o = (t > tc).astype(float)
    is_mor = ((k >= 1) & (k <= mor)).astype(float)
    is_rep = ((k > mor) & (k <= min(mor + ten, to))).astype(float)

    # Escalation exponent in operating years. README formulas use k-1 ('cod'); 'calendar' indexes to
    # the scheduled COD so that a delay does not freeze traffic growth and price indexation.
    shift = delay if inp.timeline.indexation_basis == "calendar" else 0
    exponent = np.where(k >= 1, k - 1 + shift, 0).astype(float)

    notes: list[str] = []
    if delay:
        if inp.timeline.concession_end_fixed:
            notes.append(
                f"Construction delay of {delay} year(s): COD moves from end of year {tc0} to end of year {tc}; "
                f"the concession end is fixed, so operations shrink from {to0} to {to} years."
            )
        else:
            notes.append(
                f"Construction delay of {delay} year(s): COD moves from end of year {tc0} to end of year {tc}; "
                f"the operations period stays {to} years, so the concession ends {delay} year(s) later."
            )
    if mor + ten > to:
        notes.append(
            f"Loan maturity (op year {mor + ten}) is after the concession end (op year {to}): "
            f"{mor + ten - to} contractual repayment year(s) fall outside the concession."
        )

    return Timeline(
        scheduled_construction_years=tc0,
        delay_years=delay,
        construction_years=tc,
        scheduled_operating_years=to0,
        operating_years=to,
        model_years=n_years,
        moratorium_years=mor,
        tenor_years=ten,
        year=t,
        op_year=k,
        is_construction=is_c,
        is_operation=is_o,
        is_moratorium=is_mor,
        is_repayment=is_rep,
        index_exponent=exponent,
        labels=tuple(fiscal_label(inp.project.first_fiscal_year, int(x)) for x in t),
        notes=tuple(notes),
    )
