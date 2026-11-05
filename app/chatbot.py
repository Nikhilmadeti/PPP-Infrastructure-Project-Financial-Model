"""Floating "Ask the model" assistant for the dashboard, powered by the Google Gemini API.

The assistant *explains* results; it never calculates them. Every number it sees comes from
``ppp_model`` for the case currently on screen (project type + scenario + stress levers), plus the
methodology and assumptions documents. If a question needs a number the model has not produced,
the assistant is told to say so and point the user to the lever or page that would produce it.

API key, looked up in this order:
    1. ``GEMINI_API_KEY`` in ``.streamlit/secrets.toml`` (git-ignored)
    2. ``GEMINI_API_KEY`` or ``GOOGLE_API_KEY`` environment variable
    3. pasted into the chat panel (kept in this browser session only)
Model: ``GEMINI_MODEL`` in secrets or the environment, default ``gemini-flash-latest``.

Privacy: each question sends the current assumptions and results to Google. Do not use it with
confidential project data unless your agreement with Google allows that.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterator

import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gemini-flash-latest"
# Tried in order when the configured model is overloaded (503), out of free quota (429) or missing (404).
FALLBACK_MODELS = ("gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite")
RETRY_WAITS = (2.0, 5.0)  # seconds between retries of a busy model
DOCS = ("docs/model_methodology.md", "docs/assumptions_and_limitations.md")
ANNUAL_COLUMNS = [
    "Fiscal year", "Phase", "Op year", "Capex", "IDC", "Debt drawdown", "Equity contribution",
    "Grant / construction support", "Total revenue", "Total opex", "EBITDA", "Tax", "CFADS",
    "Opening debt", "Interest paid", "Principal", "Debt service", "Closing debt", "DSCR", "LLCR",
    "DSRA closing", "Distributions", "Project cash flow (pre-grant)", "Equity cash flow",
]
SUGGESTIONS = [
    "Is this project bankable? Explain in plain words.",
    "Why is the minimum DSCR in that year?",
    "What is the difference between DSCR and LLCR?",
    "How is interest during construction calculated here?",
]

SYSTEM_RULES = """\
You are the built-in assistant of a PPP (Public-Private Partnership) infrastructure project financial
model, a course project for CE725 Construction Economics and Finance (Topic 9). The tool models
debt-equity structure, interest during construction (IDC), revenue ramp-up, CFADS, DSCR, LLCR,
Project IRR and Equity IRR for a BOT toll road, a metro line or a Hybrid Annuity Model (HAM) road,
with stress scenarios for traffic shortfall, cost overrun, delay and interest-rate rise.

Users are students, lenders, developers or a non-technical decision-maker looking at the dashboard.

Rules:
1. Use ONLY the numbers given below under CURRENT CASE. They come from the tested model. Never invent,
   estimate or recalculate a figure that is not given. If a question needs a number that is not there,
   say so and tell the user which sidebar lever or dashboard page would produce it.
2. You may show how a given number follows from other given numbers (e.g. DSCR = CFADS / debt
   service for a year), using the formulas in the METHODOLOGY section.
3. Money is in ₹ crore (₹ Cr) unless stated. Ratios are shown like 1.26x; rates as percentages.
4. Lender covenants for this case are given under CURRENT CASE. Compare against them, not against
   rules of thumb, and say where a threshold comes from.
5. Metro and HAM base cases use illustrative cost and financing assumptions, not real project data.
   Mention this when it matters.
6. Be concise: short paragraphs or bullets, plain language first, then the technical detail.
   Use markdown. Do not use LaTeX.
7. If the question is unrelated to this project or to construction economics and finance, say briefly
   that you can only help with this model.
"""


# ---------------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------------


def _setting(name: str) -> str | None:
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # no secrets.toml: st.secrets raises on access
        pass
    return os.environ.get(name)


def _api_key() -> str | None:
    return (_setting("GEMINI_API_KEY") or _setting("GOOGLE_API_KEY")
            or st.session_state.get("chat_api_key") or None)


def _model_name() -> str:
    return _setting("GEMINI_MODEL") or DEFAULT_MODEL


@st.cache_data(show_spinner=False)
def _docs_text() -> str:
    parts = []
    for rel in DOCS:
        path = ROOT / rel
        if path.exists():
            parts.append(f"----- {rel} -----\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------------------------
# Context: what the assistant is told about the case on screen
# ---------------------------------------------------------------------------------------------


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.4f}"
    return str(v)


def _metrics_block(res) -> str:
    m = res.metrics
    rows = {
        "Total project cost": m.total_project_cost, "Capex (incl. contingency)": m.capex, "IDC": m.idc,
        "Upfront fees": m.fees, "Grant / construction support": m.grant, "Debt": m.debt, "Equity": m.equity,
        "Gearing applied": m.gearing_applied, "Min DSCR": m.min_dscr, "Min DSCR op year": m.min_dscr_op_year,
        "Avg DSCR": m.avg_dscr, "LLCR at COD": m.llcr_cod, "PLCR at COD": m.plcr_cod, "Min ICR": m.min_icr,
        "Project IRR (pre-grant)": m.project_irr.display(), "Project IRR (post-grant)": m.project_irr_post_grant.display(),
        "Equity IRR": m.equity_irr.display(), "Project NPV (pre-grant)": m.project_npv,
        "Project NPV (post-grant)": m.project_npv_post_grant, "Equity NPV": m.equity_npv,
        "Equity payback": m.payback.display(), "Debt fully repaid": m.debt_fully_repaid,
        "Final repayment op year": m.final_repayment_op_year, "Debt outstanding at end": m.outstanding_at_end,
        "Tail (years)": m.tail_years, "Op years with DSCR < 1.00x": list(m.dscr_below_one_years) or "none",
        "Op years with DSCR below covenant": list(m.dscr_below_covenant_years) or "none",
        "Equity IRR meets hurdle": m.equity_meets_hurdle, "Sponsor support needed": m.sponsor_support,
        "Debt-service shortfall": m.ds_shortfall,
    }
    return "\n".join(f"- {k}: {_fmt(v)}" for k, v in rows.items())


def _annual_block(res) -> str:
    cols = [c for c in ANNUAL_COLUMNS if c in res.annual.columns]
    df = res.annual[cols].copy()
    for c in df.columns:
        if pd.api.types.is_float_dtype(df[c]):
            df[c] = df[c].round(3)
    return df.to_csv()


def _checks_block(res) -> str:
    lines = [f"- [{c.status.upper()}] {c.id} {c.name}: {c.detail}" for c in res.checks if c.status != "pass"]
    count = {s: sum(c.status == s for c in res.checks) for s in ("pass", "fail", "warn")}
    head = (f"{len(res.checks)} checks: {count['pass']} pass, {count['fail']} fail, {count['warn']} warn, "
            f"the rest are information only (not a problem).")
    warn = "\n".join(f"- Warning: {w}" for w in res.warnings)
    return "\n".join(x for x in (head, *lines, warn) if x)


def build_context(*, res, base_res, page: str, project_label: str, scenario_label: str,
                  scenario_description: str, levers: dict, is_stressed: bool,
                  scenario_table: Callable[[], pd.DataFrame] | None = None) -> str:
    """Everything the assistant knows, as one text block (rebuilt on every question)."""
    inputs = yaml.safe_dump(_inputs_dict(res), sort_keys=False, allow_unicode=True)
    parts = [
        SYSTEM_RULES,
        "=== CURRENT CASE ===",
        f"Dashboard page the user is viewing: {page}",
        f"Project type: {project_label}",
        f"Scenario: {scenario_label} - {scenario_description}",
        "Stress levers: " + ", ".join(f"{k} = {v}" for k, v in levers.items()),
        f"Covenants: {res.inputs.covenants}" if hasattr(res.inputs, "covenants") else "",
        "\nKey results (current case):\n" + _metrics_block(res),
    ]
    if is_stressed:
        parts.append("\nKey results (unstressed base case, for comparison):\n" + _metrics_block(base_res))
    parts += [
        "\nModel checks:\n" + _checks_block(res),
        "\nAnnual schedule (model years; ₹ Cr unless a ratio):\n" + _annual_block(res),
    ]
    if scenario_table is not None:
        try:
            parts.append("\nScenario table (all predefined scenarios run on this project's base case; "
                         "IRRs as decimals):\n" + scenario_table().round(4).to_csv())
        except Exception as exc:  # the chat must still work if the scenario run fails
            parts.append(f"\nScenario table unavailable: {exc}")
    parts += ["\nFull input assumptions (YAML):\n" + inputs, "\n=== METHODOLOGY ===\n" + _docs_text()]
    return "\n".join(p for p in parts if p)


def _inputs_dict(res) -> dict:
    from ppp_model import inputs_to_dict
    return inputs_to_dict(res.inputs)


# ---------------------------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------------------------


def _stream_answer(api_key: str, system: str, history: list[dict]) -> Iterator[str]:
    from google import genai
    from google.genai import types

    from google.genai import errors

    client = genai.Client(api_key=api_key)
    contents = [types.Content(role="user" if m["role"] == "user" else "model",
                              parts=[types.Part.from_text(text=m["content"])]) for m in history]
    config = types.GenerateContentConfig(system_instruction=system, temperature=0.2)

    last_exc: Exception | None = None
    for i, model in enumerate(_candidate_models()):
        waits = RETRY_WAITS if i == 0 else ()  # retry the preferred model; fallbacks get one try each
        for attempt in range(len(waits) + 1):
            started = False
            try:
                for chunk in client.models.generate_content_stream(model=model, contents=contents, config=config):
                    if chunk.text:
                        started = True
                        yield chunk.text
                st.session_state.chat_model_used = model
                return
            except errors.APIError as exc:
                if started:  # part of the answer is already on screen: do not repeat it from another model
                    raise
                last_exc = exc
                if exc.code in (500, 503, 504) and attempt < len(waits):
                    time.sleep(waits[attempt])  # busy: wait and retry the same model
                    continue
                if exc.code in (404, 429, 500, 503, 504):
                    break  # not available, out of free quota or still busy: try the next model
                raise  # bad key, bad request: another model will not help
    raise last_exc if last_exc else RuntimeError("No Gemini model available")


def _candidate_models() -> list[str]:
    """The configured model first, then fallbacks, without duplicates."""
    models = [_model_name(), *FALLBACK_MODELS]
    return list(dict.fromkeys(models))


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    code = getattr(exc, "code", None)
    tried = ", ".join(f"`{m}`" for m in _candidate_models())
    if code == 400 and "API key" not in text:
        return f"Gemini could not process the request: {text[:300]}"
    if code in (500, 503, 504) or "high demand" in text:
        return (f"Gemini is overloaded right now (tried {tried}, with retries). This is on Google's side and "
                "usually clears within minutes. Send the question again shortly.")
    if "API key" in text or "API_KEY" in text or "401" in text or "403" in text:
        return "Gemini rejected the API key. Check `GEMINI_API_KEY`."
    if "404" in text or "not found" in text.lower():
        return (f"Gemini model `{_model_name()}` was not found. Set `GEMINI_MODEL` in "
                "`.streamlit/secrets.toml` to a current model id from ai.google.dev/gemini-api/docs/models.")
    if "429" in text or "quota" in text.lower():
        return (f"Free-tier quota or rate limit reached on every model tried ({tried}). "
                "Wait a minute (per-minute limit) or until tomorrow (daily limit).")
    return f"Gemini request failed: {text[:300]}"


# ---------------------------------------------------------------------------------------------
# UI: floating button bottom-right, chat panel in a popover
# ---------------------------------------------------------------------------------------------

_CSS = """
<style>
.st-key-ppp_chat_fab {
    position: fixed; right: 1.5rem; bottom: 1.5rem; z-index: 999990; width: auto !important;
}
.st-key-ppp_chat_fab button {
    border-radius: 999px; padding: 0.65rem 1.1rem; box-shadow: 0 4px 14px rgba(0,0,0,0.25);
}
div[data-testid="stPopoverBody"]:has(.st-key-ppp_chat_panel) {
    width: min(26rem, calc(100vw - 2rem)); max-width: none;
}
@media (max-width: 640px), (max-height: 760px) {
    .st-key-ppp_chat_msgs { height: auto !important; max-height: 38vh; }
}
</style>
"""


def _ask(question: str) -> None:
    st.session_state.chat_history.append({"role": "user", "content": question})
    st.session_state.chat_pending = True


def render_chat(context_fn: Callable[[], str]) -> None:
    """Draw the floating assistant. ``context_fn`` builds the case context only when a question is asked."""
    ss = st.session_state
    ss.setdefault("chat_history", [])
    ss.setdefault("chat_pending", False)
    st.html(_CSS)

    with st.container(key="ppp_chat_fab"):
        with st.popover("Ask the model", icon=":material/smart_toy:", type="primary"):
            with st.container(key="ppp_chat_panel"):
                _panel(context_fn)


def _panel(context_fn: Callable[[], str]) -> None:
    ss = st.session_state
    st.markdown("**PPP model assistant**")

    api_key = _api_key()
    if not api_key:
        st.caption("Add a Gemini API key to start. Get one free at aistudio.google.com. "
                   "For a permanent key, put `GEMINI_API_KEY = \"...\"` in `.streamlit/secrets.toml`.")
        st.text_input("Gemini API key", type="password", key="chat_api_key_input", on_change=_save_key)
        return

    box = st.container(height=380, border=False, key="ppp_chat_msgs")
    with box:
        if not ss.chat_history:
            st.caption("Ask about the results on screen. Answers explain the model's numbers for the "
                       "current project, scenario and levers; they do not change them.")
            for i, q in enumerate(SUGGESTIONS):
                st.button(q, key=f"chat_suggest_{i}", on_click=_ask, args=(q,), width="stretch")
        for m in ss.chat_history:
            with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user"
                                 else ":material/smart_toy:"):
                st.markdown(m["content"])

        if ss.chat_pending:
            ss.chat_pending = False
            with st.chat_message("assistant", avatar=":material/smart_toy:"):
                try:
                    with st.spinner("Thinking…"):
                        system = context_fn()
                    answer = st.write_stream(_stream_answer(api_key, system, ss.chat_history))
                    answer = answer if isinstance(answer, str) else "".join(map(str, answer))
                except Exception as exc:
                    answer = None
                    msg = _friendly_error(exc)
                    st.error(msg, icon=":material/error:")
                    ss.chat_history.pop()  # let the user retry the same question
                    if msg.startswith("Gemini rejected") and ss.get("chat_api_key"):
                        ss.chat_api_key = ""  # a pasted key was wrong: show the key box again
                        st.button("Enter a different key", key="chat_rekey")
            if answer:
                ss.chat_history.append({"role": "assistant", "content": answer})

    st.chat_input("Ask about this project…", key="chat_input", on_submit=_on_submit)
    st.caption("AI answers can be wrong: check them against the model's tables. Your question and the "
               "current results are sent to Google Gemini."
               + (f" Last answer: `{ss.chat_model_used}`." if ss.get("chat_model_used") else ""))
    if ss.chat_history:
        st.button("Clear conversation", icon=":material/delete_sweep:", type="tertiary", key="chat_clear",
                  on_click=_clear)


def _save_key() -> None:
    # Copied out of the widget's own state: Streamlit deletes widget state once the widget stops
    # being drawn, and the key box disappears as soon as a key is set.
    st.session_state.chat_api_key = (st.session_state.get("chat_api_key_input") or "").strip()


def _clear() -> None:
    st.session_state.chat_history, st.session_state.chat_pending = [], False


def _on_submit() -> None:
    q = (st.session_state.get("chat_input") or "").strip()
    if q:
        _ask(q)
