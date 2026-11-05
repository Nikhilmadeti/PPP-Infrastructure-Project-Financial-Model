"""Excel export (README §13.2): sheets, values from the engine, no formulas."""

import io

import openpyxl
import pytest

from ppp_model.export import build_hand_check_workbook, build_workbook
from ppp_model.scenarios import load_scenarios, run_scenarios

REQUIRED = {"Assumptions", "Timeline", "Capex", "Funding_IDC", "Revenue", "OM_Tax", "Debt", "CFADS_Waterfall",
            "Metrics", "Scenarios", "Checks", "HandCheck"}


def test_workbook_has_every_sheet_and_engine_values(toll_res, toll_raw):
    table, _ = run_scenarios(toll_raw, load_scenarios(), keys=["base", "traffic_m20"])
    wb = openpyxl.load_workbook(io.BytesIO(build_workbook(toll_res, scenario_table=table)))
    assert REQUIRED <= set(wb.sheetnames)
    debt = wb["Debt"]
    rows = {debt.cell(r, 1).value: r for r in range(1, debt.max_row + 1)}
    assert debt.cell(rows["DSCR"], 4 + 3).value == pytest.approx(toll_res.dscr[3])  # op year 1 = model year 4
    assert debt.cell(rows["Closing debt"], 3 + 3).value == pytest.approx(779.1525, abs=1e-4)
    assert debt.freeze_panes == "D7"
    formulas = [c for ws in wb for row in ws.iter_rows() for c in row
                if isinstance(c.value, str) and c.value.startswith("=")]
    assert not formulas  # values only: no recalculation needed
    scen = wb["Scenarios"]
    assert scen.auto_filter.ref is not None
    assert scen.max_row == 4 + len(table)


def test_hand_check_workbook(toll_res):
    wb = openpyxl.load_workbook(io.BytesIO(build_hand_check_workbook(toll_res)))
    ws = wb["HandCheck"]
    statuses = [ws.cell(r, 7).value for r in range(5, ws.max_row + 1) if ws.cell(r, 7).value in {"OK", "CHECK"}]
    assert statuses and all(s == "OK" for s in statuses)


def test_report_charts_are_written(toll_res, toll_raw, tmp_path):
    from ppp_model.report_charts import write_report_charts
    from ppp_model.scenarios import profile_comparison, tornado, two_way_table

    config = load_scenarios()
    table, _ = run_scenarios(toll_raw, config, keys=["base", "traffic_m20"])
    _, profiles = profile_comparison(toll_raw)
    paths = write_report_charts(
        toll_res, tmp_path, scenario_table=table, two_way=two_way_table(toll_raw, [0.0, 0.2], [0.0, 0.2]),
        tornado_df=tornado(toll_raw, config.tornado_variables["toll"][:2], 0.1), profile_results=profiles)
    assert len(paths) == 8  # README §14.3 lists eight report charts
    assert all(p.exists() and p.stat().st_size > 5000 for p in paths)


@pytest.mark.parametrize("fixture", ["metro_res", "ham_res"])
def test_workbook_builds_for_metro_and_ham(fixture, request):
    res = request.getfixturevalue(fixture)
    wb = openpyxl.load_workbook(io.BytesIO(build_workbook(res)))
    assert "Revenue" in wb.sheetnames
    if res.inputs.project_type == "ham":
        assert "HAM_Annuity" in wb.sheetnames
