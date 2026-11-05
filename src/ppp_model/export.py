"""Excel export (README §13.2 sheet map, §14).

Writes calculated *values* from the Python engine (no formulas, no macros), so the workbook shows
the right numbers without recalculation. Time-series sheets follow the FAST convention: line items
in rows, model years in columns, with units, a total column for flows, frozen headers, number
formats in ₹ crore / % / x, and conditional formatting for covenant breaches and failed checks.
"""

from __future__ import annotations

import io
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import xlsxwriter

from .checks import CheckResult, HandCheckRow, hand_check
from .inputs import inputs_to_dict
from .model import ModelResults

# Line items that are balances, ratios or drivers: no total, and their own number format.
_BALANCES = {
    "Opening debt", "Closing debt", "DSRA target", "DSRA opening", "DSRA closing", "MMRA balance",
    "Lock-up balance", "Cumulative capex", "Cumulative equity cash flow", "Loss b/f", "Loss c/f",
    "Annuity balance (opening)",
}
_RATIOS = {"DSCR", "LLCR", "PLCR", "ICR"}
_PERCENT = {"Phasing", "Ramp-up factor", "Support milestone share"}
_FACTORS = {"Escalation factor", "Price Index Multiple"}
_FLAGS = {"Construction flag", "Operation flag", "Moratorium flag", "Repayment flag",
          "Capacity cap binding (1=yes)", "Op year"}
_TEXT = {"Fiscal year", "Phase"}

# README symbol and unit for the main inputs (shown on the Assumptions sheet).
_SYMBOLS = {
    "timeline.construction_years": ("Tc", "years"), "timeline.concession_years": ("Tcon", "years"),
    "capex.base_cost": ("C0", "₹ Cr"), "capex.phasing": ("p_t", "%"), "capex.escalation": ("e_c", "% p.a."),
    "capex.contingency": ("cont", "% of hard cost"), "capex.preop": ("preop", "% of hard cost"),
    "funding.gearing": ("g", "%"), "funding.grant_pct": ("grant_pct", "% of capex"),
    "funding.equity_mode": ("eq_mode", ""), "funding.drawdown_timing": ("m", "share of year"),
    "funding.upfront_fee": ("fee", "% of debt"), "debt.interest_rate": ("r", "% p.a."),
    "debt.tenor_years": ("n", "years"), "debt.moratorium_years": ("mor", "years"),
    "debt.profile": ("profile", ""), "debt.structured_pct": ("s_k", "%"), "debt.target_dscr": ("dscr_target", "x"),
    "reserves.dsra_months": ("dsra_months", "months"), "reserves.lockup_dscr": ("lockup", "x"),
    "revenue.toll.aadt": ("AADT0", "PCU/day"), "revenue.toll.growth": ("g_tr", "% p.a."),
    "revenue.toll.rate": ("rate0", "₹/PCU-trip"), "revenue.toll.rate_escalation": ("e_toll", "% p.a."),
    "revenue.toll.ramp_up": ("R_k", "%"), "revenue.toll.leakage": ("leak", "%"), "revenue.toll.capacity": ("cap", "PCU/day"),
    "opex.om_base": ("OM0", "₹ Cr p.a."), "opex.om_escalation": ("e_om", "% p.a."), "opex.mmr_base": ("MMR0", "₹ Cr"),
    "tax.rate": ("tax", "%"), "stress.demand_shortfall": ("short", "%"), "stress.cost_overrun": ("overrun", "%"),
    "stress.overrun_funding": ("overrun_mode", ""), "stress.delay_years": ("delay_years", "years"),
    "stress.rate_shock": ("Δr", "% p.a."),
}


class _Formats:
    def __init__(self, wb: xlsxwriter.Workbook):
        base = {"font_name": "Calibri", "font_size": 10}
        self.title = wb.add_format({**base, "bold": True, "font_size": 14, "font_color": "#1F3864"})
        self.subtitle = wb.add_format({**base, "italic": True, "font_color": "#595959"})
        self.header = wb.add_format({**base, "bold": True, "bg_color": "#1F3864", "font_color": "#FFFFFF",
                                     "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
        self.label = wb.add_format({**base})
        self.label_bold = wb.add_format({**base, "bold": True})
        self.section = wb.add_format({**base, "bold": True, "bg_color": "#D9E1F2"})
        self.unit = wb.add_format({**base, "font_color": "#7F7F7F"})
        self.money = wb.add_format({**base, "num_format": "#,##0.00;[Red]-#,##0.00;-"})
        self.money_bold = wb.add_format({**base, "bold": True, "num_format": "#,##0.00;[Red]-#,##0.00;-"})
        self.money4 = wb.add_format({**base, "num_format": "#,##0.0000;[Red]-#,##0.0000"})
        self.pct = wb.add_format({**base, "num_format": "0.00%"})
        self.ratio = wb.add_format({**base, "num_format": '0.00"x"'})
        self.ratio4 = wb.add_format({**base, "num_format": '0.0000"x"'})
        self.factor = wb.add_format({**base, "num_format": "0.0000"})
        self.integer = wb.add_format({**base, "num_format": "0"})
        self.count = wb.add_format({**base, "num_format": "#,##0"})
        self.sci = wb.add_format({**base, "num_format": "0.00E+00"})
        self.text = wb.add_format({**base})
        self.wrap = wb.add_format({**base, "text_wrap": True, "valign": "top"})
        self.red = wb.add_format({"bg_color": "#F8CBAD", "font_color": "#9C0006"})
        self.amber = wb.add_format({"bg_color": "#FFE699", "font_color": "#7F6000"})
        self.green = wb.add_format({"bg_color": "#C6EFCE", "font_color": "#006100"})
        self.grey = wb.add_format({"bg_color": "#EDEDED", "font_color": "#595959"})


def _fmt_for(name: str, f: _Formats):
    if name in _RATIOS:
        return f.ratio
    if name in _PERCENT:
        return f.pct
    if name in _FACTORS:
        return f.factor
    if name in _FLAGS:
        return f.integer
    if name in _TEXT:
        return f.text
    if "PCU/day" in name or "pax/day" in name:
        return f.count
    return f.money


def _unit_for(name: str) -> str:
    if name in _RATIOS:
        return "x"
    if name in _PERCENT:
        return "%"
    if name in _FACTORS or name in _FLAGS or name in _TEXT:
        return ""
    if "(" in name and name.endswith(")") and ("/day" in name or "/trip" in name):
        return name[name.rfind("(") + 1:-1]
    return "₹ Cr"


def _write_cell(ws, row: int, col: int, value, fmt) -> None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        ws.write_blank(row, col, None, fmt)
    elif isinstance(value, (np.floating, np.integer)):
        _write_cell(ws, row, col, value.item(), fmt)
    else:
        ws.write(row, col, value, fmt)


def _timeseries_sheet(wb, f: _Formats, res: ModelResults, name: str, title: str, columns: list[str],
                      covenant: float | None = None) -> None:
    ws = wb.add_worksheet(name)
    annual, tl = res.annual, res.timeline
    ws.write(0, 0, title, f.title)
    ws.write(1, 0, f"{res.inputs.project.name} | ₹ crore unless stated | values from the Python engine", f.subtitle)
    header_row = 3
    ws.write(header_row, 0, "Line item", f.header)
    ws.write(header_row, 1, "Unit", f.header)
    ws.write(header_row, 2, "Total", f.header)
    for j, t in enumerate(tl.year):
        ws.write(header_row, 3 + j, f"Year {t}", f.header)
        ws.write(header_row + 1, 3 + j, tl.labels[j], f.unit)
        ws.write(header_row + 2, 3 + j, "C" if tl.is_construction[j] else f"Op {tl.op_year[j]}", f.unit)
    ws.write(header_row + 1, 0, "Fiscal year", f.unit)
    ws.write(header_row + 2, 0, "Phase / op year", f.unit)
    row = header_row + 3
    for col in columns:
        if col not in annual.columns:
            continue
        fmt = _fmt_for(col, f)
        ws.write(row, 0, col, f.label_bold if col in {"CFADS", "EBITDA", "Total revenue", "Debt service",
                                                         "Equity cash flow", "Capex", "Total uses"} else f.label)
        ws.write(row, 1, _unit_for(col), f.unit)
        values = annual[col].tolist()
        numeric = col not in _TEXT
        if numeric and col not in _BALANCES | _RATIOS | _PERCENT | _FACTORS | _FLAGS and "/day" not in col \
                and "/trip" not in col:
            _write_cell(ws, row, 2, float(np.nansum(np.asarray(values, dtype=float))), f.money_bold)
        for j, v in enumerate(values):
            _write_cell(ws, row, 3 + j, v, fmt)
        if col == "DSCR" and covenant is not None:
            rng = (row, 3, row, 2 + len(values))
            ws.conditional_format(*rng, {"type": "cell", "criteria": "<", "value": 1.0, "format": f.red})
            ws.conditional_format(*rng, {"type": "cell", "criteria": "between", "minimum": 1.0,
                                         "maximum": covenant - 1e-9, "format": f.amber})
        row += 1
    ws.set_column(0, 0, 34)
    ws.set_column(1, 1, 11)
    ws.set_column(2, 2, 12)
    ws.set_column(3, 2 + tl.model_years, 11)
    ws.freeze_panes(header_row + 3, 3)


def _table_sheet(wb, f: _Formats, name: str, title: str, df: pd.DataFrame, formats: dict[str, object],
                 subtitle: str = "", index_label: str | None = None) -> xlsxwriter.worksheet.Worksheet:
    ws = wb.add_worksheet(name)
    ws.write(0, 0, title, f.title)
    if subtitle:
        ws.write(1, 0, subtitle, f.subtitle)
    frame = df.reset_index() if index_label is not None else df
    if index_label is not None:
        frame = frame.rename(columns={frame.columns[0]: index_label})
    header_row = 3
    for j, col in enumerate(frame.columns):
        ws.write(header_row, j, str(col), f.header)
        ws.set_column(j, j, max(12, min(48, len(str(col)) + 4)))
    for i, record in enumerate(frame.itertuples(index=False), start=header_row + 1):
        for j, (col, value) in enumerate(zip(frame.columns, record)):
            _write_cell(ws, i, j, value, formats.get(str(col), f.text))
    ws.freeze_panes(header_row + 1, 1)
    if len(frame):
        ws.autofilter(header_row, 0, header_row + len(frame), len(frame.columns) - 1)
    return ws


def _summary_sheet(wb, f: _Formats, res: ModelResults, scenario_label: str) -> None:
    ws = wb.add_worksheet("Summary")
    mt, tl, inp = res.metrics, res.timeline, res.inputs
    ws.write(0, 0, "PPP Project Financial Model - Summary", f.title)
    ws.write(1, 0, f"{inp.project.name} | scenario: {scenario_label} | generated {date.today():%d %b %Y} "
                   "| all money in ₹ crore", f.subtitle)
    n_fail = sum(c.status == "fail" for c in res.checks)
    n_warn = sum(c.status == "warn" for c in res.checks)
    rows = [
        ("Project type", inp.project_type.upper(), f.text),
        ("Construction / operations / concession (years)",
         f"{tl.construction_years} / {tl.operating_years} / {tl.model_years}", f.text),
        ("Total Project Cost", mt.total_project_cost, f.money),
        ("  of which capex", mt.capex, f.money),
        ("  of which IDC", mt.idc, f.money),
        ("  of which upfront fees", mt.fees, f.money),
        ("Grant / construction support", mt.grant, f.money),
        ("Debt at COD", mt.debt, f.money),
        ("Equity", mt.equity, f.money),
        ("Gearing applied", mt.gearing_applied, f.pct),
        ("Debt sizing", res.sizing.message, f.text),
        ("Minimum DSCR", mt.min_dscr, f.ratio4),
        ("  in op year", mt.min_dscr_op_year, f.integer),
        ("Average DSCR", mt.avg_dscr, f.ratio4),
        ("LLCR at COD", mt.llcr_cod, f.ratio4),
        ("PLCR at COD", mt.plcr_cod, f.ratio4),
        ("Minimum ICR", mt.min_icr, f.ratio4),
        ("Project IRR (post-tax, unlevered)", mt.project_irr.value, f.pct),
        ("Project IRR after grant", mt.project_irr_post_grant.value, f.pct),
        ("Equity IRR", mt.equity_irr.value, f.pct),
        (f"Project NPV @ {inp.valuation.discount_rate:.1%}", mt.project_npv, f.money),
        (f"Equity NPV @ hurdle {inp.valuation.equity_hurdle:.1%}", mt.equity_npv, f.money),
        ("Equity payback", mt.payback.display(), f.text),
        ("Debt fully repaid?", "Yes" if mt.debt_fully_repaid else "No", f.text),
        ("Final repayment op year", mt.final_repayment_op_year, f.integer),
        ("Tail (years)", mt.tail_years, f.integer),
        ("DSCR < 1.00x in op years", ", ".join(map(str, mt.dscr_below_one_years)) or "none", f.text),
        ("Equity IRR >= hurdle?", {True: "Yes", False: "No", None: "n/a"}[mt.equity_meets_hurdle], f.text),
        ("Sponsor support required", mt.sponsor_support, f.money),
        ("Integrity checks", "ALL PASS" if n_fail == 0 else f"{n_fail} FAILED", f.text),
        ("Financial warnings", n_warn, f.integer),
    ]
    for i, (label, value, fmt) in enumerate(rows, start=3):
        ws.write(i, 0, label, f.label_bold if not label.startswith("  ") else f.label)
        _write_cell(ws, i, 1, value, fmt)
    status_row = 3 + len(rows) - 2
    ws.write(status_row, 1, "ALL PASS" if n_fail == 0 else f"{n_fail} FAILED", f.green if n_fail == 0 else f.red)
    start = 3 + len(rows) + 1
    ws.write(start, 0, "Warnings and notes", f.section)
    for i, w in enumerate(res.warnings or ["None"], start=start + 1):
        ws.write(i, 0, w, f.wrap)
    ws.set_column(0, 0, 46)
    ws.set_column(1, 1, 60)


def _assumptions_df(res: ModelResults) -> pd.DataFrame:
    rows = []

    def walk(prefix: str, node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(f"{prefix}.{k}" if prefix else k, v)
            return
        if isinstance(node, list):
            value = ", ".join(f"{x:g}" if isinstance(x, float) else str(x) for x in node)
        else:
            value = "null" if node is None else node
        symbol, unit = _SYMBOLS.get(prefix, ("", ""))
        rows.append({"Block": prefix.split(".")[0], "Input": prefix, "README symbol": symbol, "Value": value,
                     "Unit": unit})

    walk("", inputs_to_dict(res.inputs))
    return pd.DataFrame(rows)


def _checks_df(checks: list[CheckResult]) -> pd.DataFrame:
    return pd.DataFrame([{"ID": c.id, "Check": c.name, "Category": c.category, "Status": c.status.upper(),
                          "Value": c.value, "Tolerance": c.tolerance, "Detail": c.detail} for c in checks])


def hand_check_df(rows: list[HandCheckRow]) -> pd.DataFrame:
    return pd.DataFrame([{"Year / item": r.section, "Item": r.item, "Calculator working": r.working,
                          "Hand value": r.hand_value, "Model value": r.model_value,
                          "Difference": r.difference, "OK? (< 0.01)": "OK" if r.ok else "CHECK"} for r in rows])


def _status_formatting(ws, f: _Formats, column: int, n_rows: int, header_row: int = 3) -> None:
    if n_rows == 0:
        return
    rng = (header_row + 1, column, header_row + n_rows, column)
    for text, fmt in (("FAIL", f.red), ("CHECK", f.red), ("WARN", f.amber), ("PASS", f.green), ("OK", f.green),
                      ("INFO", f.grey)):
        ws.conditional_format(*rng, {"type": "cell", "criteria": "==", "value": f'"{text}"', "format": fmt})


def build_workbook(res: ModelResults, *, scenario_label: str = "Base case",
                   scenario_table: pd.DataFrame | None = None, two_way: pd.DataFrame | None = None,
                   tornado_df: pd.DataFrame | None = None, profile_table: pd.DataFrame | None = None) -> bytes:
    """Build the full model workbook in memory and return its bytes."""
    buffer = io.BytesIO()
    wb = xlsxwriter.Workbook(buffer, {"in_memory": True, "nan_inf_to_errors": False})
    f = _Formats(wb)
    cov = res.inputs.covenants.min_dscr
    groups = res.schedule_columns()

    _summary_sheet(wb, f, res, scenario_label)
    ws = _table_sheet(wb, f, "Assumptions", "Assumptions (inputs used in this run)", _assumptions_df(res),
                      {}, "Every number the model uses comes from these inputs (config/*.yaml + scenario overrides).")
    ws.set_column(1, 1, 38)
    ws.set_column(3, 3, 30)
    _timeseries_sheet(wb, f, res, "Timeline", "Timeline and flags", groups["Timeline"])
    _timeseries_sheet(wb, f, res, "Capex", "Capital expenditure", groups["Capex"])
    _timeseries_sheet(wb, f, res, "Funding_IDC", "Sources and uses, funding and IDC", groups["Funding & IDC"])
    _timeseries_sheet(wb, f, res, "Revenue", "Revenue", groups["Revenue"])
    om_tax = groups["Opex & EBITDA"] + [c for c in groups["Tax"] if c not in groups["Opex & EBITDA"]]
    _timeseries_sheet(wb, f, res, "OM_Tax", "Operating costs, depreciation and tax", om_tax)
    _timeseries_sheet(wb, f, res, "Debt", "Debt schedule and cover ratios",
                      groups["Debt schedule"] + ["CFADS", "DSCR", "LLCR", "PLCR", "ICR"], covenant=cov)
    _timeseries_sheet(wb, f, res, "CFADS_Waterfall", "CFADS and cash-flow waterfall",
                      groups["CFADS"] + [c for c in groups["Waterfall"] if c != "CFADS"] + groups["Returns"],
                      covenant=cov)

    mt = res.metrics
    metrics = pd.DataFrame([
        ("Minimum DSCR", mt.min_dscr, f"op year {mt.min_dscr_op_year}"),
        ("Average DSCR (debt-service years)", mt.avg_dscr, ""),
        ("LLCR at COD", mt.llcr_cod, f"discounted at r = {res.inputs.interest_rate:.2%}"),
        ("PLCR at COD", mt.plcr_cod, "includes the tail"),
        ("Minimum ICR", mt.min_icr, ""),
        ("Project IRR", mt.project_irr.value, mt.project_irr.message),
        ("Project IRR after grant", mt.project_irr_post_grant.value, mt.project_irr_post_grant.message),
        ("Equity IRR", mt.equity_irr.value, mt.equity_irr.message),
        ("Project NPV", mt.project_npv, f"at {res.inputs.valuation.discount_rate:.2%}, valued at financial close"),
        ("Equity NPV", mt.equity_npv, f"at hurdle {res.inputs.valuation.equity_hurdle:.2%}"),
        ("Equity payback", mt.payback.display(), ""),
        ("Tail (years)", mt.tail_years, ""),
    ], columns=["Metric", "Value", "Note"])
    ws = wb.add_worksheet("Metrics")
    ws.write(0, 0, "Financial metrics", f.title)
    ws.write(1, 0, "Ratios in x, returns in %, money in ₹ crore", f.subtitle)
    for j, h in enumerate(metrics.columns):
        ws.write(3, j, h, f.header)
    for i, (metric, value, note) in enumerate(metrics.itertuples(index=False), start=4):
        ws.write(i, 0, metric, f.label_bold)
        fmt = f.pct if "IRR" in metric else f.money if "NPV" in metric else f.integer if "Tail" in metric \
            else f.text if isinstance(value, str) else f.ratio4
        _write_cell(ws, i, 1, value, fmt)
        ws.write(i, 2, note, f.text)
    ws.set_column(0, 0, 36)
    ws.set_column(1, 1, 16)
    ws.set_column(2, 2, 80)

    if scenario_table is not None:
        sc_formats = {c: f.money for c in ("TPC", "Debt", "Equity", "IDC", "NPV", "Sponsor support")}
        sc_formats.update({c: f.ratio for c in ("Min DSCR", "Avg DSCR", "LLCR at COD")})
        sc_formats.update({c: f.pct for c in ("Project IRR", "Project IRR (post-grant)", "Equity IRR")})
        sc_formats["Min DSCR op year"] = f.integer
        ws = _table_sheet(wb, f, "Scenarios", "Scenario comparison (README §10.2)", scenario_table.drop(
            columns=[c for c in ("Key",) if c in scenario_table.columns]), sc_formats,
            "Each scenario = base inputs + overrides from config/scenarios.yaml", index_label="Key")
        cols = ["Key", *[c for c in scenario_table.columns if c != "Key"]]
        n = len(scenario_table)
        if "Min DSCR" in cols:
            j = cols.index("Min DSCR")
            ws.conditional_format(4, j, 3 + n, j, {"type": "cell", "criteria": "<", "value": 1.0, "format": f.red})
            ws.conditional_format(4, j, 3 + n, j, {"type": "cell", "criteria": "between", "minimum": 1.0,
                                                   "maximum": cov - 1e-9, "format": f.amber})
        if "Equity IRR" in cols:
            j = cols.index("Equity IRR")
            ws.conditional_format(4, j, 3 + n, j, {"type": "cell", "criteria": "<",
                                                   "value": res.inputs.valuation.equity_hurdle, "format": f.red})

    if two_way is not None or tornado_df is not None or profile_table is not None:
        ws = wb.add_worksheet("Sensitivity")
        ws.write(0, 0, "Sensitivity analysis (README §10.3)", f.title)
        row = 2
        if two_way is not None:
            ws.write(row, 0, "Minimum DSCR: traffic shortfall (rows) x cost overrun (columns)", f.section)
            row += 1
            ws.write(row, 0, "Shortfall \\ overrun", f.header)
            for j, o in enumerate(two_way.columns):
                ws.write(row, 1 + j, float(o), wb.add_format({"bold": True, "num_format": "0%", "bg_color": "#1F3864",
                                                              "font_color": "#FFFFFF", "align": "center"}))
            for i, s in enumerate(two_way.index):
                ws.write(row + 1 + i, 0, float(s), f.pct)
                for j, o in enumerate(two_way.columns):
                    _write_cell(ws, row + 1 + i, 1 + j, two_way.loc[s, o], f.ratio)
            rng = (row + 1, 1, row + len(two_way.index), len(two_way.columns))
            ws.conditional_format(*rng, {"type": "cell", "criteria": "<", "value": 1.0, "format": f.red})
            ws.conditional_format(*rng, {"type": "cell", "criteria": "between", "minimum": 1.0,
                                         "maximum": cov - 1e-9, "format": f.amber})
            ws.conditional_format(*rng, {"type": "cell", "criteria": ">=", "value": cov, "format": f.green})
            row += len(two_way.index) + 3
        if tornado_df is not None:
            ws.write(row, 0, f"Tornado: each input moved by +/-{tornado_df.attrs.get('shock', 0.1):.0%}", f.section)
            row += 1
            cols = ["Variable", "Base value", "Equity IRR (low)", "Equity IRR (high)", "Δ Equity IRR (low)",
                    "Δ Equity IRR (high)", "Min DSCR (low)", "Min DSCR (high)", "Note"]
            for j, c in enumerate(cols):
                ws.write(row, j, c, f.header)
            for i, rec in enumerate(tornado_df[cols].itertuples(index=False), start=row + 1):
                for j, (c, v) in enumerate(zip(cols, rec)):
                    fmt = f.pct if "IRR" in c else f.ratio if "DSCR" in c else f.factor if c == "Base value" else f.text
                    _write_cell(ws, i, j, v, fmt)
            row += len(tornado_df) + 3
        if profile_table is not None:
            ws.write(row, 0, "Repayment profile comparison (README §11.4)", f.section)
            row += 1
            frame = profile_table.reset_index()
            for j, c in enumerate(frame.columns):
                ws.write(row, j, c, f.header)
            for i, rec in enumerate(frame.itertuples(index=False), start=row + 1):
                for j, (c, v) in enumerate(zip(frame.columns, rec)):
                    fmt = f.pct if "IRR" in c else f.ratio if ("DSCR" in c or "LLCR" in c) and "year" not in c \
                        else f.integer if "year" in c else f.text
                    _write_cell(ws, i, j, v, fmt)
        ws.set_column(0, 0, 26)
        ws.set_column(1, 12, 15)

    checks = _checks_df(res.checks)
    ws = _table_sheet(wb, f, "Checks", "Validation checks (README §12.1)", checks,
                      {"Value": f.sci, "Tolerance": f.sci},
                      "Integrity: FAIL means the arithmetic is wrong. Financial: WARN flags covenant / hurdle issues.")
    ws.set_column(1, 1, 52)
    ws.set_column(6, 6, 110)
    _status_formatting(ws, f, 3, len(checks))

    hc = hand_check_df(hand_check(res))
    ws = _table_sheet(wb, f, "HandCheck", "Hand check (README §12.3)", hc,
                      {"Hand value": f.money4, "Model value": f.money4, "Difference": f.sci},
                      "Hand values recomputed from the inputs with scalar (calculator) formulas; "
                      "'model value' in the working marks a figure taken from the model as the README allows.")
    ws.set_column(0, 0, 30)
    ws.set_column(1, 1, 30)
    ws.set_column(2, 2, 100)
    _status_formatting(ws, f, 6, len(hc))

    if res.revenue.semiannual is not None:
        _table_sheet(wb, f, "HAM_Annuity", "HAM annuity schedule (semi-annual, aggregated to annual in Revenue)",
                     res.revenue.semiannual, {c: f.money for c in ("Opening balance", "Annuity principal",
                                                                    "Annuity interest", "Total annuity",
                                                                    "Closing balance")})
    wb.close()
    return buffer.getvalue()


def write_workbook(res: ModelResults, path: str | Path, **kwargs) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_workbook(res, **kwargs))
    return path


def build_hand_check_workbook(res: ModelResults) -> bytes:
    """Stand-alone hand-check workbook (validation/hand_check.xlsx)."""
    buffer = io.BytesIO()
    wb = xlsxwriter.Workbook(buffer, {"in_memory": True, "nan_inf_to_errors": False})
    f = _Formats(wb)
    rows = hand_check(res)
    hc = hand_check_df(rows)
    ws = _table_sheet(wb, f, "HandCheck", f"Hand check: {res.inputs.project.name}", hc,
                      {"Hand value": f.money4, "Model value": f.money4, "Difference": f.sci},
                      "README §12.3: calculator working from the inputs vs the model; tolerance 0.01.")
    ws.set_column(0, 1, 30)
    ws.set_column(2, 2, 100)
    _status_formatting(ws, f, 6, len(hc))
    n_ok = sum(r.ok for r in rows)
    ws.write(5 + len(rows), 0, f"Result: {n_ok} of {len(rows)} items agree within 0.01", f.label_bold)
    inputs = _assumptions_df(res)
    _table_sheet(wb, f, "Inputs", "Inputs used by the hand check", inputs, {})
    wb.close()
    return buffer.getvalue()
