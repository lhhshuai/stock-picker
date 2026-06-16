"""技术面选股策略：均线 + MACD + RSI + 成交量"""

import numpy as np
import pandas as pd

from strategies.base import BaseStrategy, StockData


class TechnicalStrategy(BaseStrategy):
    name = "技术面"
    description = "均线排列 + MACD + RSI + 成交量综合评分"

    def __init__(self, short_ma: int = 5, mid_ma: int = 20, long_ma: int = 60):
        self.short_ma = short_ma
        self.mid_ma = mid_ma
        self.long_ma = long_ma

    def score(self, data: StockData) -> float:
        if data.daily is None or len(data.daily) < 30:
            return 0.0

        close = data.daily["close"].values.astype(float)
        volume = data.daily["volume"].values.astype(float)
        n = len(close)

        score = 0.0

        # --- 1. 均线多头排列 (0-25) ---
        ma_short = np.mean(close[-self.short_ma:])
        ma_mid = np.mean(close[-self.mid_ma:])
        ma_long = np.mean(close[-self.long_ma:])

        # 完美多头排列: short > mid > long
        if ma_short > ma_mid > ma_long:
            score += 25
        elif ma_short > ma_mid:
            score += 15
        elif close[-1] > ma_long:
            score += 10
        else:
            score += 0

        # 均线斜率（近期加速向上加分）
        ma_short_early = np.mean(close[-self.short_ma * 2: -self.short_ma])
        if ma_short > ma_short_early:
            score += 5  # 短线趋势向上

        # --- 2. MACD (0-25) ---
        macd_signal, macd_hist = _calc_macd(close)

        if n >= 2:
            # 金叉或红柱放大
            if macd_hist[-1] > 0 and macd_hist[-1] > macd_hist[-2]:
                score += 15  # 红柱放大，强势
            elif macd_hist[-1] > 0:
                score += 10  # 红柱但缩小
            elif macd_hist[-1] < 0 and macd_hist[-1] > macd_hist[-2]:
                score += 10  # 绿柱缩短，可能反转
            elif macd_hist[-1] < 0 and macd_hist[-2] <= 0 and macd_hist[-1] > 0:
                score += 20  # 刚刚金叉

            # DIF > DEA (MACD 线在信号线上方)
            if macd_signal[-1] > 0:
                score += 5

        # --- 3. RSI (0-20) ---
        rsi = _calc_rsi(close, period=14)
        if n >= 14:
            rsi_val = rsi[-1]
            if 40 <= rsi_val <= 70:
                score += 20  # 健康区间
            elif 30 <= rsi_val < 40:
                score += 15  # 偏低但未超卖
            elif 70 < rsi_val <= 80:
                score += 5   # 偏热但还有空间
            elif rsi_val < 30:
                score += 10  # 超卖可能反弹
            else:
                score += 0   # 严重超买

        # --- 4. 成交量 (0-20) ---
        vol_avg_5 = np.mean(volume[-5:])
        vol_avg_20 = np.mean(volume[-20:]) if n >= 20 else vol_avg_5

        if vol_avg_20 > 0:
            vol_ratio = vol_avg_5 / vol_avg_20
            if 1.2 <= vol_ratio <= 3.0:
                score += 15  # 温和放量，最好
            elif vol_ratio > 3.0:
                score += 5   # 放量过大，可能是出货
            elif vol_ratio >= 0.8:
                score += 10  # 量能正常
            else:
                score += 5   # 缩量

        # --- 5. 近 N 日涨幅趋势 (0-10) ---
        if n >= 10 and close[-2] > 0:
            pct_10 = (close[-1] - close[-10]) / close[-10] * 100
            if 0 < pct_10 < 30:
                score += 10
            elif 30 <= pct_10 < 50:
                score += 5
            elif pct_10 < -10:
                score += 0  # 大幅下跌不推荐

        return min(100, max(0, score))

    def filter(self, data: StockData) -> bool:
        """基础过滤：股价 > 3 元，至少 20 天数据"""
        if data.daily is None or len(data.daily) < 20:
            return False
        if data.daily["close"].iloc[-1] < 3:
            return False
        return True


def _calc_macd(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    """计算 MACD 的 DEA(信号线) 和 histogram"""
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    dif = ema_fast - ema_slow
    dea = _ema(dif, signal)
    hist = 2 * (dif - dea)
    return dea, hist


def _calc_rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """计算 RSI"""
    delta = np.diff(close)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    rsi = np.full(len(close), 50.0)  # 默认 50

    if len(gain) < period:
        return rsi

    avg_gain = np.mean(gain[:period])
    avg_loss = np.mean(loss[:period])

    if avg_loss == 0:
        rsi[period:] = 100.0
        return rsi

    rs = avg_gain / avg_loss
    rsi[period] = 100.0 - 100.0 / (1.0 + rs)

    for i in range(period + 1, len(gain)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - 100.0 / (1.0 + rs)

    return rsi


def _ema(series: np.ndarray, period: int) -> np.ndarray:
    """计算 EMA"""
    result = np.full(len(series), np.nan)
    if len(series) == 0:
        return result
    result[0] = series[0]
    multiplier = 2.0 / (period + 1)
    for i in range(1, len(series)):
        result[i] = (series[i] - result[i - 1]) * multiplier + result[i - 1]
    return result
