"""Tests for position accounting rules (Slice 4)."""
from __future__ import annotations

from decimal import Decimal

from quant_positions.domain.accounting import apply_ledger_event, PositionUpdate


def test_positive_quantity_increases_position():
    result = apply_ledger_event(
        current_quantity=Decimal("0"),
        current_avg_cost=Decimal("0"),
        quantity_delta=Decimal("10"),
        price=Decimal("100"),
        fees=Decimal("0"),
    )
    assert result.new_quantity == Decimal("10")
    assert result.new_average_cost == Decimal("100")
    assert result.realized_pnl_delta == Decimal("0")


def test_positive_quantity_updates_average_cost():
    """Buying 10 @ 100, then 10 @ 200 => avg cost 150."""
    result = apply_ledger_event(
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity_delta=Decimal("10"),
        price=Decimal("200"),
        fees=Decimal("0"),
    )
    assert result.new_quantity == Decimal("20")
    assert result.new_average_cost == Decimal("150")


def test_negative_quantity_decreases_position():
    result = apply_ledger_event(
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity_delta=Decimal("-5"),
        price=Decimal("150"),
        fees=Decimal("0"),
    )
    assert result.new_quantity == Decimal("5")
    # avg cost stays the same on sell (weighted average method)
    assert result.new_average_cost == Decimal("100")
    # realized PnL: 5 * (150 - 100) = 250
    assert result.realized_pnl_delta == Decimal("250")


def test_full_reduction_closes_position():
    result = apply_ledger_event(
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity_delta=Decimal("-10"),
        price=Decimal("120"),
        fees=Decimal("0"),
    )
    assert result.new_quantity == Decimal("0")
    assert result.new_average_cost == Decimal("0")
    # realized PnL: 10 * (120 - 100) = 200
    assert result.realized_pnl_delta == Decimal("200")


def test_partial_reduction_preserves_avg_cost():
    result = apply_ledger_event(
        current_quantity=Decimal("100"),
        current_avg_cost=Decimal("50"),
        quantity_delta=Decimal("-30"),
        price=Decimal("60"),
        fees=Decimal("0"),
    )
    assert result.new_quantity == Decimal("70")
    assert result.new_average_cost == Decimal("50")
    assert result.realized_pnl_delta == Decimal("300")  # 30 * (60 - 50)


def test_fees_reduce_realized_pnl():
    result = apply_ledger_event(
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity_delta=Decimal("-5"),
        price=Decimal("150"),
        fees=Decimal("10"),
    )
    # realized PnL: 5 * (150 - 100) - 10 = 240
    assert result.realized_pnl_delta == Decimal("240")
    assert result.fees == Decimal("10")


def test_fees_on_buy_reduce_realized_pnl():
    result = apply_ledger_event(
        current_quantity=Decimal("0"),
        current_avg_cost=Decimal("0"),
        quantity_delta=Decimal("10"),
        price=Decimal("100"),
        fees=Decimal("5"),
    )
    assert result.new_quantity == Decimal("10")
    assert result.realized_pnl_delta == Decimal("-5")
    assert result.fees == Decimal("5")


def test_zero_delta_fee_only():
    result = apply_ledger_event(
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity_delta=Decimal("0"),
        price=None,
        fees=Decimal("15"),
    )
    assert result.new_quantity == Decimal("10")
    assert result.new_average_cost == Decimal("100")
    assert result.realized_pnl_delta == Decimal("-15")


def test_sell_without_price_does_not_update_realized_pnl():
    result = apply_ledger_event(
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity_delta=Decimal("-5"),
        price=None,
        fees=Decimal("0"),
    )
    assert result.new_quantity == Decimal("5")
    assert result.realized_pnl_delta == Decimal("0")


def test_duplicate_import_does_not_double_count():
    """Simulates applying the same event twice - position should be the same."""
    state_qty = Decimal("0")
    state_avg = Decimal("0")

    # First application
    r1 = apply_ledger_event(state_qty, state_avg, Decimal("10"), Decimal("100"), Decimal("0"))
    state_qty = r1.new_quantity
    state_avg = r1.new_average_cost
    assert state_qty == Decimal("10")

    # For idempotency, the duplicate should be detected at the repository layer
    # (by idempotency_key), so the accounting function is NOT called again.
    # This test confirms the accounting function is deterministic.
    r2 = apply_ledger_event(Decimal("0"), Decimal("0"), Decimal("10"), Decimal("100"), Decimal("0"))
    assert r2.new_quantity == Decimal("10")
    assert r2.new_average_cost == Decimal("100")


def test_sell_at_loss():
    result = apply_ledger_event(
        current_quantity=Decimal("10"),
        current_avg_cost=Decimal("100"),
        quantity_delta=Decimal("-5"),
        price=Decimal("80"),
        fees=Decimal("0"),
    )
    # realized PnL: 5 * (80 - 100) = -100
    assert result.realized_pnl_delta == Decimal("-100")
