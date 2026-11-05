"""Debt schedule (README §9.9): four repayment profiles, moratorium, sculpting, sizing helpers.

Core rows, identical for every profile:

    Open[k] = Close[k-1]  (Open[1] = debt at COD);  Interest[k] = r x Open[k]
    Close[k] = Open[k] - Principal[k];               DS[k] = Interest[k] + Principal[k]

Profiles (j = repayment year number = k - mor):
    equal       P[j] = D / n
    annuity     DS = D x r / (1 - (1+r)^-n);   P[j] = (DS - r x D) x (1+r)^(j-1)
    structured  P[j] = D x s[j],  sum(s) = 100%
    sculpted    DS[k] = CFADS[k] / DSCR  for repayment years, with the multiplier solved so that the
                loan is exactly repaid at maturity (when gearing binds, DSCR = PV(CFADS)/D > target).

Moratorium years (k <= mor) pay interest only. Invariants enforced here: principal never exceeds the
outstanding balance, the balance never goes negative, principal is zero in the moratorium, and
sculpted principal is never negative unless ``sculpt_negative_principal = capitalise`` is chosen
explicitly. If the contractual maturity lies after the concession end, repayments that would fall
outside the concession are not made and the unpaid balance is reported, never hidden.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .errors import ConvergenceError, ModelError
from .timeline import Timeline

REPAID_TOLERANCE = 1e-6
"""₹ Cr below which a balance counts as fully repaid (README §12.1 uses 0.001; this is stricter)."""


@dataclass(frozen=True)
class DebtSchedule:
    profile: str
    amount: float  # debt at COD
    rate: float
    opening: np.ndarray
    interest: np.ndarray
    principal: np.ndarray
    debt_service: np.ndarray
    closing: np.ndarray
    maturity_op_year: int
    final_repayment_op_year: int | None
    outstanding_at_end: float
    fully_repaid: bool
    sculpt_dscr: float | None = None  # DSCR in unconstrained sculpted years (1 / multiplier)
    floored_years: tuple[int, ...] = ()  # sculpted years where principal was floored at zero
    capitalised_interest: float = 0.0  # sum of negative principal under the capitalise rule
    warnings: tuple[str, ...] = ()


def annuity_payment(amount: float, rate: float, n: int) -> float:
    """Level debt service that repays ``amount`` over ``n`` years (Excel ``PMT(r, n, -D)``)."""
    if n < 1:
        raise ModelError("annuity tenor must be at least one year")
    if rate == 0:
        return amount / n
    return amount * rate / (1.0 - (1.0 + rate) ** (-n))


def contractual_principal(profile: str, amount: float, rate: float, tenor: int,
                          structured_pct: tuple[float, ...]) -> np.ndarray:
    """Principal due in repayment years j = 1..n for the non-sculpted profiles."""
    j = np.arange(1, tenor + 1)
    if profile == "equal":
        return np.full(tenor, amount / tenor)
    if profile == "annuity":
        first = annuity_payment(amount, rate, tenor) - rate * amount
        return first * (1.0 + rate) ** (j - 1)
    if profile == "structured":
        if len(structured_pct) != tenor:
            raise ModelError(f"structured repayment needs {tenor} percentages; got {len(structured_pct)}")
        return amount * np.asarray(structured_pct, dtype=float)
    raise ModelError(f"profile '{profile}' has no fixed principal schedule")


def _finish(profile, amount, rate, tl, opening, interest, principal, closing, **extra) -> DebtSchedule:
    warnings = list(extra.pop("warnings", []))
    end = float(closing[-1]) if closing.size else 0.0
    repaid = end <= REPAID_TOLERANCE
    final_k = None
    if amount > REPAID_TOLERANCE and repaid:
        paid_off = np.where((opening > REPAID_TOLERANCE) & (closing <= REPAID_TOLERANCE))[0]
        final_k = int(tl.op_year[paid_off[0]]) if paid_off.size else None
    if not repaid:
        warnings.append(
            f"Debt not fully repaid: {end:,.2f} ₹ Cr is still outstanding at the end of the concession "
            f"(contractual maturity op year {tl.maturity_op_year}, concession has {tl.operating_years} operating years)."
        )
    if np.any(closing < -REPAID_TOLERANCE):  # guarded below; kept as a hard invariant
        raise ModelError("Debt balance went negative: principal exceeded the outstanding balance")
    return DebtSchedule(
        profile=profile,
        amount=amount,
        rate=rate,
        opening=opening,
        interest=interest,
        principal=principal,
        debt_service=interest + principal,
        closing=closing,
        maturity_op_year=tl.maturity_op_year,
        final_repayment_op_year=final_k,
        outstanding_at_end=end,
        fully_repaid=repaid,
        warnings=tuple(warnings),
        **extra,
    )


def schedule_from_principal(profile: str, amount: float, rate: float, tl: Timeline,
                            structured_pct: tuple[float, ...] = ()) -> DebtSchedule:
    """Debt schedule for equal, annuity and structured profiles."""
    n_years = tl.model_years
    opening, interest, principal, closing = (np.zeros(n_years) for _ in range(4))
    due = np.zeros(n_years)
    if amount > 0:
        contract = contractual_principal(profile, amount, rate, tl.tenor_years, structured_pct)
        for j, p in enumerate(contract, start=1):
            k = tl.moratorium_years + j
            if k <= tl.operating_years:
                due[tl.index_of_op_year(k)] = p
    final_index = tl.index_of_op_year(tl.maturity_op_year) if tl.maturity_within_concession else None
    balance = amount
    for i in range(tl.cod_index, n_years):
        opening[i] = balance
        interest[i] = rate * balance
        pay = min(due[i], balance)  # never repay more than is outstanding
        if i == final_index and 0 < balance - pay <= 1e-9 * max(amount, 1.0):
            pay = balance  # clear floating-point residue at contractual maturity
        principal[i] = pay
        balance -= pay
        closing[i] = balance
    return _finish(profile, amount, rate, tl, opening, interest, principal, closing)


def _sculpt_pass(amount, rate, cfads, tl, multiplier, rule, cleanup_tol=0.0):
    n_years = tl.model_years
    opening, interest, principal, closing = (np.zeros(n_years) for _ in range(4))
    floored: list[int] = []
    final_index = np.where(tl.is_repayment > 0)[0][-1]
    balance = amount
    for i in range(tl.cod_index, n_years):
        opening[i] = balance
        interest[i] = rate * balance
        if tl.is_repayment[i] > 0 and balance > 0:
            target_ds = multiplier * max(cfads[i], 0.0)
            pay = target_ds - interest[i]
            if pay < 0 and rule == "floor":
                floored.append(int(tl.op_year[i]))
                pay = 0.0
            pay = min(pay, balance)
            if i == final_index and 0 < balance - pay <= cleanup_tol:
                pay = balance  # clear solver residue at maturity
        else:
            pay = 0.0
        principal[i] = pay
        balance -= pay
        closing[i] = balance
    return opening, interest, principal, closing, floored


def sculpted_schedule(amount: float, rate: float, cfads: np.ndarray, tl: Timeline, rule: str,
                      tol: float, max_iter: int) -> DebtSchedule:
    """Sculpted debt service DS[k] = CFADS[k] x multiplier over the repayment years.

    The multiplier is solved so the loan is exactly repaid at maturity. Without constraints it has
    the closed form D x (1+r)^-mor / PV_r(CFADS over the repayment years). With the zero-principal
    floor it is found by bisection on the closing balance at maturity.
    """
    n_years = tl.model_years
    window = np.where(tl.is_repayment > 0)[0]
    if amount <= REPAID_TOLERANCE:
        zero = np.zeros(n_years)
        return _finish("sculpted", amount, rate, tl, zero, zero.copy(), zero.copy(), zero.copy())
    if window.size == 0:
        raise ModelError("Sculpting needs at least one repayment year inside the concession")

    k_window = tl.op_year[window]
    shape = np.maximum(cfads[window], 0.0)
    pv_shape = float(np.sum(shape * (1.0 + rate) ** (-k_window.astype(float))))
    if pv_shape <= 0:
        raise ModelError("Sculpting is impossible: CFADS is zero or negative in every repayment year")
    multiplier = amount * (1.0 + rate) ** (-tl.moratorium_years) / pv_shape
    cleanup_tol = max(tol, 1e-9 * amount)

    opening, interest, principal, closing, floored = _sculpt_pass(amount, rate, cfads, tl, multiplier, rule)
    end_balance = closing[window[-1]]
    if floored or abs(end_balance) > tol:
        lo, hi = 0.0, multiplier
        while _sculpt_pass(amount, rate, cfads, tl, hi, rule)[3][window[-1]] > tol:
            hi *= 2.0
            if hi > 1e6:
                raise ConvergenceError("Sculpting multiplier diverged: CFADS cannot repay the debt")
        for _ in range(max_iter * 2):
            mid = 0.5 * (lo + hi)
            if _sculpt_pass(amount, rate, cfads, tl, mid, rule)[3][window[-1]] > tol:
                lo = mid
            else:
                hi = mid
            if hi - lo <= 1e-15 * hi:
                break
        else:
            raise ConvergenceError("Sculpting multiplier bisection did not converge")
        multiplier = hi
    opening, interest, principal, closing, floored = _sculpt_pass(
        amount, rate, cfads, tl, multiplier, rule, cleanup_tol
    )
    warnings = []
    if floored:
        warnings.append(
            "Sculpted debt service was below interest in op year(s) "
            f"{', '.join(map(str, sorted(set(floored))))}: principal floored at zero (interest-only), so DSCR "
            "in those years is below the sculpted level (README §9.9 sculpting pitfall)."
        )
    capitalised = float(np.clip(-principal, 0.0, None).sum())
    if capitalised > 0:
        warnings.append(
            f"Capitalise rule: {capitalised:,.2f} ₹ Cr of interest was added to the loan (negative principal)."
        )
    return _finish(
        "sculpted", amount, rate, tl, opening, interest, principal, closing,
        sculpt_dscr=1.0 / multiplier, floored_years=tuple(sorted(set(floored))),
        capitalised_interest=capitalised, warnings=warnings,
    )


def sculpted_debt_capacity(cfads: np.ndarray, rate: float, target_dscr: float, tl: Timeline) -> float:
    """README §9.9 DSCR limit: D_dscr = (1+r)^mor x sum_k [CFADS[k] / target] / (1+r)^k over repayment years."""
    window = np.where(tl.is_repayment > 0)[0]
    k = tl.op_year[window].astype(float)
    pv = float(np.sum(np.maximum(cfads[window], 0.0) / target_dscr * (1.0 + rate) ** (-k)))
    return pv * (1.0 + rate) ** tl.moratorium_years


def build_debt_schedule(profile: str, amount: float, rate: float, tl: Timeline, *,
                        structured_pct: tuple[float, ...] = (), cfads: np.ndarray | None = None,
                        negative_rule: str = "floor", tol: float = 1e-10, max_iter: int = 200) -> DebtSchedule:
    if profile == "sculpted":
        if cfads is None:
            raise ModelError("Sculpted profile needs CFADS")
        return sculpted_schedule(amount, rate, cfads, tl, negative_rule, tol, max_iter)
    return schedule_from_principal(profile, amount, rate, tl, structured_pct)


def default_structured_pct(tenor: int) -> tuple[float, ...]:
    """A linearly rising ('ballooning') profile summing to 100%, for when the tenor changes.

    Used only when a user explicitly asks for it (dashboard button, profile comparison); never as a
    silent replacement for an invalid configured profile.
    """
    weights = np.arange(1, tenor + 1, dtype=float) + tenor / 3.0
    return tuple(float(w) for w in weights / weights.sum())
