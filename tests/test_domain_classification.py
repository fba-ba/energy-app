"""Tests de classification prélèvement/injection et de la règle de précédence."""

from __future__ import annotations

from app.domain.classification import Direction, classify_direction, is_rate, is_totals


def test_consumption_is_withdrawal():
    assert classify_direction("Consumption (+A) rate 1") == Direction.WITHDRAWAL
    assert classify_direction("consumption totals") == Direction.WITHDRAWAL
    assert classify_direction("Energie prélevée") == Direction.WITHDRAWAL
    assert classify_direction("ENERGIE PRELEVEE") == Direction.WITHDRAWAL


def test_production_is_injection():
    assert classify_direction("Production (-A) totals rate 2") == Direction.INJECTION
    assert classify_direction("PRODUCTION (+A) Totals") == Direction.INJECTION
    assert classify_direction("Energie injectée") == Direction.INJECTION


def test_unknown_variable_is_none():
    assert classify_direction("Temperature") is None
    assert classify_direction(None) is None
    assert classify_direction("") is None


def test_totals_excludes_rate_registers():
    # Les registres « totals rate N » sont des composantes, pas des totaux.
    assert is_totals("Consumption (A+) Totals") is True
    assert is_totals("Consumption (+A) totals rate 1") is False
    assert is_totals("Production (-A) totals rate 2") is False
    assert is_rate("Consumption (+A) totals rate 1") is True
    assert is_rate("Production (-A) rate 2") is True
