"""Backtesting engine — event-driven strategy backtester.

Supports:
- Factor expression-based signal generation
- Configurable initial capital, fees, slippage
- Performance metrics (Sharpe, max drawdown, win rate, etc.)
- Trade log with entry/exit details
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from backend.factor_engine import FactorFunctions, evaluate_expression

logger = logging.getLogger("stockoverflow")


@dataclass
class BacktestConfig:
    initial_capital: float = 100000.0
    fee_rate: float = 0.001  # 0.1% per trade
    slippage: float = 0.0005  # 0.05% slippage
    position_size: float = 1.0  # fraction of capital per trade
    stop_loss_pct: float | None = None  # e.g., 0.05 for 5%
    take_profit_pct: float | None = None  # e.g., 0.10 for 10%


@dataclass
class Trade:
    entry_date: str
    entry_price: float
    exit_date: str | None = None
    exit_price: float | None = None
    shares: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""


@dataclass
class BacktestResult:
    # performance
    total_return: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pnl: float = 0.0
    total_trades: int = 0
    # equity curve
    equity_curve: list[dict] = field(default_factory=list)
    # trade log
    trades: list[dict] = field(default_factory=list)
    # config
    config: dict = field(default_factory=dict)


def _apply_slippage(price: float, direction: str, slippage: float) -> float:
    """Apply slippage to execution price."""
    if direction == "buy":
        return price * (1 + slippage)
    else:
        return price * (1 - slippage)


def _apply_fee(amount: float, fee_rate: float) -> float:
    """Calculate fee for a trade amount."""
    return amount * fee_rate


def run_backtest(
    candles: list[dict],
    buy_expr: str,
    sell_expr: str,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Run a backtest on candle data with buy/sell factor expressions.

    Args:
        candles: OHLCV data
        buy_expr: Factor expression for buy signal (e.g., "rsi(14) < 30")
        sell_expr: Factor expression for sell signal (e.g., "rsi(14) > 70")
        config: Backtest configuration
    """
    if config is None:
        config = BacktestConfig()

    # evaluate signals
    buy_result = evaluate_expression(buy_expr, candles)
    sell_result = evaluate_expression(sell_expr, candles)

    if buy_result.get("error"):
        raise ValueError(f"Buy expression error: {buy_result['error']}")
    if sell_result.get("error"):
        raise ValueError(f"Sell expression error: {sell_result['error']}")

    if buy_result["type"] != "signal":
        raise ValueError("Buy expression must return a boolean signal")
    if sell_result["type"] != "signal":
        raise ValueError("Sell expression must return a boolean signal")

    buy_signals = buy_result["values"]
    sell_signals = sell_result["values"]

    # align lengths
    n = min(len(candles), len(buy_signals), len(sell_signals))
    candles = candles[-n:]
    buy_signals = buy_signals[-n:]
    sell_signals = sell_signals[-n:]

    # simulation
    capital = config.initial_capital
    position = 0
    entry_price = 0.0
    entry_date = ""
    trades: list[Trade] = []
    equity_curve = []

    for i in range(n):
        c = candles[i]
        price = c["close"]
        date = c["date"]

        # check stop loss / take profit if in position
        if position > 0:
            pnl_pct = (price - entry_price) / entry_price

            exit_reason = ""
            if config.stop_loss_pct and pnl_pct <= -config.stop_loss_pct:
                exit_reason = "stop_loss"
            elif config.take_profit_pct and pnl_pct >= config.take_profit_pct:
                exit_reason = "take_profit"
            elif sell_signals[i]:
                exit_reason = "sell_signal"

            if exit_reason:
                exit_price = _apply_slippage(price, "sell", config.slippage)
                proceeds = position * exit_price
                fee = _apply_fee(proceeds, config.fee_rate)
                capital += proceeds - fee
                pnl = (exit_price - entry_price) * position - fee
                pnl_pct = (exit_price - entry_price) / entry_price

                trades.append(Trade(
                    entry_date=entry_date,
                    entry_price=entry_price,
                    exit_date=date,
                    exit_price=round(exit_price, 4),
                    shares=position,
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct * 100, 2),
                    exit_reason=exit_reason,
                ))
                position = 0
                entry_price = 0.0

        # check buy signal
        if position == 0 and buy_signals[i]:
            buy_price = _apply_slippage(price, "buy", config.slippage)
            shares = int((capital * config.position_size) / buy_price)
            if shares > 0:
                cost = shares * buy_price
                fee = _apply_fee(cost, config.fee_rate)
                capital -= cost + fee
                position = shares
                entry_price = buy_price
                entry_date = date

        # record equity
        total_value = capital + position * price
        equity_curve.append({"date": date, "equity": round(total_value, 2)})

    # close any open position at end
    if position > 0:
        last_price = candles[-1]["close"]
        exit_price = _apply_slippage(last_price, "sell", config.slippage)
        proceeds = position * exit_price
        fee = _apply_fee(proceeds, config.fee_rate)
        capital += proceeds - fee
        pnl = (exit_price - entry_price) * position - fee
        pnl_pct = (exit_price - entry_price) / entry_price
        trades.append(Trade(
            entry_date=entry_date,
            entry_price=entry_price,
            exit_date=candles[-1]["date"],
            exit_price=round(exit_price, 4),
            shares=position,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct * 100, 2),
            exit_reason="end_of_data",
        ))
        equity_curve[-1]["equity"] = round(capital, 2)

    # calculate metrics
    result = _calc_metrics(equity_curve, trades, config)
    result.config = {
        "buy_expr": buy_expr,
        "sell_expr": sell_expr,
        "initial_capital": config.initial_capital,
        "fee_rate": config.fee_rate,
        "slippage": config.slippage,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
    }
    return result


def run_out_of_sample(
    candles: list[dict],
    buy_expr: str,
    sell_expr: str,
    train_ratio: float = 0.6,
    config: BacktestConfig | None = None,
) -> dict:
    """Out-of-sample validation — train on first portion, test on remainder."""
    if config is None:
        config = BacktestConfig()

    n = len(candles)
    if n < 100:
        return {"error": "Need at least 100 candles"}

    split = int(n * train_ratio)
    train_candles = candles[:split]
    test_candles = candles[split:]

    if len(train_candles) < 30 or len(test_candles) < 20:
        return {"error": "Not enough data for train/test split"}

    try:
        train_result = run_backtest(train_candles, buy_expr, sell_expr, config)
        test_result = run_backtest(test_candles, buy_expr, sell_expr, config)
    except ValueError as e:
        return {"error": str(e)}

    # compare in-sample vs out-of-sample
    return_gap = train_result.total_return - test_result.total_return
    sharpe_gap = train_result.sharpe_ratio - test_result.sharpe_ratio

    if abs(return_gap) < 10 and abs(sharpe_gap) < 0.5:
        robustness = "STRONG"
    elif abs(return_gap) < 25 and abs(sharpe_gap) < 1.0:
        robustness = "MODERATE"
    else:
        robustness = "WEAK"

    return {
        "train": {
            "period": f"{train_candles[0]['date']} → {train_candles[-1]['date']}",
            "candles": len(train_candles),
            "total_return": train_result.total_return,
            "annual_return": train_result.annual_return,
            "sharpe_ratio": train_result.sharpe_ratio,
            "max_drawdown": train_result.max_drawdown,
            "win_rate": train_result.win_rate,
            "total_trades": train_result.total_trades,
        },
        "test": {
            "period": f"{test_candles[0]['date']} → {test_candles[-1]['date']}",
            "candles": len(test_candles),
            "total_return": test_result.total_return,
            "annual_return": test_result.annual_return,
            "sharpe_ratio": test_result.sharpe_ratio,
            "max_drawdown": test_result.max_drawdown,
            "win_rate": test_result.win_rate,
            "total_trades": test_result.total_trades,
        },
        "return_gap": round(return_gap, 2),
        "sharpe_gap": round(sharpe_gap, 2),
        "robustness": robustness,
    }


def run_monte_carlo(trades: list[dict], n_simulations: int = 1000, initial_capital: float = 100000) -> dict:
    """Monte Carlo simulation — shuffle trade order to assess robustness."""
    if not trades or len(trades) < 5:
        return {"error": "Need at least 5 trades for Monte Carlo simulation"}

    import numpy as np

    pnls = [t.get("pnl", 0) for t in trades]
    n = len(pnls)

    final_equities = []
    max_drawdowns = []
    sharpe_ratios = []

    for _ in range(n_simulations):
        # shuffle trade order
        shuffled = np.random.permutation(pnls)
        equity = initial_capital
        peak = equity
        max_dd = 0
        returns = []

        for pnl in shuffled:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
            returns.append(pnl / (equity - pnl) if (equity - pnl) > 0 else 0)

        final_equities.append(equity)
        max_drawdowns.append(max_dd * 100)
        if np.std(returns) > 0:
            sharpe_ratios.append(np.mean(returns) / np.std(returns) * np.sqrt(252))
        else:
            sharpe_ratios.append(0)

    final_equities = np.array(final_equities)
    max_drawdowns = np.array(max_drawdowns)
    sharpe_ratios = np.array(sharpe_ratios)

    return {
        "n_simulations": n_simulations,
        "n_trades": n,
        "initial_capital": initial_capital,
        "final_equity": {
            "mean": round(float(np.mean(final_equities)), 2),
            "median": round(float(np.median(final_equities)), 2),
            "p5": round(float(np.percentile(final_equities, 5)), 2),
            "p25": round(float(np.percentile(final_equities, 25)), 2),
            "p75": round(float(np.percentile(final_equities, 75)), 2),
            "p95": round(float(np.percentile(final_equities, 95)), 2),
            "min": round(float(np.min(final_equities)), 2),
            "max": round(float(np.max(final_equities)), 2),
        },
        "max_drawdown": {
            "mean": round(float(np.mean(max_drawdowns)), 2),
            "p5": round(float(np.percentile(max_drawdowns, 5)), 2),
            "p95": round(float(np.percentile(max_drawdowns, 95)), 2),
            "worst": round(float(np.max(max_drawdowns)), 2),
        },
        "sharpe": {
            "mean": round(float(np.mean(sharpe_ratios)), 2),
            "p5": round(float(np.percentile(sharpe_ratios, 5)), 2),
            "p95": round(float(np.percentile(sharpe_ratios, 95)), 2),
        },
        "probability_of_profit": round(float((final_equities > initial_capital).mean()) * 100, 1),
    }


def run_walk_forward(
    candles: list[dict],
    buy_expr: str,
    sell_expr: str,
    train_pct: float = 0.7,
    n_splits: int = 3,
    config: BacktestConfig | None = None,
) -> dict:
    """Walk-forward analysis — train/test split to avoid look-ahead bias."""
    if config is None:
        config = BacktestConfig()

    n = len(candles)
    if n < 100:
        return {"error": "Need at least 100 candles for walk-forward analysis"}

    split_size = n // n_splits
    results = []

    for i in range(n_splits):
        start = i * split_size
        end = min((i + 1) * split_size, n)
        split_candles = candles[start:end]

        if len(split_candles) < 30:
            continue

        train_end = int(len(split_candles) * train_pct)
        test_candles = split_candles[train_end:]

        if len(test_candles) < 10:
            continue

        try:
            r = run_backtest(test_candles, buy_expr, sell_expr, config)
            results.append({
                "split": i + 1,
                "train_size": train_end,
                "test_size": len(test_candles),
                "start_date": test_candles[0]["date"],
                "end_date": test_candles[-1]["date"],
                "total_return": r.total_return,
                "sharpe_ratio": r.sharpe_ratio,
                "max_drawdown": r.max_drawdown,
                "win_rate": r.win_rate,
                "total_trades": r.total_trades,
            })
        except Exception as e:
            results.append({"split": i + 1, "error": str(e)})

    if not results:
        return {"error": "No valid splits"}

    valid = [r for r in results if "error" not in r]
    import numpy as np
    returns = [r["total_return"] for r in valid]
    sharpes = [r["sharpe_ratio"] for r in valid]

    return {
        "n_splits": n_splits,
        "train_pct": train_pct,
        "results": results,
        "avg_return": round(float(np.mean(returns)), 2),
        "avg_sharpe": round(float(np.mean(sharpes)), 2),
        "return_std": round(float(np.std(returns)), 2),
        "consistency": round(float(np.mean([1 if r > 0 else 0 for r in returns])) * 100, 1),
    }


def _calc_metrics(equity_curve: list[dict], trades: list[Trade], config: BacktestConfig) -> BacktestResult:
    """Calculate performance metrics."""
    result = BacktestResult()

    if not equity_curve:
        return result

    equities = [e["equity"] for e in equity_curve]
    initial = config.initial_capital
    final = equities[-1]

    # total return
    result.total_return = round((final - initial) / initial * 100, 2)

    # annualized return
    days = len(equity_curve)
    if days > 1:
        result.annual_return = round(((final / initial) ** (252 / days) - 1) * 100, 2)

    # max drawdown
    peak = equities[0]
    max_dd = 0
    for eq in equities:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak
        if dd > max_dd:
            max_dd = dd
    result.max_drawdown = round(max_dd * 100, 2)

    # Sharpe ratio (daily returns)
    if len(equities) > 1:
        returns = pd.Series(equities).pct_change().dropna()
        if returns.std() > 0:
            result.sharpe_ratio = round((returns.mean() / returns.std()) * np.sqrt(252), 2)

    # trade stats
    result.total_trades = len(trades)
    if trades:
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        result.win_rate = round(len(wins) / len(trades) * 100, 1)

        total_profit = sum(t.pnl for t in wins) if wins else 0
        total_loss = abs(sum(t.pnl for t in losses)) if losses else 0
        result.profit_factor = round(total_profit / total_loss, 2) if total_loss > 0 else 999.99

        result.avg_trade_pnl = round(sum(t.pnl for t in trades) / len(trades), 2)

    result.equity_curve = equity_curve
    result.trades = [
        {
            "entry_date": t.entry_date,
            "entry_price": t.entry_price,
            "exit_date": t.exit_date,
            "exit_price": t.exit_price,
            "shares": t.shares,
            "pnl": t.pnl,
            "pnl_pct": t.pnl_pct,
            "exit_reason": t.exit_reason,
        }
        for t in trades
    ]

    return result
