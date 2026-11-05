"""Depreciation and corporate tax with loss carry-forward (README §9.7).

    Dep[k]      = depreciable cost / L         straight-line from COD (L = operating years by default)
    PBT[k]      = EBITDA[k] - Dep[k] - Interest[k]
    Taxable[k]  = PBT[k] - LossBF[k]
    Tax[k]      = tax x max(0, Taxable[k])
    LossBF[k+1] = max(0, -Taxable[k])

Tax needs interest, so it is computed after the debt schedule. Depreciable cost is the capitalised
cost: capex + fees + IDC, less grant-funded cost when ``depreciation_net_of_grant`` is true. The
DSRA initial balance is cash, not an asset, and is not depreciated. If L exceeds the operating
period, the undepreciated balance is written off in the final year (handback).

Loss carry-forward: unlimited by default (the README base case). With
``loss_carry_forward_years = L``, each year's loss is tracked separately (a vintage), used oldest
first, and lapses if unused after L years. This is a modelling convention, not a full statement of
Indian tax law: the Income-tax Act limits business losses to 8 years but lets unabsorbed
depreciation run indefinitely, and the s.115BAA regime has its own conditions. The model does not
split the two.

Unlevered tax (Project IRR only): the same rules with interest = 0 and depreciation on capex
excluding IDC and fees, so the project return gets no debt tax shield.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .timeline import Timeline


@dataclass(frozen=True)
class TaxResult:
    depreciation: np.ndarray
    interest: np.ndarray
    pbt: np.ndarray
    loss_bf: np.ndarray  # losses available at the start of the year
    loss_used: np.ndarray
    loss_expired: np.ndarray
    taxable_income: np.ndarray  # max(0, PBT - losses used)
    tax: np.ndarray
    loss_cf: np.ndarray  # losses carried forward at the end of the year


@dataclass(frozen=True)
class TaxSchedule:
    levered: TaxResult
    unlevered_pre_grant: TaxResult  # Project IRR before grant
    unlevered: TaxResult  # Project IRR after grant (depreciation net of grant if configured)
    depreciable_cost: float
    unlevered_depreciable_cost: float


def straight_line_depreciation(cost: float, tl: Timeline, years: int | None) -> np.ndarray:
    life = years or tl.operating_years
    dep = np.zeros(tl.model_years)
    for k in range(1, tl.operating_years + 1):
        if k <= life:
            dep[tl.index_of_op_year(k)] = cost / life
    if life > tl.operating_years:  # undepreciated balance written off at handback
        dep[tl.index_of_op_year(tl.operating_years)] += cost * (life - tl.operating_years) / life
    return dep


def tax_with_losses(pbt: np.ndarray, rate: float, carry_forward_years: int | None) -> tuple[np.ndarray, ...]:
    n = pbt.size
    loss_bf, used, expired, taxable, tax, loss_cf = (np.zeros(n) for _ in range(6))
    vintages: list[list[float]] = []  # [year index of origin, remaining amount], oldest first
    for i in range(n):
        if carry_forward_years is not None:
            keep = []
            for origin, amount in vintages:
                if i - origin > carry_forward_years:
                    expired[i] += amount
                else:
                    keep.append([origin, amount])
            vintages = keep
        loss_bf[i] = sum(amount for _, amount in vintages)
        if pbt[i] > 0:
            to_use = min(pbt[i], loss_bf[i])
            used[i] = to_use
            for vintage in vintages:  # oldest first
                take = min(vintage[1], to_use)
                vintage[1] -= take
                to_use -= take
                if to_use <= 0:
                    break
            vintages = [v for v in vintages if v[1] > 1e-12]
            taxable[i] = pbt[i] - used[i]
        elif pbt[i] < 0:
            vintages.append([i, -pbt[i]])
        tax[i] = rate * taxable[i]
        loss_cf[i] = sum(amount for _, amount in vintages)
    return loss_bf, used, expired, taxable, tax, loss_cf


def compute_tax(
    ebitda: np.ndarray,
    depreciation: np.ndarray,
    interest: np.ndarray,
    rate: float,
    carry_forward_years: int | None,
    tl: Timeline,
) -> TaxResult:
    pbt = (ebitda - depreciation - interest) * tl.is_operation
    loss_bf, used, expired, taxable, tax, loss_cf = tax_with_losses(pbt, rate, carry_forward_years)
    return TaxResult(
        depreciation=depreciation,
        interest=interest,
        pbt=pbt,
        loss_bf=loss_bf,
        loss_used=used,
        loss_expired=expired,
        taxable_income=taxable,
        tax=tax,
        loss_cf=loss_cf,
    )
