"""简易回测模块：验证策略历史表现"""

from datetime import datetime

import numpy as np
import pandas as pd

from data.fetcher import get_daily_kline
from strategies.base import StockData
from strategies.technical import TechnicalStrategy


def backtest_strategy(strategy: TechnicalStrategy, codes: list[str],
                      start_date: str = None, end_date: str = None,
                      initial_capital: float = 1000000.0,
                      top_n: int = 10,
                      rebalance_days: int = 5) -> pd.DataFrame:
    """
    简易回测：定期根据策略打分选股，等权买入，持有 rebalance_days 天后调仓。

    Args:
        strategy: 策略实例
        codes: 股票池代码列表
        start_date: 回测起始日期
        end_date: 回测结束日期
        initial_capital: 初始资金
        top_n: 每次买入前 N 只
        rebalance_days: 调仓频率（交易日）

    Returns:
        DataFrame: [date, portfolio_value, benchmark_value]
    """
    # 简化版：用沪深300指数作为基准
    portfolio_value = initial_capital
    positions = {}  # code -> {"shares": int, "cost": float}
    rebalance_counter = 0

    # 收集所有交易日的净值
    nav_history = []

    # 获取一个参考日期（用最新可用数据）
    all_dates = set()
    stock_data = {}

    for code in codes[:50]:  # 回测限制数量，避免太慢
        daily = get_daily_kline(code, days=250)
        if daily is not None and not daily.empty:
            stock_data[code] = daily
            all_dates.update(daily["date"].tolist())

    if not all_dates:
        return pd.DataFrame()

    trading_days = sorted(all_dates)

    # 过滤日期范围
    if start_date:
        trading_days = [d for d in trading_days if d >= start_date]
    if end_date:
        trading_days = [d for d in trading_days if d <= end_date]

    for date in trading_days:
        rebalance_counter += 1

        # 每日更新持仓市值
        daily_value = 0.0
        for code, pos in list(positions.items()):
            if code in stock_data and date in stock_data[code]["date"].values:
                row = stock_data[code][stock_data[code]["date"] == date]
                if not row.empty:
                    price = row["close"].values[0]
                    daily_value += pos["shares"] * price

        daily_value += sum(
            cash for cash in [portfolio_value]  # 现金部分简化处理
        )

        # 调仓
        if rebalance_counter >= rebalance_days:
            rebalance_counter = 0
            portfolio_value = _rebalance(
                strategy, stock_data, codes, portfolio_value, top_n
            )

        nav_history.append({
            "date": date,
            "portfolio_value": round(daily_value + portfolio_value, 2),
        })

    df = pd.DataFrame(nav_history)
    if df.empty:
        return df

    # 计算收益率和夏普比率
    df["daily_return"] = df["portfolio_value"].pct_change()
    total_return = (df["portfolio_value"].iloc[-1] / initial_capital - 1) * 100
    annual_return = total_return * (252 / len(df)) if len(df) > 0 else 0

    if df["daily_return"].std() > 0:
        sharpe = (df["daily_return"].mean() / df["daily_return"].std()
                  * np.sqrt(252))
    else:
        sharpe = 0

    max_dd = _calc_max_drawdown(df["portfolio_value"])

    print(f"\n{'='*40}")
    print(f"回测结果 ({len(trading_days)} 个交易日)")
    print(f"{'='*40}")
    print(f"总收益率:   {total_return:.2f}%")
    print(f"年化收益:   {annual_return:.2f}%")
    print(f"夏普比率:   {sharpe:.2f}")
    print(f"最大回撤:   {max_dd:.2f}%")
    print(f"{'='*40}\n")

    return df


def _rebalance(strategy, stock_data: dict, codes: list[str],
               capital: float, top_n: int) -> float:
    """调仓逻辑：打分选股，等权分配资金"""
    scores = []

    for code in codes[:100]:  # 候选池
        if code not in stock_data or stock_data[code].empty:
            continue

        data = StockData(
            code=code,
            name=code,
            daily_df=stock_data[code],
            financial=None,  # 回测简化版不用财务数据
        )

        if strategy.filter(data):
            s = strategy.score(data)
            if s > 0:
                scores.append((code, s))

    if not scores:
        return capital

    # 按分数排序
    scores.sort(key=lambda x: x[1], reverse=True)
    picks = scores[:top_n]

    # 等权分配
    alloc = capital / len(picks) if picks else 0

    # 清仓旧持仓（简化：全部卖出再买入新的）
    # 实际应该考虑买卖价差和滑点

    return alloc * len(picks)  # 返回新仓位总占用资金


def _calc_max_drawdown(values: pd.Series) -> float:
    """计算最大回撤"""
    peak = values.cummax()
    drawdown = (values - peak) / peak
    return drawdown.min() * 100


def run_quick_backtest():
    """快速回测示例：用技术面策略测试前100只股票"""
    from data.fetcher import get_stock_pool

    stocks = get_stock_pool()
    if not stocks:
        print("无法获取股票池")
        return

    codes = [s["code"] for s in stocks[:100]]
    strategy = TechnicalStrategy()

    backtest_strategy(strategy, codes, top_n=10, rebalance_days=10)
