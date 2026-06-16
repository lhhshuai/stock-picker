"""多因子选股策略：价值 + 成长 + 动量 + 质量 + 波动"""

import numpy as np

from strategies.base import BaseStrategy, StockData
from strategies.fundamental import _safe_get
from strategies.technical import _calc_rsi, _calc_macd


class MultiFactorStrategy(BaseStrategy):
    name = "多因子"
    description = "价值+成长+动量+质量+波动 五因子加权打分"

    def __init__(self, weights: dict = None):
        """
        weights: {"value": 0.25, "growth": 0.25, ...}
        默认使用 config.FACTOR_WEIGHTS
        """
        import config
        self.weights = weights or config.FACTOR_WEIGHTS

    def score(self, data: StockData) -> float:
        if data.daily is None or len(data.daily) < 60:
            return 0.0

        close = data.daily["close"].values.astype(float)
        volume = data.daily["volume"].values.astype(float)
        n = len(close)

        factors = {}

        # ===== 1. 价值因子 =====
        factors["value"] = self._factor_value(data)

        # ===== 2. 成长因子 =====
        factors["growth"] = self._factor_growth(data)

        # ===== 3. 动量因子 =====
        factors["momentum"] = self._factor_momentum(close)

        # ===== 4. 质量因子 =====
        factors["quality"] = self._factor_quality(data, close)

        # ===== 5. 波动因子 =====
        factors["volatility"] = self._factor_volatility(close)

        # 加权求和
        total = 0.0
        for factor_name, weight in self.weights.items():
            total += factors.get(factor_name, 0) * weight

        return min(100, max(0, total))

    def _factor_value(self, data: StockData) -> float:
        """价值因子 (0-100)：低 PE/PB + 高股息"""
        score = 50  # 基准分
        if data.financial is None:
            return score

        f = data.financial
        pe = _safe_get(f, "pe")
        pb = _safe_get(f, "pb")
        dv = _safe_get(f, "dv_ratio")

        # PE 评分
        if pe is not None and pe > 0:
            score += min(25, max(-25, (50 - pe) / 2))
        else:
            score -= 10

        # PB 评分
        if pb is not None and pb > 0:
            score += min(15, max(-15, (3 - pb) * 5))
        else:
            score -= 5

        # 股息率
        if dv is not None and dv > 0:
            score += min(10, dv * 2)

        return score

    def _factor_growth(self, data: StockData) -> float:
        """成长因子 (0-100)：营收/利润增速"""
        score = 50
        if data.financial is None:
            return score

        f = data.financial
        rev_yoy = _safe_get(f, "revenue_yoy")
        prof_yoy = _safe_get(f, "net_profit_yoy")

        if rev_yoy is not None:
            score += min(20, max(-20, rev_yoy / 5))
        if prof_yoy is not None:
            score += min(20, max(-20, prof_yoy / 5))

        return score

    def _factor_momentum(self, close: np.ndarray) -> float:
        """动量因子 (0-100)：短期趋势强度"""
        n = len(close)
        score = 50

        # 短期涨幅
        if n >= 5 and close[-5] > 0:
            pct_5 = (close[-1] - close[-5]) / close[-5] * 100
            score += min(15, max(-15, pct_5 / 2))

        # 中期涨幅
        if n >= 20 and close[-20] > 0:
            pct_20 = (close[-1] - close[-20]) / close[-20] * 100
            score += min(15, max(-15, pct_20 / 4))

        # RSI 趋势
        if n >= 14:
            rsi = _calc_rsi(close, 14)
            rsi_val = rsi[-1]
            if 55 <= rsi_val <= 70:
                score += 10  # 偏强
            elif rsi_val > 70:
                score += 5   # 过热
            elif rsi_val < 40:
                score -= 10  # 偏弱

        # MACD 方向
        if n >= 26:
            _, hist = _calc_macd(close)
            if hist[-1] > 0 and hist[-1] > hist[-2]:
                score += 10

        return score

    def _factor_quality(self, data: StockData, close: np.ndarray) -> float:
        """质量因子 (0-100)：盈利能力 + 稳定性"""
        score = 50

        if data.financial is not None:
            roe = _safe_get(data.financial, "roe_avg")
            if roe is not None and roe > 0:
                score += min(20, roe / 2)
            else:
                score -= 10

        # 价格波动作为质量近似（稳定上涨比大起大落质量好）
        n = len(close)
        if n >= 21:
            recent = close[-20:]
            daily_returns = np.diff(recent) / recent[:-1]
            volatility = np.std(daily_returns)
            if volatility < 0.015:
                score += 15  # 波动率低，质量高
            elif volatility < 0.03:
                score += 10
            else:
                score -= 5

        return score

    def _factor_volatility(self, close: np.ndarray) -> float:
        """波动因子 (0-100)：低波动的股票更稳健"""
        n = len(close)
        if n < 20:
            return 50

        daily_returns = np.diff(close[-60:]) / close[-60:-1]
        volatility = np.std(daily_returns) * np.sqrt(252)  # 年化波动率

        if volatility < 0.20:
            return 80   # 低波
        elif volatility < 0.40:
            return 60   # 中波
        elif volatility < 0.60:
            return 40   # 高波
        else:
            return 20   # 极高波
