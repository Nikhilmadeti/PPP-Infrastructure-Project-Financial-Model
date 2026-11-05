"""PPP infrastructure project financial model (BOT toll road, metro, Hybrid Annuity Model).

Typical use::

    from ppp_model import load_inputs, run_model, base_config_path
    res = run_model(load_inputs(base_config_path("toll")))
    res.metrics.min_dscr, res.metrics.equity_irr.value, res.annual

The calculation engine has no dependency on Streamlit; ``app/dashboard.py`` only displays results.
"""

from .errors import ConvergenceError, FundingError, InputValidationError, ModelError
from .inputs import (
    ModelInputs,
    base_config_path,
    build_inputs,
    config_dir,
    deep_merge,
    inputs_to_dict,
    load_inputs,
    load_yaml,
)
from .model import ModelResults, run_model

__version__ = "1.0.0"

__all__ = [
    "ConvergenceError",
    "FundingError",
    "InputValidationError",
    "ModelError",
    "ModelInputs",
    "ModelResults",
    "base_config_path",
    "build_inputs",
    "config_dir",
    "deep_merge",
    "inputs_to_dict",
    "load_inputs",
    "load_yaml",
    "run_model",
]
