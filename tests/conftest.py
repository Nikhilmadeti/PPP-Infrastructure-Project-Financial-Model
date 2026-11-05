"""Shared fixtures. Raw configs are re-read for every test so no test can leak changes into another."""

from __future__ import annotations

import pytest

from ppp_model import base_config_path, deep_merge, load_yaml, run_model


@pytest.fixture
def toll_raw() -> dict:
    return load_yaml(base_config_path("toll"))


@pytest.fixture
def metro_raw() -> dict:
    return load_yaml(base_config_path("metro"))


@pytest.fixture
def ham_raw() -> dict:
    return load_yaml(base_config_path("ham"))


@pytest.fixture(scope="session")
def toll_res():
    return run_model(load_yaml(base_config_path("toll")))


@pytest.fixture(scope="session")
def metro_res():
    return run_model(load_yaml(base_config_path("metro")))


@pytest.fixture(scope="session")
def ham_res():
    return run_model(load_yaml(base_config_path("ham")))


def run_with(raw: dict, **blocks):
    """Run the model with nested overrides, e.g. run_with(raw, debt={'profile': 'equal'})."""
    return run_model(deep_merge(raw, blocks))


def op(res, k: int) -> int:
    """Array index of operating year k."""
    return res.timeline.index_of_op_year(k)
