"""技术指标计算工具函数"""

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """简单移动平均线"""
    return series.rolling(window=window).mean()


def ema(series: pd.Series, window: int) -> pd.Series:
    """指数移动平均线"""
    return series.ewm(span=window, adjust=False).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    计算 MACD。
    返回 (dif, dea, hist) 三个 Series
    """
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    dif = ema_fast - ema_slow
    dea = ema(dif, signal)
    hist = 2 * (dif - dea)
    return dif, dea, hist


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(lower=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def bollinger_bands(series: pd.Series, window: int = 20, num_std: float = 2.0):
    """
    计算布林带。
    返回 (mid, upper, lower) 三个 Series
    """
    mid = sma(series, window)
    std = series.rolling(window=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """计算平均真实波幅 (ATR)"""
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()


def volume_ratio(volume: pd.Series, short: int = 5, long: int = 20) -> pd.Series:
    """量比：短期均量 / 长期均量"""
    return sma(volume, short) / sma(volume, long)


def golden_cross(short_ma: pd.Series, long_ma: pd.Series):
    """
    检测金叉/死叉。
    返回信号序列: 1=金叉, -1=死叉, 0=无信号
    """
    signal = pd.Series(0, index=short_ma.index, dtype=int)
    cross = short_ma - long_ma
    # 金叉: 之前 <=0, 现在 >0
    signal[(cross > 0) & (cross.shift(1) <= 0)] = 1
    # 死叉: 之前 >=0, 现在 <0
    signal[(cross < 0) & (cross.shift(1) >= 0)] = -1
    return signal
