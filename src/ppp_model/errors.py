"""Exceptions raised by the PPP model.

Every failure the model can detect is raised as one of these, with a message that says
what was wrong and, where possible, how to fix it.
"""

from __future__ import annotations

from collections.abc import Iterable


class ModelError(Exception):
    """Base class for all errors raised by the model."""


class InputValidationError(ModelError, ValueError):
    """One or more inputs are missing, of the wrong type, out of range or inconsistent.

    All problems found are collected in ``errors`` so the user can fix them in one pass.
    """

    def __init__(self, errors: Iterable[str]):
        self.errors = [str(e) for e in errors]
        message = "Invalid model inputs:\n" + "\n".join(f"  - {e}" for e in self.errors)
        super().__init__(message)


class ConvergenceError(ModelError, RuntimeError):
    """An iterative solve (IDC, fees, sculpting/tax, DSRA, debt sizing) did not converge."""


class FundingError(ModelError):
    """The construction funding cannot be solved (for example, a grant larger than the uses)."""
