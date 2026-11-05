"""Streamlit dashboard for the PPP project financial model (README §14).

Run from the project folder:

    streamlit run app/dashboard.py

This file only *displays* results. Every number comes from ``ppp_model`` (``run_model``, the
scenario engine and the checks), so the dashboard can never disagree with the tested model.
Covenant DSCR and equity hurdle are read from the config, never typed in here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # works without installing the package or setting PYTHONPATH
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402
import yaml  # noqa: E402
from plotly.subplots import make_subplots  # noqa: E402

from ppp_model import (  # noqa: E402
    InputValidationError,
    ModelError,
    base_config_path,
    build_inputs,
    deep_merge,
    inputs_to_dict,
    load_yaml,
    run_model,
)
from chatbot import build_context, render_chat  # noqa: E402
from ppp_model.checks import hand_check  # noqa: E402
from ppp_model.debt import default_structured_pct  # noqa: E402
from ppp_model.export import build_workbook, hand_check_df  # noqa: E402
from ppp_model.metrics import meets  # noqa: E402
from ppp_model.scenarios import (  # noqa: E402
    break_even_shortfall,
    ham_traffic_demonstration,
    load_scenarios,
    profile_comparison,
    run_scenarios,
    tornado,
    two_way_table,
)

st.set_page_config(page_title="PPP Financial Model", page_icon=":material/account_balance:", layout="wide")

PROJECT_LABELS = {"toll": "BOT toll road", "metro": "Metro (PPP)", "ham": "Hybrid Annuity Model (HAM)"}
SCENARIOS = load_scenarios()
PLOT_CONFIG = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


# =============================================================================================
# State: base assumptions per project type, scenario, stress levers
# =============================================================================================


def scenario_levers(key: str, ptype: str) -> dict:
    """Slider positions implied by a scenario's stress overrides (README: picking a scenario sets them)."""
    stress = SCENARIOS.scenarios[key].overrides_for(ptype).get("stress", {})
    return {
        "lever_demand_shortfall": round(100 * stress.get("demand_shortfall", 0.0)),
        "lever_cost_overrun": round(100 * stress.get("cost_overrun", 0.0)),
        "lever_overrun_funding": stress.get("overrun_funding", "pro_rata"),
        "lever_delay_years": int(stress.get("delay_years", 0)),
        "lever_rate_shock": round(10000 * stress.get("rate_shock", 0.0)),
    }


def apply_scenario_levers() -> None:
    ss = st.session_state
    for k, v in scenario_levers(ss.scenario, ss.ptype).items():
        ss[k] = v


def on_type_change() -> None:
    st.session_state.scenario = "base"
    apply_scenario_levers()


def init_state() -> None:
    ss = st.session_state
    if "base" not in ss:
        ss.base = {p: load_yaml(base_config_path(p)) for p in PROJECT_LABELS}
    ss.setdefault("ptype", "toll")
    ss.setdefault("scenario", "base")
    for k, v in scenario_levers(ss.scenario, ss.ptype).items():
        ss.setdefault(k, v)


def effective_raw() -> dict:
    """Base assumptions + scenario overrides + sidebar levers (a fresh dict every time)."""
    ss = st.session_state
    raw = deep_merge(ss.base[ss.ptype], SCENARIOS.scenarios[ss.scenario].overrides_for(ss.ptype))
    return deep_merge(raw, {"stress": {
        "demand_shortfall": ss.lever_demand_shortfall / 100.0,
        "cost_overrun": ss.lever_cost_overrun / 100.0,
        "overrun_funding": ss.lever_overrun_funding or "pro_rata",
        "delay_years": int(ss.lever_delay_years),
        "rate_shock": ss.lever_rate_shock / 10000.0,
    }})


def levers_customised() -> bool:
    ss = st.session_state
    return any(ss[k] != v for k, v in scenario_levers(ss.scenario, ss.ptype).items())


# =============================================================================================
# Cached model runs (Streamlit reruns the script on every change; identical inputs run once)
# =============================================================================================


def key_of(raw: dict) -> str:
    return json.dumps(raw, sort_keys=True, default=str)


@st.cache_resource(max_entries=256, show_spinner=False)
def run_cached(key: str):
    return run_model(json.loads(key))


@st.cache_data(max_entries=32, show_spinner="Running all scenarios…")
def scenarios_cached(base_key: str) -> pd.DataFrame:
    table, _ = run_scenarios(json.loads(base_key), SCENARIOS)
    return table


@st.cache_data(max_entries=32, show_spinner="Running the two-way sensitivity…")
def two_way_cached(key: str, metric: str) -> pd.DataFrame:
    return two_way_table(json.loads(key), SCENARIOS.two_way_shortfalls, SCENARIOS.two_way_overruns, metric)


@st.cache_data(max_entries=32, show_spinner="Running the tornado…")
def tornado_cached(key: str, ptype: str) -> tuple[pd.DataFrame, dict]:
    df = tornado(json.loads(key), SCENARIOS.tornado_variables.get(ptype, ()), SCENARIOS.tornado_shock)
    return df, dict(df.attrs)


@st.cache_data(max_entries=32, show_spinner="Searching for break-even traffic shortfall…")
def break_even_cached(key: str, metric: str, threshold: float):
    return break_even_shortfall(json.loads(key), metric=metric, threshold=threshold,
                                max_shortfall=SCENARIOS.break_even_max_shortfall, tol=SCENARIOS.break_even_tolerance)


@st.cache_data(max_entries=32, show_spinner="Comparing repayment profiles…")
def profiles_cached(key: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    table, results = profile_comparison(json.loads(key))
    tl = next(iter(results.values())).timeline
    ops = slice(tl.cod_index, tl.model_years)
    dscr = pd.DataFrame({p: r.dscr[ops] for p, r in results.items()}, index=pd.Index(tl.op_year[ops], name="Op year"))
    return table, dscr


@st.cache_data(max_entries=16, show_spinner=False)
def ham_demo_cached(key: str) -> tuple[pd.DataFrame, float]:
    df = ham_traffic_demonstration(json.loads(key))
    return df, df.attrs["max_revenue_difference"]


@st.cache_data(max_entries=16, show_spinner="Building the Excel workbook…")
def workbook_cached(key: str, base_key: str, label: str, ptype: str) -> bytes:
    raw = json.loads(key)
    res = run_cached(key)
    return build_workbook(
        res, scenario_label=label, scenario_table=scenarios_cached(base_key),
        two_way=two_way_cached(key, "min_dscr"), tornado_df=_tornado_with_attrs(key, ptype),
        profile_table=profiles_cached(key)[0],
    )


def _tornado_with_attrs(key: str, ptype: str) -> pd.DataFrame:
    df, attrs = tornado_cached(key, ptype)
    df = df.copy()
    df.attrs.update(attrs)
    return df


# =============================================================================================
# Formatting and chart styling
# =============================================================================================


def cr(x, d: int = 2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"₹{x:,.{d}f} Cr"


def money(x, d: int = 2) -> str:
    """Bare ₹ crore figure for KPI tiles (the unit sits in the label, so the value never truncates)."""
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:,.{d}f}"


def pct(x, d: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{d}%}"


def ratio(x, d: int = 2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}x"


def theme() -> SimpleNamespace:
    context_theme = st.context.theme
    dark = (context_theme.get("type") if hasattr(context_theme, "get") else None) == "dark"
    if dark:
        return SimpleNamespace(
            dark=True, surface="#1a1a19", ink="#f0efec", ink2="#c3c2b7", muted="#898781", grid="#2c2c2a",
            axis="#383835", series=["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"],
            ordinal=["#86b6ef", "#3987e5", "#1c5cab", "#104281"], gray="#5f5e5a",
            good="#0ca30c", warning="#fab219", critical="#d03b3b",
        )
    return SimpleNamespace(
        dark=False, surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781", grid="#e1e0d9",
        axis="#c3c2b7", series=["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"],
        ordinal=["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"], gray="#c3c2b7",
        good="#0ca30c", warning="#fab219", critical="#d03b3b",
    )


def style(fig: go.Figure, height: int = 360, *, legend: bool = True, hover: str = "x unified") -> go.Figure:
    t = theme()
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family='system-ui, -apple-system, "Segoe UI", sans-serif', size=12, color=t.ink2),
        margin=dict(l=64, r=24, t=48 if legend else 24, b=56), showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None,
                    font=dict(color=t.ink2), traceorder="normal"),
        hovermode=hover, barcornerradius=4,
        hoverlabel=dict(bgcolor=t.surface, bordercolor=t.axis, font=dict(color=t.ink)),
    )
    fig.update_xaxes(showgrid=False, linecolor=t.axis, linewidth=1, ticks="outside", tickcolor=t.axis,
                     zeroline=False, automargin=True, title_font=dict(color=t.ink2), tickfont=dict(color=t.ink2))
    fig.update_yaxes(gridcolor=t.grid, gridwidth=1, zeroline=True, zerolinecolor=t.axis, zerolinewidth=1,
                     linecolor=t.axis, automargin=True, title_font=dict(color=t.ink2), tickfont=dict(color=t.ink2))
    return fig


def threshold_line(fig: go.Figure, y: float, label: str, color: str, position: str = "top right", **subplot) -> None:
    """Dashed threshold (covenant, 1.00x, capacity) with its label; dashing marks a threshold, not a grid."""
    fig.add_hline(y=y, line=dict(color=color, width=1, dash="dash"), annotation_text=label,
                  annotation_position=position, annotation_font=dict(size=11, color=theme().ink2), **subplot)


def show(fig: go.Figure, data: pd.DataFrame | None = None, key: str | None = None, caption: str | None = None):
    """Render a chart with its table-view twin (values are never available on hover only)."""
    st.plotly_chart(fig, width="stretch", theme=None, config=PLOT_CONFIG, key=key)
    if caption:
        st.caption(caption)
    if data is not None:
        with st.expander("Data table", icon=":material/table:"):
            st.dataframe(data, width="stretch")


def status_of_dscr(value, covenant):
    if value is None:
        return "gray", "No debt service", ":material/remove:"
    if not meets(value, 1.0):
        return "red", "Below 1.00x: default", ":material/error:"
    if not meets(value, covenant):
        return "orange", f"Below {covenant:.2f}x covenant", ":material/warning:"
    return "green", f"Meets {covenant:.2f}x covenant", ":material/check_circle:"


def status_color(value, covenant) -> str:
    t = theme()
    color = status_of_dscr(value, covenant)[0]
    return {"red": t.critical, "orange": t.warning, "green": t.good}.get(color, t.gray)


TINT = {"red": "rgba(208,59,59,0.24)", "orange": "rgba(250,178,25,0.30)", "green": "rgba(12,163,12,0.18)"}


def dscr_cell_style(covenant):
    def fn(v):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return ""
        return f"background-color: {TINT[status_of_dscr(v, covenant)[0]]}"
    return fn


def irr_cell_style(hurdle):
    def fn(v):
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            return f"background-color: {TINT['red']}"
        return f"background-color: {TINT['green'] if meets(v, hurdle) else TINT['red']}"
    return fn


# =============================================================================================
# Charts (each one draws model output; no calculations)
# =============================================================================================


def op_frame(res, columns: list[str]) -> pd.DataFrame:
    a = res.annual
    ops = a[a["Phase"] == "Operation"]
    return ops.set_index("Op year")[["Fiscal year", *columns]]


def op_axis(fig: go.Figure, res, **subplot) -> None:
    """Operating-year x-axis spanning exactly the concession's operating years."""
    n = res.timeline.operating_years
    fig.update_xaxes(title_text="Operating year", range=[0.4, n + 0.6], dtick=1 if n <= 20 else 2, **subplot)


def fig_cfads_dscr(res) -> go.Figure:
    """README chart 1: CFADS vs debt service, with DSCR in an aligned panel (one y-scale per panel)."""
    t, cov = theme(), res.inputs.covenants.min_dscr
    d = op_frame(res, ["CFADS", "Debt service", "DSCR"])
    k = d.index.to_numpy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38], vertical_spacing=0.07,
                        subplot_titles=("CFADS and debt service (₹ Cr)", "DSCR (x)"))
    fig.add_bar(x=k, y=d["CFADS"], name="CFADS", marker=dict(color=t.series[0], line=dict(width=1, color=t.surface)),
                customdata=d["Fiscal year"], hovertemplate="%{y:,.2f}<extra>CFADS</extra>", row=1, col=1)
    fig.add_bar(x=k, y=d["Debt service"], name="Debt service",
                marker=dict(color=t.series[1], line=dict(width=1, color=t.surface)),
                hovertemplate="%{y:,.2f}<extra>Debt service</extra>", row=1, col=1)
    dscr = d["DSCR"].astype(float)
    colors = [status_color(v if np.isfinite(v) else None, cov) for v in dscr]
    fig.add_scatter(x=k, y=dscr, name="DSCR", mode="lines+markers", line=dict(color=t.ink2, width=2),
                    marker=dict(size=9, color=colors, line=dict(width=2, color=t.surface)),
                    hovertemplate="%{y:.2f}x<extra>DSCR</extra>", showlegend=False, row=2, col=1)
    threshold_line(fig, cov, f"Covenant {cov:.2f}x", t.warning, row=2, col=1)
    threshold_line(fig, 1.0, "1.00x: CFADS = debt service", t.critical, "bottom right", row=2, col=1)
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    style(fig, 560)
    fig.update_layout(legend=dict(xanchor="right", x=1))  # keep clear of the left-aligned panel titles
    op_axis(fig, res)
    fig.update_xaxes(title_text=None, row=1, col=1)
    finite = dscr[np.isfinite(dscr)]
    top = max(float(finite.max()) * 1.08 if len(finite) else 2.0, cov * 1.15)
    fig.update_yaxes(range=[0, top], row=2, col=1)
    for ann in fig.layout.annotations[:2]:
        ann.update(font=dict(size=12, color=t.ink), x=0, xanchor="left")
    return fig


def fig_timeline(res) -> go.Figure:
    t, tl = theme(), res.timeline
    construction = f"Construction{' (incl. ' + str(tl.delay_years) + '-yr delay)' if tl.delay_years else ''}"
    segments = [(construction, tl.construction_years)]
    mor = min(tl.moratorium_years, tl.operating_years)
    if mor:
        segments.append(("Moratorium (interest only)", mor))
    repay = max(0, tl.last_repayment_op_year - mor)
    segments.append(("Debt repayment", repay))
    tail = max(0, tl.operating_years - tl.maturity_op_year)
    if tail:
        segments.append(("Tail (debt-free)", tail))
    fig = go.Figure()
    start = 0
    for (name, years), color in zip(segments, t.ordinal):
        text_color = "#0b0b0b" if color == t.ordinal[0] else "#ffffff"
        fig.add_bar(y=["Concession"], x=[years], base=[start], orientation="h", name=name, marker_color=color,
                    marker_line=dict(width=1, color=t.surface), text=[f"{name}: {years} yr"],
                    textposition="inside", insidetextanchor="middle", textfont=dict(color=text_color, size=12),
                    hovertemplate=f"{name}: years {start + 1}-{start + years}<extra></extra>")
        start += years
    fig.update_layout(barmode="stack", uniformtext=dict(minsize=10, mode="hide"), bargap=0.2)
    style(fig, 170, hover="closest")
    fig.update_xaxes(range=[0, tl.model_years], dtick=1 if tl.model_years <= 20 else 5, title_text="Model year")
    fig.update_yaxes(showticklabels=False, zeroline=False, showgrid=False)
    fig.update_layout(margin=dict(l=16, t=40, b=48))
    return fig


def fig_debt_balance(res) -> go.Figure:
    t, a = theme(), res.annual
    fig = go.Figure()
    fig.add_scatter(x=a.index, y=a["Closing debt"], mode="lines+markers", name="Closing debt",
                    line=dict(color=t.series[0], width=2), fill="tozeroy",
                    fillcolor="rgba(57,135,229,0.10)" if t.dark else "rgba(42,120,214,0.10)",
                    marker=dict(size=8, color=t.series[0], line=dict(width=2, color=t.surface)),
                    customdata=a["Fiscal year"], hovertemplate="%{customdata}: %{y:,.2f} ₹ Cr<extra></extra>")
    tl = res.timeline
    fig.add_vline(x=tl.construction_years + 0.5, line=dict(color=t.axis, width=1))
    fig.add_annotation(x=tl.construction_years + 0.5, y=1, yref="paper", text="COD", showarrow=False,
                       xanchor="left", yanchor="top", font=dict(color=t.ink2, size=11))
    style(fig, 320, legend=False, hover="x")
    fig.update_xaxes(title_text="Model year")
    fig.update_yaxes(title_text="₹ Cr")
    return fig


def fig_sources_uses(res) -> go.Figure:
    t, fu = theme(), res.funding
    uses = [("Capex", fu.capex_total), ("IDC", fu.idc_total), ("Fees & DSRA", fu.fees_total + fu.dsra_initial)]
    sources = [("Debt", fu.debt_at_cod), ("Equity", fu.equity_total), ("Grant / support", fu.grant_total)]
    fig = go.Figure()
    for i, (name, value) in enumerate(uses + sources):
        if value <= 1e-9:
            continue
        row = "Uses" if i < 3 else "Sources"
        fig.add_bar(y=[row], x=[value], orientation="h", name=name, marker_color=t.series[i],
                    marker_line=dict(width=1, color=t.surface), text=[f"{value:,.0f}"], textposition="inside",
                    insidetextanchor="middle", textfont=dict(color="#0b0b0b" if i == 3 else "#ffffff"),  # dark on yellow
                    hovertemplate=f"{name}: %{{x:,.2f}} ₹ Cr<extra></extra>")
    fig.update_layout(barmode="stack", bargap=0.45, uniformtext=dict(minsize=10, mode="hide"))
    style(fig, 230, hover="closest")
    fig.update_xaxes(title_text="₹ Cr")
    fig.update_yaxes(categoryorder="array", categoryarray=["Sources", "Uses"], zeroline=False)
    return fig


def fig_debt_service(res) -> go.Figure:
    t = theme()
    d = op_frame(res, ["Interest paid", "Principal"])
    fig = go.Figure()
    for i, col in enumerate(["Interest paid", "Principal"]):
        fig.add_bar(x=d.index, y=d[col], name=col.replace(" paid", ""), marker_color=t.series[i],
                    marker_line=dict(width=1, color=t.surface), hovertemplate=f"%{{y:,.2f}}<extra>{col}</extra>")
    fig.update_layout(barmode="stack", bargap=0.5)  # keeps full-width bars near the 24px mark spec
    style(fig, 340)
    op_axis(fig, res)
    fig.update_yaxes(title_text="₹ Cr")
    return fig


def fig_cover_ratios(res) -> go.Figure:
    t, cov = theme(), res.inputs.covenants.min_dscr
    d = op_frame(res, ["DSCR", "LLCR", "PLCR"])
    fig = go.Figure()
    for i, col in enumerate(["DSCR", "LLCR", "PLCR"]):
        fig.add_scatter(x=d.index, y=d[col], mode="lines+markers", name=col, line=dict(color=t.series[i], width=2),
                        marker=dict(size=8, color=t.series[i], line=dict(width=2, color=t.surface)),
                        hovertemplate=f"%{{y:.3f}}x<extra>{col}</extra>")
    threshold_line(fig, cov, f"DSCR covenant {cov:.2f}x", t.warning)
    threshold_line(fig, 1.0, "1.00x", t.critical, "bottom right")
    style(fig, 340)
    op_axis(fig, res)
    fig.update_yaxes(title_text="x", rangemode="tozero")
    return fig


def fig_profiles(dscr: pd.DataFrame, covenant: float) -> go.Figure:
    t = theme()
    fig = go.Figure()
    for i, col in enumerate(dscr.columns):
        series = dscr[col]
        fig.add_scatter(x=dscr.index, y=series, mode="lines+markers", name=col, line=dict(color=t.series[i], width=2),
                        marker=dict(size=8, color=t.series[i], line=dict(width=2, color=t.surface)),
                        hovertemplate=f"%{{y:.3f}}x<extra>{col}</extra>")
    threshold_line(fig, covenant, f"Covenant {covenant:.2f}x", t.warning)
    threshold_line(fig, 1.0, "1.00x", t.critical, "bottom right")
    style(fig, 360)
    fig.update_xaxes(title_text="Operating year", range=[0.4, dscr.index.max() + 0.6], dtick=1 if len(dscr) <= 20 else 2)
    fig.update_yaxes(title_text="DSCR (x)", rangemode="tozero")
    return fig


def fig_scenario_bars(table: pd.DataFrame, column: str, threshold: float, *, kind: str, covenant: float) -> go.Figure:
    t = theme()
    values = table[column].astype(float)
    labels = table["Scenario"]
    if kind == "dscr":
        colors = [status_color(v if np.isfinite(v) else None, covenant) for v in values]
        text = [f"{v:.2f}x {'✓' if meets(v, covenant) else ('!' if meets(v, 1.0) else '✕')}"
                if np.isfinite(v) else "n/a" for v in values]
        hover = "%{y}: %{x:.3f}x<extra></extra>"
    else:
        colors = [t.good if np.isfinite(v) and meets(v, threshold) else t.critical for v in values]
        text = [f"{v:.2%} {'✓' if meets(v, threshold) else '✕'}" if np.isfinite(v) else "n/a" for v in values]
        hover = "%{y}: %{x:.2%}<extra></extra>"
    fig = go.Figure(go.Bar(y=labels, x=values, orientation="h", marker_color=colors, text=text,
                           textposition="outside", textfont=dict(color=t.ink2), cliponaxis=False,
                           hovertemplate=hover))
    fig.update_layout(bargap=0.4)
    style(fig, 40 + 34 * len(table), legend=False, hover="closest")
    fig.update_yaxes(autorange="reversed", zeroline=False)
    if kind == "dscr":
        fig.add_vline(x=covenant, line=dict(color=t.warning, width=1, dash="dash"))
        fig.add_vline(x=1.0, line=dict(color=t.critical, width=1, dash="dash"))
        fig.update_xaxes(title_text="Minimum DSCR (x); dashed lines: covenant and 1.00x")
    else:
        fig.add_vline(x=threshold, line=dict(color=t.warning, width=1, dash="dash"))
        fig.update_xaxes(title_text=f"Equity IRR; dashed line: {threshold:.0%} hurdle", tickformat=".0%")
    finite = values[np.isfinite(values)]
    if len(finite):
        fig.update_xaxes(range=[min(0, float(finite.min()) * 1.1), float(finite.max()) * 1.22])
    return fig


def fig_tornado(df: pd.DataFrame, metric: str, shock: float) -> go.Figure:
    t = theme()
    is_irr = metric == "Equity IRR"
    low, high = f"Δ {metric} (low)", f"Δ {metric} (high)"
    span = (df[high].astype(float) - df[low].astype(float)).abs()
    d = df.assign(_span=span).sort_values("_span", ascending=True)
    fig = go.Figure()
    for i, (col, name) in enumerate(((low, f"Input -{shock:.0%}"), (high, f"Input +{shock:.0%}"))):
        vals = d[col].astype(float) * (100 if is_irr else 1)
        fig.add_bar(y=d["Variable"], x=vals, orientation="h", name=name, marker_color=t.series[i],
                    hovertemplate="%{y}: %{x:+.2f}" + (" pp" if is_irr else "x") + f"<extra>{name}</extra>")
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.05)  # grouped: same-sign moves stay visible
    style(fig, 60 + 32 * len(d), hover="closest")
    fig.update_xaxes(title_text=f"Change in {metric} vs this case ({'percentage points' if is_irr else 'x'})",
                     zeroline=True, zerolinecolor=t.ink2, zerolinewidth=1)
    fig.update_yaxes(zeroline=False)
    return fig


def fig_demand(res) -> go.Figure:
    t, rv = theme(), res.revenue
    d = op_frame(res, list(rv.drivers))
    fig = go.Figure()
    if res.inputs.project_type == "toll":
        mature, actual, label = "Mature traffic (PCU/day)", "Paying traffic (PCU/day)", "PCU/day"
    else:
        mature, actual, label = "Mature ridership (pax/day)", "Ridership carried (pax/day)", "passengers/day"
    fig.add_scatter(x=d.index, y=d[mature], mode="lines", name="Forecast at maturity (no ramp-up, no shortfall)",
                    line=dict(color=t.gray, width=2), hovertemplate="%{y:,.0f}<extra>Mature</extra>")
    fig.add_scatter(x=d.index, y=d[actual], mode="lines+markers", name="Modelled (ramp-up, shortfall, cap)",
                    line=dict(color=t.series[0], width=2),
                    marker=dict(size=8, color=t.series[0], line=dict(width=2, color=t.surface)),
                    hovertemplate="%{y:,.0f}<extra>Modelled</extra>")
    blk = res.inputs.revenue_block
    if getattr(blk, "capacity", None):
        threshold_line(fig, blk.capacity, f"Capacity {blk.capacity:,.0f}", t.warning)
    style(fig, 340)
    op_axis(fig, res)
    fig.update_yaxes(title_text=label, rangemode="tozero")
    return fig


def fig_price(res) -> go.Figure:
    t = theme()
    col = "Toll rate (₹/trip)" if res.inputs.project_type == "toll" else "Average fare (₹/trip)"
    d = op_frame(res, [col])
    fig = go.Figure(go.Scatter(x=d.index, y=d[col], mode="lines+markers", line=dict(color=t.series[0], width=2,
                                                                                  shape="hv" if res.inputs.project_type == "metro" else "linear"),
                               marker=dict(size=8, color=t.series[0], line=dict(width=2, color=t.surface)),
                               hovertemplate="₹%{y:,.2f}<extra></extra>"))
    style(fig, 300, legend=False, hover="x")
    op_axis(fig, res)
    fig.update_yaxes(title_text="₹ per trip", rangemode="tozero")
    return fig


def fig_revenue(res) -> go.Figure:
    t, rv = theme(), res.revenue
    d = op_frame(res, list(rv.lines))
    fig = go.Figure()
    for i, col in enumerate(rv.lines):
        fig.add_bar(x=d.index, y=d[col], name=col, marker_color=t.series[i], marker_line=dict(width=1, color=t.surface),
                    hovertemplate=f"%{{y:,.2f}}<extra>{col}</extra>")
    fig.update_layout(barmode="stack", bargap=0.5)  # keeps full-width bars near the 24px mark spec
    style(fig, 340, legend=len(rv.lines) > 1)
    op_axis(fig, res)
    fig.update_yaxes(title_text="₹ Cr")
    return fig


def fig_construction_support(res) -> go.Figure:
    t = theme()
    a = res.annual
    c = a[a["Phase"] == "Construction"]
    fig = go.Figure()
    fig.add_bar(x=c["Fiscal year"], y=c["Capex"], name="Actual capex", marker_color=t.series[0],
                hovertemplate="%{y:,.2f}<extra>Capex</extra>")
    fig.add_bar(x=c["Fiscal year"], y=c["Grant / construction support"], name="Construction support (40% of BPC x PIM)",
                marker_color=t.series[1], hovertemplate="%{y:,.2f}<extra>Support</extra>")
    fig.update_layout(barmode="group", bargap=0.45, bargroupgap=0.1)
    style(fig, 300)
    fig.update_yaxes(title_text="₹ Cr")
    return fig


def fig_equity_cf(res) -> go.Figure:
    t, a = theme(), res.annual
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.55, 0.45], vertical_spacing=0.1,
                        subplot_titles=("Equity cash flow by year (₹ Cr)", "Cumulative equity cash flow (₹ Cr)"))
    colors = [t.series[0] if v >= 0 else t.series[1] for v in a["Equity cash flow"]]
    fig.add_bar(x=a.index, y=a["Equity cash flow"], marker_color=colors, customdata=a["Fiscal year"],
                hovertemplate="%{customdata}: %{y:,.2f}<extra></extra>", showlegend=False, row=1, col=1)
    fig.add_scatter(x=a.index, y=a["Cumulative equity cash flow"], mode="lines+markers", showlegend=False,
                    line=dict(color=t.ink2, width=2), marker=dict(size=8, color=t.ink2, line=dict(width=2, color=t.surface)),
                    hovertemplate="%{y:,.2f}<extra>Cumulative</extra>", row=2, col=1)
    pb = res.metrics.payback
    if pb.status == "achieved":
        fig.add_vline(x=pb.model_year, line=dict(color=t.good, width=1, dash="dash"))
        fig.add_annotation(x=pb.model_year, y=0, yref="y2", text=f"Payback: year {pb.model_year}", showarrow=False,
                           xanchor="left", yanchor="bottom", font=dict(color=t.ink2, size=11))
    style(fig, 460, legend=False, hover="x")
    fig.update_xaxes(title_text="Model year", row=2, col=1)
    for ann in fig.layout.annotations[:2]:
        ann.update(font=dict(size=12, color=t.ink), x=0, xanchor="left")
    return fig


# =============================================================================================
# Page building blocks
# =============================================================================================


def header(title: str, ctx) -> None:
    ss = st.session_state
    st.title(title)
    label = SCENARIOS.scenarios[ss.scenario].label + (" (customised levers)" if levers_customised() else "")
    st.caption(f"{PROJECT_LABELS[ss.ptype]} · scenario: **{label}** · {ctx.res.inputs.project.name} · "
               "all money in ₹ crore")


def kpi(col, label: str, value: str, *, delta: str | None = None, delta_color: str = "normal",
        badge: tuple[str, str, str] | None = None, help: str | None = None) -> None:
    with col.container(border=True):
        st.metric(label, value, delta=delta, delta_color=delta_color, help=help)
        if badge:
            color, text, icon = badge
            st.badge(text, icon=icon, color=color)


def delta_of(value, base, fmt, show: bool) -> str | None:
    if not show or value is None or base is None:
        return None
    diff = value - base
    if abs(diff) < 1e-12:
        return None
    return fmt(diff)


def warnings_block(res) -> None:
    fails = [c for c in res.checks if c.status == "fail"]
    if fails:
        st.error(f"{len(fails)} integrity check(s) FAILED: the numbers below must not be relied on. "
                 "See the Validation page.", icon=":material/error:")
    for w in res.warnings:
        if w.startswith(("Debt-service shortfall", "Sponsor support", "Debt not fully repaid", "Loan maturity")):
            st.warning(w, icon=":material/warning:")
        else:
            st.info(w, icon=":material/info:")


# =============================================================================================
# Pages
# =============================================================================================


def page_overview() -> None:
    ctx = CTX
    res, base, mt = ctx.res, ctx.base_res.metrics, ctx.res.metrics
    header("Overview", ctx)
    cov, hurdle = res.inputs.covenants.min_dscr, res.inputs.valuation.equity_hurdle
    compare = ctx.is_stressed

    c = st.columns(5)
    kpi(c[0], "TPC (₹ Cr)", money(mt.total_project_cost),
        help="Total Project Cost = capex + IDC + fees (+ DSRA funded at COD)",
        delta=delta_of(mt.total_project_cost, base.total_project_cost, lambda d: f"{d:+,.2f} vs base", compare),
        delta_color="inverse")
    kpi(c[1], "Debt at COD (₹ Cr)", money(mt.debt),
        delta=delta_of(mt.debt, base.debt, lambda d: f"{d:+,.2f} vs base", compare), delta_color="inverse",
        help=res.sizing.message)
    kpi(c[2], "Equity (₹ Cr)", money(mt.equity),
        delta=delta_of(mt.equity, base.equity, lambda d: f"{d:+,.2f} vs base", compare), delta_color="inverse")
    kpi(c[3], "IDC, capitalised (₹ Cr)", money(mt.idc),
        delta=delta_of(mt.idc, base.idc, lambda d: f"{d:+,.2f} vs base", compare),
        delta_color="inverse", help="Interest during construction, funded by debt and equity")
    kpi(c[4], "Grant / support (₹ Cr)", money(mt.grant), help="VGF, or HAM construction support")

    c = st.columns(5)
    kpi(c[0], f"Min DSCR · op yr {mt.min_dscr_op_year}" if mt.min_dscr is not None else "Min DSCR",
        ratio(mt.min_dscr), badge=status_of_dscr(mt.min_dscr, cov), help="Lowest DSCR over the debt-service years",
        delta=delta_of(mt.min_dscr, base.min_dscr, lambda d: f"{d:+.2f}x vs base", compare))
    kpi(c[1], "Average DSCR", ratio(mt.avg_dscr), help="Over debt-service years only",
        delta=delta_of(mt.avg_dscr, base.avg_dscr, lambda d: f"{d:+.2f}x vs base", compare))
    llcr_ok = mt.llcr_cod is None or meets(mt.llcr_cod, res.inputs.covenants.min_llcr)
    kpi(c[2], "LLCR at COD", ratio(mt.llcr_cod),
        badge=("green" if llcr_ok else "orange",
               f"{'Meets' if llcr_ok else 'Below'} {res.inputs.covenants.min_llcr:.2f}x",
               ":material/check_circle:" if llcr_ok else ":material/warning:"),
        delta=delta_of(mt.llcr_cod, base.llcr_cod, lambda d: f"{d:+.2f}x vs base", compare))
    if mt.grant > 0:  # README §9.13: report both; after-grant is the SPV's own unlevered return
        support = "support" if res.inputs.project_type == "ham" else "grant"
        kpi(c[3], f"Post-{support} IRR", mt.project_irr_post_grant.display(),
            help=f"Project IRR after {support}: post-tax, unlevered, capex net of the {support}. Before {support}: "
                 f"{mt.project_irr.display()} (the project's return with no government money).",
            delta=delta_of(mt.project_irr_post_grant.value, base.project_irr_post_grant.value,
                           lambda d: f"{d * 100:+.2f} pp vs base", compare))
    else:
        kpi(c[3], "Project IRR", mt.project_irr.display(), help="Post-tax, unlevered (README §9.13)",
            delta=delta_of(mt.project_irr.value, base.project_irr.value, lambda d: f"{d * 100:+.2f} pp vs base",
                           compare))
    eq_ok = mt.equity_meets_hurdle
    kpi(c[4], "Equity IRR", mt.equity_irr.display(),
        badge=("green" if eq_ok else "red", f"{'Beats' if eq_ok else 'Below'} {hurdle:.0%} hurdle",
               ":material/check_circle:" if eq_ok else ":material/error:"),
        delta=delta_of(mt.equity_irr.value, base.equity_irr.value, lambda d: f"{d * 100:+.2f} pp vs base", compare))

    c = st.columns(5)
    kpi(c[0], f"NPV @ {res.inputs.valuation.discount_rate:.0%} (₹ Cr)", money(mt.project_npv),
        help="Project NPV: unlevered project cash flows valued at financial close",
        delta=delta_of(mt.project_npv, base.project_npv, lambda d: f"{d:+,.2f} vs base", compare))
    kpi(c[1], "Equity payback", f"Year {mt.payback.model_year}" if mt.payback.status == "achieved" else "Not achieved",
        help=mt.payback.display())
    repaid = mt.debt_fully_repaid
    kpi(c[2], "Debt repayment", f"Op year {mt.final_repayment_op_year}" if repaid and mt.final_repayment_op_year
        else ("No debt" if mt.debt == 0 else "Not repaid"),
        badge=("green", "Fully repaid", ":material/check_circle:") if repaid else
        ("red", f"{cr(mt.outstanding_at_end)} unpaid at concession end", ":material/error:"))
    kpi(c[3], "Tail", f"{mt.tail_years} years" if mt.tail_years is not None else "n/a",
        help="Operating years after the final repayment")
    n_fail = sum(x.status == "fail" for x in res.checks)
    n_warn = sum(x.status == "warn" for x in res.checks)
    if n_fail:
        validation_badge = ("red", "Integrity failure: see Validation", ":material/error:")
    elif n_warn:
        validation_badge = ("orange", f"{n_warn} financial warning(s)", ":material/warning:")
    else:
        validation_badge = ("green", "No financial warnings", ":material/fact_check:")
    kpi(c[4], "Model validation", "Pass" if n_fail == 0 else f"{n_fail} failed", badge=validation_badge,
        help="Integrity checks test the arithmetic; financial checks test covenants and the hurdle.")

    st.subheader("Concession timeline")
    show(fig_timeline(res), key="timeline")
    st.subheader("CFADS vs debt service, and DSCR")
    show(fig_cfads_dscr(res), op_frame(res, ["CFADS", "Debt service", "DSCR"]), key="cfads_dscr",
         caption="DSCR markers: green meets the covenant, amber is between 1.00x and the covenant, red is below 1.00x.")
    left, right = st.columns(2)
    with left:
        st.subheader("Debt outstanding")
        show(fig_debt_balance(res), res.annual[["Fiscal year", "Opening debt", "Closing debt"]], key="debt_bal")
    with right:
        st.subheader("Sources and uses of funds")
        fu = res.funding
        su = pd.DataFrame({"Uses": ["Capex", "IDC", "Upfront fees", "DSRA initial funding", "Total"],
                           "Uses ₹ Cr": [fu.capex_total, fu.idc_total, fu.fees_total, fu.dsra_initial,
                                        fu.total_project_cost],
                           "Sources": ["Debt", "Equity", "Grant / support", "", "Total"],
                           "Sources ₹ Cr": [fu.debt_at_cod, fu.equity_total, fu.grant_total, None,
                                           fu.debt_at_cod + fu.equity_total + fu.grant_total]})
        show(fig_sources_uses(res), su.set_index("Uses"), key="sources_uses")
    st.subheader("Warnings and notes")
    if res.warnings or not res.integrity_ok:
        warnings_block(res)
    else:
        st.success("No warnings: debt is repaid, DSCR stays above 1.00x and no sponsor support is needed.",
                   icon=":material/check_circle:")


PCT_KEYS = {
    "capex.escalation", "capex.contingency", "capex.preop", "funding.gearing", "funding.grant_pct",
    "funding.upfront_fee", "debt.interest_rate", "opex.om_escalation", "opex.concession_fee_pct",
    "opex.premium_escalation", "tax.rate", "valuation.discount_rate", "valuation.equity_hurdle",
    "revenue.toll.growth", "revenue.toll.rate_escalation", "revenue.toll.leakage", "revenue.metro.growth",
    "revenue.metro.fare_revision_pct", "revenue.metro.non_fare_pct", "revenue.ham.construction_support_pct",
    "revenue.ham.annuity_interest_rate", "revenue.ham.pim_inflation",
}


def _list_text(values, as_pct: bool) -> str:
    if values is None:
        return ""
    return ", ".join(f"{v * 100:g}" if as_pct else f"{v:g}" for v in values)


def _parse_list(text: str, as_pct: bool, integer: bool = False):
    text = text.strip()
    if not text:
        return []
    items = [x for x in text.replace(";", ",").split(",") if x.strip()]
    out = []
    for item in items:
        value = float(item)
        value = value / 100 if as_pct else value
        out.append(int(value) if integer else round(value, 10))
    return out


def page_assumptions() -> None:
    ctx = CTX
    ss = st.session_state
    ptype = ss.ptype
    header("Project assumptions", ctx)
    st.markdown("Edit the **base case** for this project type. Percentages are entered in %. Press **Validate and "
                "apply**: the inputs are checked first and the model re-runs only if they are valid. Scenario "
                "levers (shortfall, overrun, delay, rate shock) stay in the sidebar.")
    base = ss.base[ptype]
    p = f"a_{ptype}_"

    def num(container, path: str, label: str, *, step: float = 0.1, integer: bool = False, minv=None, maxv=None,
            help: str | None = None):
        value = base
        for part in path.split("."):
            value = value[part]
        if path in PCT_KEYS:
            return container.number_input(f"{label} (%)", value=float(value) * 100, step=step, format="%.4g",
                                          key=p + path, help=help, min_value=minv, max_value=maxv) / 100
        if integer:
            return int(container.number_input(label, value=int(value), step=1, key=p + path, help=help,
                                              min_value=minv, max_value=maxv))
        return container.number_input(label, value=float(value), step=step, key=p + path, help=help, format="%.4g",
                                      min_value=minv, max_value=maxv)

    def choice(container, path: str, label: str, options: list, help: str | None = None):
        value = base
        for part in path.split("."):
            value = value[part]
        return container.selectbox(label, options, index=options.index(value), key=p + path, help=help)

    def flag(container, path: str, label: str, help: str | None = None):
        value = base
        for part in path.split("."):
            value = value[part]
        return container.checkbox(label, value=bool(value), key=p + path, help=help)

    with st.form(f"assumptions_{ptype}", border=True):
        tabs = st.tabs(["Timeline & capital cost", "Funding & debt", "Revenue", "Operating costs & tax",
                        "Reserves, valuation & covenants"])
        new = json.loads(json.dumps(base))  # plain deep copy

        with tabs[0]:
            c1, c2, c3 = st.columns(3)
            new["timeline"]["construction_years"] = num(c1, "timeline.construction_years", "Construction period (years)",
                                                        integer=True, minv=1, maxv=10)
            new["timeline"]["concession_years"] = num(c2, "timeline.concession_years", "Concession period (years)",
                                                      integer=True, minv=2, maxv=99, help="From the appointed date")
            new["project"]["first_fiscal_year"] = num(c3, "project.first_fiscal_year", "First fiscal year (label)",
                                                      integer=True, minv=2000, maxv=2100)
            new["timeline"]["concession_end_fixed"] = flag(c1, "timeline.concession_end_fixed",
                                                           "Concession end fixed when construction is delayed")
            new["timeline"]["indexation_basis"] = choice(c2, "timeline.indexation_basis", "Indexation basis",
                                                         ["cod", "calendar"],
                                                         help="cod: escalation exponent k-1 (README). calendar: years "
                                                              "since the scheduled COD (a delay does not freeze growth).")
            c1, c2, c3 = st.columns(3)
            new["capex"]["base_cost"] = num(c1, "capex.base_cost", "Base hard cost, today's prices (₹ Cr)", step=10.0,
                                            minv=0.0)
            phasing_text = c2.text_input("Phasing by construction year (%)",
                                         value=_list_text(base["capex"]["phasing"], True), key=p + "capex.phasing",
                                         help="Comma-separated, one per construction year; must sum to 100")
            new["capex"]["escalation"] = num(c3, "capex.escalation", "Capex escalation p.a.")
            new["capex"]["contingency"] = num(c1, "capex.contingency", "Contingency (share of hard cost)")
            new["capex"]["preop"] = num(c2, "capex.preop", "Pre-operative expenses (share of hard cost)")

        with tabs[1]:
            c1, c2, c3 = st.columns(3)
            new["funding"]["gearing"] = num(c1, "funding.gearing", "Gearing: debt share", step=1.0, minv=0.0, maxv=99.0)
            new["funding"]["grant_pct"] = num(c2, "funding.grant_pct", "Grant / VGF (share of capex)", step=1.0)
            new["funding"]["equity_mode"] = choice(c3, "funding.equity_mode", "Equity drawdown",
                                                   ["pro_rata", "equity_first"])
            new["funding"]["grant_covers_overrun"] = flag(c1, "funding.grant_covers_overrun",
                                                          "Grant also covers cost overruns",
                                                          help="Off: VGF is fixed at award (default). On: the README "
                                                               "formula Grant = grant% x Capex taken literally.")
            new["funding"]["upfront_fee"] = num(c2, "funding.upfront_fee", "Upfront fee (share of debt)", step=0.05)
            new["funding"]["drawdown_timing"] = num(c3, "funding.drawdown_timing",
                                                    "Drawdown timing m (0.5 = mid-year)", step=0.05, minv=0.0, maxv=1.0)
            c1, c2, c3 = st.columns(3)
            new["debt"]["interest_rate"] = num(c1, "debt.interest_rate", "Interest rate (all-in)", step=0.05)
            new["debt"]["tenor_years"] = num(c2, "debt.tenor_years", "Repayment tenor (years)", integer=True, minv=1,
                                             maxv=40)
            new["debt"]["moratorium_years"] = num(c3, "debt.moratorium_years", "Moratorium after COD (years)",
                                                  integer=True, minv=0, maxv=10)
            new["debt"]["profile"] = choice(c1, "debt.profile", "Repayment profile",
                                            ["annuity", "equal", "structured", "sculpted"])
            structured_text = c2.text_input("Structured repayment % (one per tenor year)",
                                            value=_list_text(base["debt"]["structured_pct"], True),
                                            key=p + "debt.structured_pct", help="Used only for the structured profile")
            use_default = c3.checkbox("Replace with a default rising profile for this tenor",
                                      key=p + "debt.structured_default")
            new["debt"]["target_dscr"] = num(c1, "debt.target_dscr", "Target DSCR (sculpting / sizing)", step=0.05)
            new["debt"]["sizing"] = choice(c2, "debt.sizing", "Debt sizing", ["gearing", "gearing_and_dscr"],
                                           help="gearing_and_dscr: debt = min(gearing limit, DSCR limit)")
            new["debt"]["sculpt_negative_principal"] = choice(c3, "debt.sculpt_negative_principal",
                                                              "Sculpting: negative principal", ["floor", "capitalise"])

        with tabs[2]:
            c1, c2, c3 = st.columns(3)
            rev = new["revenue"][ptype]
            if ptype == "toll":
                rev["aadt"] = num(c1, "revenue.toll.aadt", "Traffic at COD, mature (PCU/day)", step=500.0, minv=0.0)
                rev["growth"] = num(c2, "revenue.toll.growth", "Traffic growth p.a.")
                rev["rate"] = num(c3, "revenue.toll.rate", "Toll rate at COD (₹ per PCU-trip)", step=5.0)
                rev["rate_escalation"] = num(c1, "revenue.toll.rate_escalation", "Toll escalation p.a.")
                ramp_text = c2.text_input("Ramp-up factors, op years 1, 2, ... (%)",
                                          value=_list_text(base["revenue"]["toll"]["ramp_up"], True),
                                          key=p + "revenue.toll.ramp_up", help="100% after the last value")
                rev["leakage"] = num(c3, "revenue.toll.leakage", "Leakage / exempt vehicles")
                cap = c1.number_input("Road capacity (PCU/day; 0 = no cap)", value=float(base["revenue"]["toll"]["capacity"] or 0),
                                      step=1000.0, key=p + "revenue.toll.capacity", min_value=0.0)
                rev["capacity"] = cap or None
            elif ptype == "metro":
                rev["ridership"] = num(c1, "revenue.metro.ridership", "Ridership at COD, mature (passengers/day)",
                                       step=5000.0, minv=0.0)
                rev["growth"] = num(c2, "revenue.metro.growth", "Ridership growth p.a.")
                rev["fare"] = num(c3, "revenue.metro.fare", "Average fare (₹ per trip)", step=1.0)
                rev["fare_revision_pct"] = num(c1, "revenue.metro.fare_revision_pct", "Fare revision", step=1.0)
                rev["fare_revision_every"] = num(c2, "revenue.metro.fare_revision_every", "Revise fares every (years)",
                                                 integer=True, minv=1, maxv=20)
                rev["non_fare_pct"] = num(c3, "revenue.metro.non_fare_pct", "Non-fare revenue (share of fare revenue)",
                                          step=1.0)
                ramp_text = c1.text_input("Ramp-up factors, op years 1, 2, ... (%)",
                                          value=_list_text(base["revenue"]["metro"]["ramp_up"], True),
                                          key=p + "revenue.metro.ramp_up")
                cap = c2.number_input("Line capacity (passengers/day; 0 = no cap)",
                                      value=float(base["revenue"]["metro"]["capacity"] or 0), step=10000.0,
                                      key=p + "revenue.metro.capacity", min_value=0.0)
                rev["capacity"] = cap or None
            else:
                ramp_text = None
                rev["bid_project_cost"] = num(c1, "revenue.ham.bid_project_cost", "Bid Project Cost (₹ Cr)", step=10.0)
                rev["construction_support_pct"] = num(c2, "revenue.ham.construction_support_pct",
                                                      "Construction support (share of BPC)", step=1.0)
                rev["annuity_interest_rate"] = num(c3, "revenue.ham.annuity_interest_rate",
                                                   "Interest on annuity balance p.a.", step=0.05)
                rev["annuity_instalments"] = num(c1, "revenue.ham.annuity_instalments", "Annuity instalments",
                                                 integer=True, minv=1, maxv=120)
                rev["instalments_per_year"] = choice(c2, "revenue.ham.instalments_per_year", "Instalments per year",
                                                     [1, 2, 4, 12])
                rev["om_payment"] = num(c3, "revenue.ham.om_payment", "O&M payment, op-year-1 prices (₹ Cr)")
                rev["pim_inflation"] = num(c1, "revenue.ham.pim_inflation", "Price Index Multiple inflation p.a.")
                st.caption("HAM revenue has no traffic input: the Authority pays annuities on the Bid Project Cost.")

        with tabs[3]:
            c1, c2, c3 = st.columns(3)
            new["opex"]["om_base"] = num(c1, "opex.om_base", "Routine O&M, op-year-1 prices (₹ Cr)")
            new["opex"]["om_escalation"] = num(c2, "opex.om_escalation", "O&M and MMR escalation p.a.")
            new["opex"]["mmr_base"] = num(c3, "opex.mmr_base", "Major maintenance, op-year-1 prices (₹ Cr)")
            mmr_text = c1.text_input("Major-maintenance operating years", value=_list_text(base["opex"]["mmr_years"], False),
                                     key=p + "opex.mmr_years")
            new["opex"]["concession_fee_pct"] = num(c2, "opex.concession_fee_pct", "Concession fee (share of revenue)")
            new["opex"]["concession_premium"] = num(c3, "opex.concession_premium", "Fixed premium, op-year-1 prices (₹ Cr)")
            new["opex"]["premium_escalation"] = num(c1, "opex.premium_escalation", "Premium escalation p.a.")
            c1, c2, c3 = st.columns(3)
            new["tax"]["rate"] = num(c1, "tax.rate", "Corporate tax rate", step=0.01)
            dep = c2.number_input("Depreciation life (years; 0 = operating period)",
                                  value=int(base["tax"]["depreciation_years"] or 0), step=1, min_value=0,
                                  key=p + "tax.depreciation_years")
            new["tax"]["depreciation_years"] = int(dep) or None
            lcf = c3.number_input("Loss carry-forward limit (years; 0 = unlimited)",
                                  value=int(base["tax"]["loss_carry_forward_years"] or 0), step=1, min_value=0,
                                  key=p + "tax.loss_carry_forward_years")
            new["tax"]["loss_carry_forward_years"] = int(lcf) or None
            new["tax"]["depreciation_net_of_grant"] = flag(c1, "tax.depreciation_net_of_grant",
                                                           "Depreciate net of grant")

        with tabs[4]:
            c1, c2, c3 = st.columns(3)
            new["reserves"]["dsra_months"] = num(c1, "reserves.dsra_months", "DSRA size (months of debt service)",
                                                 step=1.0, minv=0.0, maxv=24.0)
            new["reserves"]["dsra_initial_funding"] = choice(c2, "reserves.dsra_initial_funding", "DSRA funded from",
                                                             ["cash_flow", "construction"])
            lock = c3.number_input("Dividend lock-up DSCR (0 = off)", value=float(base["reserves"]["lockup_dscr"] or 0),
                                   step=0.05, min_value=0.0, key=p + "reserves.lockup_dscr")
            new["reserves"]["lockup_dscr"] = lock or None
            new["reserves"]["mmra_enabled"] = flag(c1, "reserves.mmra_enabled", "Major-maintenance reserve (MMRA)")
            new["reserves"]["mmra_position"] = choice(c2, "reserves.mmra_position", "MMRA position in the waterfall",
                                                      ["after_debt_service", "in_cfads"])
            c1, c2, c3 = st.columns(3)
            new["valuation"]["discount_rate"] = num(c1, "valuation.discount_rate", "Project discount rate (NPV)")
            new["valuation"]["equity_hurdle"] = num(c2, "valuation.equity_hurdle", "Equity hurdle rate")
            new["valuation"]["terminal_value"] = num(c3, "valuation.terminal_value", "Terminal value at handback (₹ Cr)")
            new["covenants"]["min_dscr"] = num(c1, "covenants.min_dscr", "Lender covenant: minimum DSCR (x)", step=0.05)
            new["covenants"]["min_llcr"] = num(c2, "covenants.min_llcr", "Lender covenant: minimum LLCR (x)", step=0.05)

        submitted = st.form_submit_button("Validate and apply", type="primary", icon=":material/check:")

    if submitted:
        errors = []
        try:
            new["capex"]["phasing"] = _parse_list(phasing_text, True)
            new["debt"]["structured_pct"] = (list(default_structured_pct(new["debt"]["tenor_years"])) if use_default
                                             else _parse_list(structured_text, True))
            new["opex"]["mmr_years"] = _parse_list(mmr_text, False, integer=True)
            if ramp_text is not None:
                new["revenue"][ptype]["ramp_up"] = _parse_list(ramp_text, True)
        except ValueError as exc:
            errors.append(f"Could not read a list of numbers: {exc}")
        if not errors:
            try:
                build_inputs(new)  # full validation before anything is applied
            except InputValidationError as exc:
                errors = exc.errors
        if errors:
            st.error("Not applied. Fix these inputs:\n\n" + "\n".join(f"- {e}" for e in errors), icon=":material/error:")
        else:
            ss.base[ptype] = new
            if use_default:
                ss.pop(p + "debt.structured_pct", None)
                ss.pop(p + "debt.structured_default", None)
            st.toast("Assumptions validated and applied", icon=":material/check_circle:")
            st.rerun()

    c1, c2 = st.columns([1, 3])
    if c1.button("Reset to config file", icon=":material/restart_alt:"):
        for k in [k for k in ss.keys() if str(k).startswith(p)]:
            del ss[k]
        ss.base[ptype] = load_yaml(base_config_path(ptype))
        st.rerun()
    with st.expander("Current base assumptions (YAML)", icon=":material/description:"):
        st.code(yaml.safe_dump(ss.base[ptype], sort_keys=False, allow_unicode=True), language="yaml")


STATEMENTS = {
    "Construction": ["Capex"],
    "Funding": ["Funding & IDC"],
    "Revenue & expenditure": ["Revenue", "Opex & EBITDA"],
    "Tax": ["Tax"],
    "CFADS": ["CFADS"],
    "Debt schedule": ["Debt schedule"],
    "DSCR & cover ratios": ["Cover ratios"],
    "Cash-flow waterfall": ["Waterfall"],
    "Equity cash flows": ["Returns"],
}


def column_config(columns) -> dict:
    cfg = {}
    for col in columns:
        if col in {"DSCR", "LLCR", "PLCR", "ICR"}:
            cfg[col] = st.column_config.NumberColumn(col, format="%.3fx")
        elif col in {"Phasing", "Ramp-up factor", "Support milestone share"}:
            cfg[col] = st.column_config.NumberColumn(col, format="percent")
        elif col in {"Escalation factor", "Price Index Multiple"}:
            cfg[col] = st.column_config.NumberColumn(col, format="%.4f")
        elif "/day" in col:
            cfg[col] = st.column_config.NumberColumn(col, format="%.0f")
        elif col in {"Op year", "Construction flag", "Operation flag", "Moratorium flag", "Repayment flag",
                     "Capacity cap binding (1=yes)"}:
            cfg[col] = st.column_config.NumberColumn(col, format="%d")
        elif col not in {"Fiscal year", "Phase"}:
            cfg[col] = st.column_config.NumberColumn(col, format="%.2f")
    return cfg


def page_statements() -> None:
    ctx = CTX
    res = ctx.res
    header("Annual financial statements", ctx)
    st.markdown("Complete annual schedules from the model (₹ crore unless the column says otherwise). Every column "
                "is also in the Excel export.")
    transpose = st.toggle("Show years as columns (model layout)", value=False)
    groups = res.schedule_columns()
    a = res.annual
    tabs = st.tabs(list(STATEMENTS) + ["All columns"])
    for tab, (name, keys) in zip(tabs, list(STATEMENTS.items()) + [("All columns", None)]):
        with tab:
            if keys is None:
                cols = [c for c in a.columns if c not in {"Fiscal year", "Phase", "Op year"}]
            else:
                cols = []
                for k in keys:
                    cols += [c for c in groups[k] if c not in cols and c not in {"Fiscal year", "Phase", "Op year"}]
            frame = a[["Fiscal year", "Phase", "Op year", *cols]]
            if name in {"Construction", "Funding"}:
                frame = frame[frame["Phase"] == "Construction"]
            if transpose:
                st.dataframe(frame.drop(columns="Phase").set_index("Fiscal year").round(4).T, width="stretch",
                             height=min(40 + 35 * len(cols), 760))
            else:
                st.dataframe(frame, width="stretch", height=min(40 + 35 * len(frame), 760),
                             column_config=column_config(frame.columns))
            if name == "Equity cash flows":
                show(fig_equity_cf(res), key="equity_cf")
            if name == "Funding":
                fu = res.funding
                st.caption(f"Sources − uses, largest gap: {np.max(np.abs(fu.sources - fu.uses)):.2e} ₹ Cr. "
                           f"IDC closed form vs iteration, largest gap: {np.max(np.abs(fu.idc - fu.idc_iterative)):.2e}.")


def page_debt() -> None:
    ctx = CTX
    res = ctx.res
    mt, tl, db = res.metrics, res.timeline, res.debt
    header("Debt analysis", ctx)
    c = st.columns(6)
    kpi(c[0], "Debt at COD (₹ Cr)", money(mt.debt), help=res.sizing.message)
    kpi(c[1], "Repayment profile", f"{db.profile.title()}",
        help=f"Tenor {tl.tenor_years} years after a {tl.moratorium_years}-year moratorium; "
             f"rate {res.inputs.interest_rate:.2%}")
    kpi(c[2], "Minimum DSCR", ratio(mt.min_dscr, 3), badge=status_of_dscr(mt.min_dscr, res.inputs.covenants.min_dscr))
    kpi(c[3], "LLCR at COD", ratio(mt.llcr_cod), help="PV of CFADS over the loan life (at r) / debt outstanding")
    kpi(c[4], "PLCR at COD", ratio(mt.plcr_cod), help="PV of CFADS over the remaining concession, including the tail")
    kpi(c[5], "Minimum ICR", ratio(mt.min_icr), help="CFADS / interest")
    st.info(res.sizing.message, icon=":material/straighten:")
    if db.floored_years:
        st.warning(next(w for w in db.warnings if "floored" in w), icon=":material/warning:")

    left, right = st.columns(2)
    with left:
        st.subheader("Opening and closing debt")
        show(fig_debt_balance(res), op_frame(res, ["Opening debt", "Closing debt"]), key="debt_balance_2")
    with right:
        st.subheader("Debt service: interest and principal")
        show(fig_debt_service(res), op_frame(res, ["Opening debt", "Interest paid", "Principal", "Debt service",
                                                   "Closing debt"]), key="ds_split")
    left, right = st.columns(2)
    with left:
        st.subheader("CFADS vs debt service, and DSCR")
        show(fig_cfads_dscr(res), op_frame(res, ["CFADS", "Debt service", "DSCR"]), key="cfads_dscr_2")
    with right:
        st.subheader("DSCR, LLCR and PLCR by year")
        show(fig_cover_ratios(res), op_frame(res, ["DSCR", "LLCR", "PLCR", "ICR"]), key="cover")

    st.subheader("Repayment profile comparison")
    st.caption("Same project and debt amount, four repayment shapes (README §11.4). Front-loaded repayment squeezes "
               "the ramp-up years; sculpting follows CFADS.")
    table, dscr = profiles_cached(ctx.key)
    cov = res.inputs.covenants.min_dscr
    left, right = st.columns([3, 2])
    with left:
        show(fig_profiles(dscr, cov), dscr, key="profiles")
    with right:
        table = table[["Min DSCR", "Equity IRR", "Min DSCR op year", "Avg DSCR", "LLCR at COD", "Debt fully repaid?",
                       "Note"]]
        styled = (table.style.format({"Min DSCR": "{:.3f}x", "Avg DSCR": "{:.3f}x", "LLCR at COD": "{:.3f}x",
                                      "Equity IRR": "{:.2%}", "Min DSCR op year": "{:.0f}"}, na_rep="n/a")
                  .map(dscr_cell_style(cov), subset=["Min DSCR"])
                  .map(irr_cell_style(res.inputs.valuation.equity_hurdle), subset=["Equity IRR"]))
        st.dataframe(styled, width="stretch")


def page_scenarios() -> None:
    ctx = CTX
    res, ptype = ctx.res, st.session_state.ptype
    header("Scenario analysis", ctx)
    cov, hurdle = res.inputs.covenants.min_dscr, res.inputs.valuation.equity_hurdle
    table = scenarios_cached(ctx.base_key)
    if ptype == "ham":
        st.info("HAM: the Authority pays annuities on the Bid Project Cost, so the traffic-shortfall and ramp-up "
                "scenarios leave revenue, DSCR and returns exactly unchanged. Cost overrun and interest rate still "
                "bite.", icon=":material/info:")

    st.subheader("Scenario summary")
    st.caption("Every scenario starts from a fresh copy of the base assumptions on the Assumptions page "
               "(config/scenarios.yaml overrides). Min DSCR: red below 1.00x, amber below the covenant.")
    show_cols = ["Scenario", "TPC", "Debt", "Equity", "IDC", "Min DSCR", "Min DSCR op year", "Avg DSCR", "LLCR at COD",
                 "Project IRR", "Project IRR (post-grant)", "Equity IRR", "NPV", "Debt fully repaid?",
                 "Any DSCR < 1.0?", "Equity IRR >= hurdle?", "Verdict"]
    if not (table["Project IRR"] - table["Project IRR (post-grant)"]).abs().gt(1e-12).any():
        show_cols.remove("Project IRR (post-grant)")  # no grant: the two are identical
    styled = (table[show_cols].style
              .format({"TPC": "{:,.2f}", "Debt": "{:,.2f}", "Equity": "{:,.2f}", "IDC": "{:,.2f}", "NPV": "{:,.2f}",
                       "Min DSCR": "{:.2f}x", "Avg DSCR": "{:.2f}x", "LLCR at COD": "{:.2f}x", "Min DSCR op year": "{:.0f}",
                       "Project IRR": "{:.2%}", "Project IRR (post-grant)": "{:.2%}", "Equity IRR": "{:.2%}"},
                      na_rep="n/a")
              .map(dscr_cell_style(cov), subset=["Min DSCR"])
              .map(irr_cell_style(hurdle), subset=["Equity IRR"]))
    st.dataframe(styled, width="stretch", hide_index=True, height=38 + 35 * len(table))  # every row visible

    st.subheader("Selected case vs base case")
    base_mt, mt = ctx.base_res.metrics, res.metrics
    rows = [
        ("Total Project Cost (₹ Cr)", base_mt.total_project_cost, mt.total_project_cost, "{:,.2f}"),
        ("Debt (₹ Cr)", base_mt.debt, mt.debt, "{:,.2f}"),
        ("Equity (₹ Cr)", base_mt.equity, mt.equity, "{:,.2f}"),
        ("IDC (₹ Cr)", base_mt.idc, mt.idc, "{:,.2f}"),
        ("Minimum DSCR", base_mt.min_dscr, mt.min_dscr, "{:.3f}x"),
        ("Average DSCR", base_mt.avg_dscr, mt.avg_dscr, "{:.3f}x"),
        ("LLCR at COD", base_mt.llcr_cod, mt.llcr_cod, "{:.3f}x"),
        ("Project IRR", base_mt.project_irr.value, mt.project_irr.value, "{:.2%}"),
        ("Equity IRR", base_mt.equity_irr.value, mt.equity_irr.value, "{:.2%}"),
        ("Project NPV (₹ Cr)", base_mt.project_npv, mt.project_npv, "{:,.2f}"),
        ("Sponsor support (₹ Cr)", base_mt.sponsor_support, mt.sponsor_support, "{:,.2f}"),
    ]
    comp = pd.DataFrame([{"Metric": m, "Base case": fmt.format(b) if b is not None else "n/a",
                          "Selected case": fmt.format(s) if s is not None else "n/a",
                          "Change": (fmt.replace("{:", "{:+").format(s - b) if b is not None and s is not None else "n/a")}
                         for m, b, s, fmt in rows])
    st.dataframe(comp, width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Minimum DSCR by scenario")
        show(fig_scenario_bars(table, "Min DSCR", cov, kind="dscr", covenant=cov),
             table[["Scenario", "Min DSCR", "Min DSCR op year"]], key="sc_dscr",
             caption="✓ meets covenant · ! between 1.00x and covenant · ✕ below 1.00x (payment default)")
    with right:
        st.subheader("Equity IRR by scenario")
        show(fig_scenario_bars(table, "Equity IRR", hurdle, kind="irr", covenant=cov),
             table[["Scenario", "Equity IRR", "Equity IRR >= hurdle?"]], key="sc_irr",
             caption=f"✓ at or above the {hurdle:.0%} hurdle · ✕ below")

    st.subheader("Two-way sensitivity: traffic shortfall × cost overrun")
    st.caption("Computed around the case selected in the sidebar (other levers held). Rows: traffic shortfall; "
               "columns: cost overrun.")
    metric = st.segmented_control("Show", ["Minimum DSCR", "Equity IRR"], default="Minimum DSCR", required=True,
                                  key="two_way_metric")
    grid = two_way_cached(ctx.key, "min_dscr" if metric == "Minimum DSCR" else "equity_irr")
    grid_display = grid.copy()
    grid_display.index = [f"{s:.0%} shortfall" for s in grid.index]
    grid_display.columns = [f"+{o:.0%} cost" for o in grid.columns]
    if metric == "Minimum DSCR":
        styled = grid_display.style.format("{:.2f}x", na_rep="n/a").map(dscr_cell_style(cov))
    else:
        styled = grid_display.style.format("{:.2%}", na_rep="n/a").map(irr_cell_style(hurdle))
    st.dataframe(styled, width="stretch")

    st.subheader(f"Tornado: each input moved ±{SCENARIOS.tornado_shock:.0%}")
    torn, attrs = tornado_cached(ctx.key, ptype)
    left, right = st.columns(2)
    with left:
        show(fig_tornado(torn, "Equity IRR", SCENARIOS.tornado_shock), key="tornado_irr",
             caption=f"Base Equity IRR for this case: {pct(attrs.get('base_equity_irr'))}. Largest range at the top.")
    with right:
        show(fig_tornado(torn, "Min DSCR", SCENARIOS.tornado_shock), key="tornado_dscr",
             caption=f"Base minimum DSCR for this case: {ratio(attrs.get('base_min_dscr'), 3)}.")
    with st.expander("Tornado data table", icon=":material/table:"):
        st.dataframe(torn.drop(columns=["Path"]), width="stretch", hide_index=True)

    st.subheader("Break-even traffic shortfall")
    be_dscr = break_even_cached(ctx.key, "min_dscr", 1.0)
    be_irr = break_even_cached(ctx.key, "equity_irr", hurdle)
    c = st.columns(2)
    for col, be, label in ((c[0], be_dscr, "Shortfall at which minimum DSCR = 1.00x"),
                           (c[1], be_irr, f"Shortfall at which Equity IRR = {hurdle:.0%} hurdle")):
        value = f"{be.value:.2%}" if be.status == "found" else {"not_applicable": "Not applicable",
                                                                 "not_reached": "Not reached",
                                                                 "already_breached": "Already breached"}[be.status]
        badge = {"found": ("blue", "Solution found", ":material/check:"),
                 "not_reached": ("green", f"Holds up to {SCENARIOS.break_even_max_shortfall:.0%} shortfall",
                                 ":material/shield:"),
                 "already_breached": ("red", "Below threshold with no shortfall", ":material/error:"),
                 "not_applicable": ("gray", "Revenue does not depend on traffic", ":material/block:")}[be.status]
        kpi(col, label, value, badge=badge, help=be.message)
    if be_dscr.status == "found" and be_dscr.binding_op_year:
        st.caption(f"The binding year at break-even is op year {be_dscr.binding_op_year}. Search: coarse scan then "
                   "bisection on the shortfall, so infeasible and not-reached cases are reported, not invented.")
    if ptype == "ham":
        demo, diff = ham_demo_cached(ctx.base_key)
        st.markdown(f"**HAM traffic-shortfall demonstration** (largest annual revenue difference: {diff:.2e} ₹ Cr)")
        st.dataframe(demo.style.format({"Total revenue": "{:,.2f}", "Min DSCR": "{:.3f}x", "LLCR at COD": "{:.3f}x",
                                        "Equity IRR": "{:.2%}"}), width="stretch")


def page_revenue() -> None:
    ctx = CTX
    res, ptype = ctx.res, st.session_state.ptype
    header("Revenue analysis", ctx)
    for note in res.revenue.notes:
        st.info(note, icon=":material/info:")
    if ptype in ("toll", "metro"):
        left, right = st.columns(2)
        with left:
            st.subheader("Traffic growth and ramp-up" if ptype == "toll" else "Ridership growth and ramp-up")
            show(fig_demand(res), op_frame(res, list(res.revenue.drivers)), key="demand",
                 caption="Gray: forecast at maturity. Blue: what the model uses after ramp-up, shortfall, leakage "
                         "and any capacity cap.")
        with right:
            st.subheader("Toll rate escalation" if ptype == "toll" else "Fare revisions")
            col = "Toll rate (₹/trip)" if ptype == "toll" else "Average fare (₹/trip)"
            show(fig_price(res), op_frame(res, [col]), key="price")
        st.subheader("Revenue build-up")
        show(fig_revenue(res), op_frame(res, [*res.revenue.lines, "Total revenue"]), key="rev")
    else:
        left, right = st.columns(2)
        with left:
            st.subheader("Authority payments by year")
            show(fig_revenue(res), op_frame(res, [*res.revenue.lines, "Total revenue"]), key="ham_rev",
                 caption="Semi-annual instalments are summed into the annual period in which they fall.")
        with right:
            st.subheader("Construction support vs capex")
            show(fig_construction_support(res), res.annual[res.annual["Phase"] == "Construction"][
                ["Fiscal year", "Capex", "Grant / construction support"]], key="ham_support",
                 caption="Support is 40% of the Bid Project Cost indexed by PIM, not of actual cost: an overrun is "
                         "not compensated.")
        st.subheader("Semi-annual annuity schedule")
        st.dataframe(res.revenue.semiannual, width="stretch", hide_index=True,
                     column_config={c: st.column_config.NumberColumn(c, format="%.4f") for c in
                                    ("Opening balance", "Annuity principal", "Annuity interest", "Total annuity",
                                     "Closing balance")})
    st.subheader("Does a 20% traffic shortfall change revenue?")
    base_total = float(ctx.base_res.revenue.total.sum())
    stressed = run_cached(key_of(deep_merge(st.session_state.base[ptype], {"stress": {"demand_shortfall": 0.20}})))
    stressed_total = float(stressed.revenue.total.sum())
    c = st.columns(3)
    kpi(c[0], "Total revenue, base (₹ Cr)", f"{base_total:,.2f}")
    kpi(c[1], "Total revenue, traffic -20% (₹ Cr)", f"{stressed_total:,.2f}",
        delta=f"{stressed_total - base_total:+,.2f}" if abs(stressed_total - base_total) > 1e-9 else None,
        delta_color="normal")
    kpi(c[2], "Revenue change", f"{(stressed_total / base_total - 1):+.2%}" if base_total else "n/a",
        badge=("gray", "No traffic risk: HAM", ":material/block:") if ptype == "ham" else
        ("orange", "SPV bears traffic risk", ":material/warning:"))


def page_validation() -> None:
    ctx = CTX
    res = ctx.res
    header("Validation", ctx)
    integrity = [c for c in res.checks if c.category == "integrity"]
    financial = [c for c in res.checks if c.category == "financial"]
    n_fail = sum(c.status == "fail" for c in integrity)
    n_warn = sum(c.status == "warn" for c in financial)
    c = st.columns(3)
    kpi(c[0], "Integrity checks", f"{sum(c.status == 'pass' for c in integrity)} pass / {n_fail} fail",
        badge=("green", "Arithmetic verified", ":material/verified:") if n_fail == 0 else
        ("red", "Do not rely on these numbers", ":material/error:"))
    kpi(c[1], "Financial checks", f"{len(financial) - n_warn} pass / {n_warn} warn",
        badge=("green", "No covenant issues", ":material/check_circle:") if n_warn == 0 else
        ("orange", "Lender or sponsor thresholds breached", ":material/warning:"))
    rows = hand_check(res)
    n_ok = sum(r.ok for r in rows)
    kpi(c[2], "Hand check (README §12.3)", f"{n_ok} of {len(rows)} agree",
        badge=("green", "All within 0.01", ":material/check_circle:") if n_ok == len(rows) else
        ("red", "Differences above 0.01", ":material/error:"))

    left, right = st.columns(2)
    with left:
        st.subheader("Integrity checks")
        for chk in integrity:
            text = f"**{chk.id} · {chk.name}**  \n{chk.detail}"
            if chk.status == "pass":
                st.success(text, icon=":material/check_circle:")
            elif chk.status == "fail":
                st.error(text, icon=":material/error:")
            else:
                st.info(text, icon=":material/info:")
    with right:
        st.subheader("Financial checks")
        for chk in financial:
            text = f"**{chk.id} · {chk.name}**  \n{chk.detail}"
            (st.success if chk.status == "pass" else st.warning)(
                text, icon=":material/check_circle:" if chk.status == "pass" else ":material/warning:")
        st.subheader("Model warnings")
        if res.warnings:
            for w in res.warnings:
                st.info(w, icon=":material/info:")
        else:
            st.caption("None.")

    fu, db = res.funding, res.debt
    tc = res.timeline.construction_years
    st.subheader("Sources vs uses and IDC cross-check (construction years)")
    su = pd.DataFrame({
        "Fiscal year": res.timeline.labels[:tc], "Capex": fu.capex[:tc], "Fees": fu.fees[:tc], "IDC (closed form)": fu.idc[:tc],
        "IDC (iteration)": fu.idc_iterative[:tc], "IDC difference": fu.idc[:tc] - fu.idc_iterative[:tc],
        "DSRA": fu.dsra_funding[:tc], "Total uses": fu.uses[:tc], "Grant": fu.grant[:tc], "Debt": fu.debt_draw[:tc],
        "Equity": fu.equity[:tc], "Total sources": fu.sources[:tc], "Sources - uses": fu.sources[:tc] - fu.uses[:tc],
    })
    st.dataframe(su, width="stretch", hide_index=True,
                 column_config={c: st.column_config.NumberColumn(c, format="%.6f") for c in su.columns[1:]})
    ratio_now = fu.debt_at_cod / max(fu.total_project_cost - fu.grant_total - fu.equity_only_total, 1e-12)
    st.caption(f"Gearing check: debt / (TPC − grant − equity-funded overrun) = {ratio_now:.6f} vs gearing applied "
               f"{fu.gearing:.6f}. Debt repayment: Σ principal {db.principal.sum():,.4f} + outstanding "
               f"{db.outstanding_at_end:,.4f} = debt at COD {db.amount:,.4f}.")

    st.subheader("IRR and NPV checks")
    irr_rows = []
    for name, result, cf in (("Project IRR", res.metrics.project_irr, res.project_cf),
                             ("Project IRR after grant", res.metrics.project_irr_post_grant, res.project_cf_post_grant),
                             ("Equity IRR", res.metrics.equity_irr, res.equity_cf)):
        irr_rows.append({"Return": name, "Own solver": result.display(4),
                         "numpy-financial": "n/a" if result.numpy_financial is None else f"{result.numpy_financial:.4%}",
                         "NPV at IRR (₹ Cr)": "n/a" if result.npv_at_irr is None else f"{result.npv_at_irr:.2e}",
                         "Status": result.status, "Note": result.message})
    st.dataframe(pd.DataFrame(irr_rows), width="stretch", hide_index=True)

    st.subheader("Hand check (README §12.3)")
    st.caption("Recomputed from the inputs with calculator-style formulas, independently of the vectorised model; "
               "'(model value)' marks a figure the README procedure allows to be taken from the model.")
    hc = hand_check_df(rows)
    st.dataframe(hc.style.format({"Hand value": "{:,.4f}", "Model value": "{:,.4f}", "Difference": "{:+.2e}"})
                 .map(lambda v: f"background-color: {TINT['green'] if v == 'OK' else TINT['red']}",
                      subset=["OK? (< 0.01)"]), width="stretch", hide_index=True)

    st.subheader("Automated test suite")
    st.caption("Runs `pytest` on the whole engine (worked example, degenerate cases, scenarios, checks).")
    if st.button("Run tests", icon=":material/play_arrow:"):
        with st.spinner("Running pytest…"):
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=600)
        st.session_state.pytest_output = (proc.returncode, proc.stdout[-6000:] + proc.stderr[-2000:])
    if "pytest_output" in st.session_state:
        code, out = st.session_state.pytest_output
        (st.success if code == 0 else st.error)("All tests passed." if code == 0 else "Some tests failed.",
                                                icon=":material/check_circle:" if code == 0 else ":material/error:")
        st.code(out.strip().splitlines()[-1] if code == 0 and out.strip() else out, language="text")


def page_export() -> None:
    ctx = CTX
    res, ptype = ctx.res, st.session_state.ptype
    header("Export", ctx)
    scenario = SCENARIOS.scenarios[st.session_state.scenario]
    label = scenario.label + (" (customised)" if levers_customised() else "")
    stem = f"ppp_{ptype}_{st.session_state.scenario}"
    c = st.columns(2)
    with c[0].container(border=True):
        st.markdown("**Complete financial model (Excel)**")
        st.caption("Summary, assumptions, timeline, capex, funding & IDC, revenue, O&M & tax, debt, CFADS & "
                   "waterfall, metrics, scenarios, sensitivity, checks and hand check. Values from the engine; no "
                   "formulas or macros.")
        st.download_button("Download workbook (.xlsx)", workbook_cached(ctx.key, ctx.base_key, label, ptype),
                           file_name=f"{stem}.xlsx", icon=":material/download:", type="primary",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with c[1].container(border=True):
        st.markdown("**Scenario comparison (CSV)**")
        st.caption("One row per scenario (README §10.2), run on the base assumptions.")
        st.download_button("Download scenarios (.csv)", scenarios_cached(ctx.base_key).to_csv().encode("utf-8"),
                           file_name=f"ppp_{ptype}_scenarios.csv", mime="text/csv", icon=":material/download:")
    c = st.columns(2)
    with c[0].container(border=True):
        st.markdown("**Assumptions (YAML)**")
        st.caption("The exact inputs of the case on screen (base + scenario + levers). Load it with "
                   "`ppp_model.load_inputs()`.")
        text = yaml.safe_dump(inputs_to_dict(res.inputs), sort_keys=False, allow_unicode=True)
        st.download_button("Download assumptions (.yaml)", text.encode("utf-8"), file_name=f"{stem}_inputs.yaml",
                           mime="application/x-yaml", icon=":material/download:")
    with c[1].container(border=True):
        st.markdown("**Validation results (CSV)**")
        st.caption("All integrity and financial checks plus the hand check.")
        checks = pd.DataFrame([{"Type": "check", "ID": x.id, "Name": x.name, "Category": x.category,
                                "Status": x.status.upper(), "Detail": x.detail} for x in res.checks])
        hc = hand_check_df(hand_check(res)).assign(Type="hand check")
        st.download_button("Download validation (.csv)", pd.concat([checks, hc], ignore_index=True).to_csv(
            index=False).encode("utf-8"), file_name=f"{stem}_validation.csv", mime="text/csv", icon=":material/download:")
    with st.container(border=True):
        st.markdown("**Annual schedules (CSV)**")
        st.download_button("Download annual table (.csv)", res.annual.to_csv().encode("utf-8"),
                           file_name=f"{stem}_annual.csv", mime="text/csv", icon=":material/download:")


# =============================================================================================
# App shell: navigation, sidebar levers, one model run per input set
# =============================================================================================

init_state()
pages = [
    st.Page(page_overview, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
    st.Page(page_assumptions, title="Project assumptions", icon=":material/tune:", url_path="assumptions"),
    st.Page(page_statements, title="Financial statements", icon=":material/table_view:", url_path="statements"),
    st.Page(page_debt, title="Debt analysis", icon=":material/account_balance:", url_path="debt"),
    st.Page(page_scenarios, title="Scenario analysis", icon=":material/query_stats:", url_path="scenarios"),
    st.Page(page_revenue, title="Revenue analysis", icon=":material/trending_up:", url_path="revenue"),
    st.Page(page_validation, title="Validation", icon=":material/fact_check:", url_path="validation"),
    st.Page(page_export, title="Export", icon=":material/download:", url_path="export"),
]
navigation = st.navigation(pages)

with st.sidebar:
    st.selectbox("Project type", list(PROJECT_LABELS), format_func=PROJECT_LABELS.get, key="ptype",
                 on_change=on_type_change)
    st.selectbox("Scenario", list(SCENARIOS.scenarios), format_func=lambda k: SCENARIOS.scenarios[k].label,
                 key="scenario", on_change=apply_scenario_levers)
    st.caption(SCENARIOS.scenarios[st.session_state.scenario].description)
    st.markdown("**Stress levers**")
    is_ham = st.session_state.ptype == "ham"
    st.slider("Traffic / ridership shortfall", 0, 60, step=1, format="%d%%", key="lever_demand_shortfall",
              help="HAM revenue is paid by the Authority: this lever has no effect on HAM (README §3.3)."
              if is_ham else "Cuts traffic (toll) or ridership (metro) below forecast")
    st.slider("Cost overrun", 0, 50, step=1, format="%d%%", key="lever_cost_overrun", help="On hard cost")
    st.segmented_control("Overrun funded by", ["pro_rata", "equity"], key="lever_overrun_funding", required=True,
                         format_func={"pro_rata": "Debt + equity", "equity": "Equity only"}.get)
    st.slider("Construction delay", 0, 3, step=1, format="%d yr", key="lever_delay_years",
              help="Concession end stays fixed for toll and metro, so operations shrink")
    st.slider("Interest-rate shock", -200, 300, step=25, format="%+d bp", key="lever_rate_shock")
    st.button("Reset levers to scenario", on_click=apply_scenario_levers, icon=":material/restart_alt:",
              width="stretch")

raw_now = effective_raw()
CTX = SimpleNamespace(key=key_of(raw_now), base_key=key_of(st.session_state.base[st.session_state.ptype]))
try:
    CTX.res = run_cached(CTX.key)
    CTX.base_res = run_cached(CTX.base_key)
except (InputValidationError, ModelError) as exc:
    st.error(f"The model cannot run with these inputs:\n\n{exc}", icon=":material/error:")
    st.stop()
CTX.is_stressed = CTX.key != CTX.base_key

with st.sidebar:
    st.divider()
    fails = sum(c.status == "fail" for c in CTX.res.checks)
    warns = sum(c.status == "warn" for c in CTX.res.checks)
    if fails:
        st.badge(f"{fails} integrity check(s) failed", icon=":material/error:", color="red")
    else:
        st.badge("Integrity checks pass", icon=":material/verified:", color="green")
    if warns:
        st.badge(f"{warns} financial warning(s)", icon=":material/warning:", color="orange")
    if is_ham and st.session_state.lever_demand_shortfall:
        st.caption("Traffic lever moved on a HAM project: revenue is unchanged by design.")


def chat_context() -> str:
    """Case on screen for the assistant; built only when a question is asked."""
    ss = st.session_state
    scen = SCENARIOS.scenarios[ss.scenario]
    return build_context(
        res=CTX.res, base_res=CTX.base_res, page=navigation.title, project_label=PROJECT_LABELS[ss.ptype],
        scenario_label=scen.label, scenario_description=scen.description, is_stressed=CTX.is_stressed,
        levers={"traffic/ridership shortfall": f"{ss.lever_demand_shortfall}%",
                "cost overrun": f"{ss.lever_cost_overrun}%", "overrun funded by": ss.lever_overrun_funding,
                "construction delay": f"{ss.lever_delay_years} yr", "rate shock": f"{ss.lever_rate_shock:+d} bp"},
        scenario_table=lambda: scenarios_cached(CTX.base_key),
    )


render_chat(chat_context)
navigation.run()
