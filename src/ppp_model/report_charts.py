"""Static report charts with Matplotlib (README §14.3, "Charts for the report").

Writes eight PNG files from model results, so the report uses exactly the numbers the engine and
dashboard produce. Styling: thin marks, hairline solid grid, one y-scale per panel (DSCR gets its own
panel instead of a second axis), categorical colours in a fixed order, status colours only for status.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # file output only; no display needed
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402

from .model import ModelResults  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
ORDINAL = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]
GOOD, WARNING, CRITICAL = "#0ca30c", "#fab219", "#d03b3b"
INK, INK2, GRID, AXIS, SURFACE = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"


def _style(ax, *, ylabel: str | None = None, xlabel: str | None = None) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(AXIS)
        ax.spines[side].set_linewidth(0.8)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK2, labelsize=9, length=3)
    if ylabel:
        ax.set_ylabel(ylabel, color=INK2, fontsize=9)
    if xlabel:
        ax.set_xlabel(xlabel, color=INK2, fontsize=9)


def _year_axis(ax) -> None:
    """Whole-number ticks for a year axis (no 2.5-year ticks)."""
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))


def _thresholds(ax, covenant: float) -> None:
    """Dashed covenant and 1.00x lines, labelled at the right edge above and below so they never collide."""
    ax.axhline(covenant, color=WARNING, linewidth=1, linestyle="--")
    ax.axhline(1.0, color=CRITICAL, linewidth=1, linestyle="--")
    edge = ax.get_yaxis_transform()  # x in axes fraction, y in data units
    ax.text(0.995, covenant, f"covenant {covenant:.2f}x", transform=edge, fontsize=8, color=INK2, ha="right",
            va="bottom")
    ax.text(0.995, 1.0, "1.00x", transform=edge, fontsize=8, color=INK2, ha="right", va="top")


def _figure(width: float = 9.0, height: float = 4.2, rows: int = 1, **kwargs):
    fig, axes = plt.subplots(rows, 1, figsize=(width, height), facecolor=SURFACE, **kwargs)
    return fig, axes


def _save(fig, path: Path, title: str) -> Path:
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, color=INK, fontweight="bold")
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path


def _ops(res: ModelResults) -> pd.DataFrame:
    a = res.annual
    return a[a["Phase"] == "Operation"].set_index("Op year")


def sources_and_uses(res: ModelResults, path: Path) -> Path:
    fu = res.funding
    uses = [("Capex", fu.capex_total), ("IDC", fu.idc_total), ("Fees & DSRA", fu.fees_total + fu.dsra_initial)]
    sources = [("Debt", fu.debt_at_cod), ("Equity", fu.equity_total), ("Grant / support", fu.grant_total)]
    fig, ax = _figure(9, 2.8)
    for row, items, offset in ((1, uses, 0), (0, sources, 3)):
        left = 0.0
        for j, (name, value) in enumerate(items):
            if value <= 1e-9:
                continue
            ax.barh(row, value, left=left, height=0.45, color=SERIES[offset + j], edgecolor=SURFACE, linewidth=1.5,
                    label=name)
            if value / fu.total_project_cost > 0.06:
                ax.text(left + value / 2, row, f"{value:,.0f}", ha="center", va="center", fontsize=9,
                        color=INK if offset + j == 3 else "white")
            left += value
    ax.set_yticks([0, 1], ["Sources", "Uses"])
    _style(ax, xlabel="₹ crore")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.legend(ncol=6, fontsize=8, frameon=False, loc="lower left", bbox_to_anchor=(0, 1.0))
    return _save(fig, path, "Sources and uses of funds")


def revenue_build_up(res: ModelResults, path: Path) -> Path:
    d = _ops(res)
    fig, ax = _figure()
    bottom = np.zeros(len(d))
    for i, col in enumerate(res.revenue.lines):
        ax.bar(d.index, d[col], bottom=bottom, width=0.55, color=SERIES[i], edgecolor=SURFACE, linewidth=1, label=col)
        bottom += d[col].to_numpy()
    _style(ax, ylabel="₹ crore", xlabel="Operating year")
    _year_axis(ax)
    if len(res.revenue.lines) > 1:
        ax.legend(fontsize=8, frameon=False, ncol=3, loc="upper left")
    ramp = d.get("Ramp-up factor")
    if ramp is not None:
        first_full = int(ramp.index[np.argmax(ramp.to_numpy() >= 1.0)])
        ax.axvline(first_full - 0.5, color=AXIS, linewidth=1)
        ax.text(first_full - 0.4, ax.get_ylim()[1] * 0.95, "ramp-up complete", fontsize=8, color=INK2, va="top")
    return _save(fig, path, "Revenue build-up")


def cfads_vs_debt_service(res: ModelResults, path: Path) -> Path:
    d = _ops(res)
    cov = res.inputs.covenants.min_dscr
    fig, (top, bottom) = _figure(9, 6.2, rows=2, sharex=True, gridspec_kw={"height_ratios": [1.6, 1]})
    k = d.index.to_numpy()
    top.bar(k - 0.18, d["CFADS"], width=0.34, color=SERIES[0], label="CFADS")
    top.bar(k + 0.18, d["Debt service"], width=0.34, color=SERIES[1], label="Debt service")
    _style(top, ylabel="₹ crore")
    top.legend(fontsize=8, frameon=False, loc="upper left")
    dscr = d["DSCR"].astype(float)
    colors = [CRITICAL if v < 1 else WARNING if v < cov else GOOD for v in dscr.fillna(np.inf)]
    bottom.plot(k, dscr, color=INK2, linewidth=1.6, zorder=2)
    bottom.scatter(k, dscr, c=colors, s=36, edgecolors=SURFACE, linewidths=1.5, zorder=3)
    _thresholds(bottom, cov)
    _style(bottom, ylabel="DSCR (x)", xlabel="Operating year")
    _year_axis(bottom)
    bottom.set_ylim(0, max(np.nanmax(dscr) * 1.1, cov * 1.2))
    return _save(fig, path, "CFADS vs debt service, and DSCR")


def debt_outstanding(res: ModelResults, path: Path) -> Path:
    a = res.annual
    tl = res.timeline
    fig, ax = _figure()
    ax.fill_between(a.index, a["Closing debt"], color=SERIES[0], alpha=0.10, linewidth=0)
    ax.plot(a.index, a["Closing debt"], color=SERIES[0], linewidth=2, marker="o", markersize=4,
            markeredgecolor=SURFACE)
    ax.axvline(tl.construction_years + 0.5, color=AXIS, linewidth=1)
    ax.text(tl.construction_years + 0.6, ax.get_ylim()[1] * 0.95, "COD", fontsize=8, color=INK2, va="top")
    if res.metrics.tail_years:
        start = tl.construction_years + res.metrics.final_repayment_op_year + 0.5
        ax.axvspan(start, tl.model_years + 0.5, color=GRID, alpha=0.6, linewidth=0)
        ax.text((start + tl.model_years + 0.5) / 2, ax.get_ylim()[1] * 0.5, f"tail\n{res.metrics.tail_years} yr",
                ha="center", fontsize=8, color=INK2)
    _style(ax, ylabel="₹ crore", xlabel="Model year")
    _year_axis(ax)
    return _save(fig, path, "Debt outstanding over time")


def scenario_comparison(table: pd.DataFrame, res: ModelResults, path: Path) -> Path:
    cov, hurdle = res.inputs.covenants.min_dscr, res.inputs.valuation.equity_hurdle
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 0.45 * len(table) + 1.6), facecolor=SURFACE, sharey=True)
    y = np.arange(len(table))
    dscr = table["Min DSCR"].astype(float).to_numpy()
    eirr = table["Equity IRR"].astype(float).to_numpy()
    left.barh(y, dscr, height=0.55, color=[CRITICAL if v < 1 else WARNING if v < cov else GOOD for v in dscr])
    left.axvline(cov, color=WARNING, linestyle="--", linewidth=1)
    left.axvline(1.0, color=CRITICAL, linestyle="--", linewidth=1)
    for yi, v in zip(y, dscr):
        left.text(v + 0.02, yi, f"{v:.2f}x", va="center", fontsize=8, color=INK2)
    right.barh(y, eirr, height=0.55, color=[GOOD if v >= hurdle else CRITICAL for v in eirr])
    right.axvline(hurdle, color=WARNING, linestyle="--", linewidth=1)
    for yi, v in zip(y, eirr):
        right.text(v + 0.003, yi, f"{v:.1%}", va="center", fontsize=8, color=INK2)
    left.set_yticks(y, table["Scenario"])
    left.invert_yaxis()
    _style(left, xlabel="Minimum DSCR (x); dashed: covenant and 1.00x")
    _style(right, xlabel=f"Equity IRR; dashed: {hurdle:.0%} hurdle")
    for ax in (left, right):
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
    right.xaxis.set_major_locator(matplotlib.ticker.MultipleLocator(0.05))  # whole-percent ticks only
    right.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    return _save(fig, path, "Scenario comparison: lender and sponsor view")


def tornado_chart(df: pd.DataFrame, path: Path) -> Path:
    shock = df.attrs.get("shock", 0.10)
    d = df.iloc[::-1]
    y = np.arange(len(d))
    fig, ax = _figure(9, 0.45 * len(d) + 1.4)
    ax.barh(y + 0.18, d["Δ Equity IRR (low)"].astype(float) * 100, height=0.34, color=SERIES[0],
            label=f"input -{shock:.0%}")
    ax.barh(y - 0.18, d["Δ Equity IRR (high)"].astype(float) * 100, height=0.34, color=SERIES[1],
            label=f"input +{shock:.0%}")
    ax.axvline(0, color=INK2, linewidth=1)
    ax.set_yticks(y, d["Variable"])
    _style(ax, xlabel="Change in Equity IRR (percentage points)")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    return _save(fig, path, f"Tornado: Equity IRR sensitivity (base {df.attrs.get('base_equity_irr', 0):.2%})")


def heatmap(grid: pd.DataFrame, covenant: float, path: Path) -> Path:
    fig, ax = _figure(8, 5)
    cmap = ListedColormap(["#f3c0c0", "#fde3a7", "#c8ecc8"])
    norm = BoundaryNorm([-1e9, 1.0, covenant, 1e9], cmap.N)
    ax.imshow(grid.to_numpy(dtype=float), cmap=cmap, norm=norm, aspect="auto")
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            ax.text(j, i, f"{grid.iat[i, j]:.2f}x", ha="center", va="center", fontsize=9, color=INK)
    ax.set_xticks(range(grid.shape[1]), [f"+{c:.0%}" for c in grid.columns])
    ax.set_yticks(range(grid.shape[0]), [f"-{r:.0%}" if r > 0 else "0%" for r in grid.index])
    ax.set_xlabel("Cost overrun", color=INK2, fontsize=9)
    ax.set_ylabel("Traffic shortfall", color=INK2, fontsize=9)
    ax.tick_params(colors=INK2, labelsize=9, length=0)
    for side in ax.spines.values():
        side.set_visible(False)
    return _save(fig, path, f"Minimum DSCR: red < 1.00x, amber < {covenant:.2f}x covenant, green above")


def profile_comparison_chart(dscr: pd.DataFrame, covenant: float, path: Path) -> Path:
    fig, ax = _figure()
    for i, col in enumerate(dscr.columns):
        ax.plot(dscr.index, dscr[col], color=SERIES[i], linewidth=2, marker="o", markersize=4,
                markeredgecolor=SURFACE, label=col)
    _thresholds(ax, covenant)
    _style(ax, ylabel="DSCR (x)", xlabel="Operating year")
    _year_axis(ax)
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=8, frameon=False, ncol=4, loc="upper left")
    return _save(fig, path, "Repayment profile comparison: DSCR by year")


def write_report_charts(res: ModelResults, out_dir: str | Path, *, scenario_table: pd.DataFrame,
                        two_way: pd.DataFrame, tornado_df: pd.DataFrame,
                        profile_results: dict[str, ModelResults]) -> list[Path]:
    """Write the eight README §14.3 charts as PNG files and return their paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tl = res.timeline
    ops = slice(tl.cod_index, tl.model_years)
    profiles = pd.DataFrame({p: r.dscr[ops] for p, r in profile_results.items()},
                            index=pd.Index(tl.op_year[ops], name="Op year"))
    cov = res.inputs.covenants.min_dscr
    return [
        sources_and_uses(res, out / "1_sources_and_uses.png"),
        revenue_build_up(res, out / "2_revenue_build_up.png"),
        cfads_vs_debt_service(res, out / "3_cfads_vs_debt_service.png"),
        debt_outstanding(res, out / "4_debt_outstanding.png"),
        scenario_comparison(scenario_table, res, out / "5_scenario_comparison.png"),
        tornado_chart(tornado_df, out / "6_tornado_equity_irr.png"),
        heatmap(two_way, cov, out / "7_heatmap_min_dscr.png"),
        profile_comparison_chart(profiles, cov, out / "8_repayment_profiles.png"),
    ]
