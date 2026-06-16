"""龙头股策略：在基础策略之上叠加龙头加成"""

import numpy as np

from strategies.base import BaseStrategy, StockData
from strategies.multifactor import MultiFactorStrategy
from strategies.technical import TechnicalStrategy, _calc_macd, _calc_rsi


class LeaderStrategy(BaseStrategy):
    """
    龙头股策略：包装一个基础策略，对概念板块龙头股给予加成。

    规则：
    1. 如果是概念板块龙头，总分 +leader_bonus
    2. 需要成交量确认（近期放量）
    """

    name = "龙头策略"
    description = "概念板块龙头股加成策略"

    def __init__(
        self,
        base_strategy: BaseStrategy = None,
        leader_bonus: float = 8.0,
        min_leader_rank: int = 3,
        volume_confirm_days: int = 5,
    ):
        self.base_strategy = base_strategy or MultiFactorStrategy()
        self.leader_bonus = leader_bonus
        self.min_leader_rank = min_leader_rank
        self.volume_confirm_days = volume_confirm_days

    def score(self, data: StockData) -> float:
        if data.daily is None or len(data.daily) < 30:
            return 0.0

        # 1. 基础策略打分
        base_score = self.base_strategy.score(data)

        # 2. 龙头加成判定
        leader_bonus = self._check_leader_premium(data)

        # 3. 成交量确认
        volume_confirmed = self._volume_confirmation(data)

        if leader_bonus > 0 and volume_confirmed:
            return min(100, max(0, base_score + leader_bonus))
        else:
            return base_score

    def _check_leader_premium(self, data: StockData) -> float:
        """检查是否为概念板块龙头股"""
        if data.board_name and data.leader_rank is not None:
            if data.leader_rank <= self.min_leader_rank:
                return self.leader_bonus
        return 0.0

    def _volume_confirmation(self, data: StockData) -> bool:
        """成交量确认：近期均量 >= 20日均量的1.2倍"""
        if data.daily is None or len(data.daily) < self.volume_confirm_days + 20:
            return True

        vol_recent = data.daily["volume"].tail(self.volume_confirm_days).mean()
        vol_20 = data.daily["volume"].tail(20).mean()

        if vol_20 <= 0:
            return True

        return vol_recent >= vol_20 * 1.2

    def filter(self, data: StockData) -> bool:
        """沿用基础策略的过滤条件"""
        return self.base_strategy.filter(data)


class LeaderTechnicalStrategy(TechnicalStrategy):
    """
    龙头技术面策略：在 TechnicalStrategy 基础上增加动量权重和板块加成。
    与普通技术面策略的区别：均线/MACD 权重更高，适合龙头股强势特征。
    """

    name = "龙头技术面"
    description = "增强动量的龙头技术面策略"

    def __init__(
        self,
        sector_bonus: float = 5.0,
    ):
        super().__init__()
        self.sector_bonus = sector_bonus

    def score(self, data: StockData) -> float:
        if data.daily is None or len(data.daily) < self.long_ma + 10:
            return 0.0

        close = data.daily["close"].values.astype(float)
        volume = data.daily["volume"].values.astype(float)
        n = len(close)

        score = 0.0

        # --- 1. 均线多头排列 (0-30，比普通策略多5分) ---
        ma_short = np.mean(close[-self.short_ma:])
        ma_mid = np.mean(close[-self.mid_ma:])
        ma_long = np.mean(close[-self.long_ma:])

        if ma_short > ma_mid > ma_long:
            score += 30
        elif ma_short > ma_mid:
            score += 18
        elif close[-1] > ma_long:
            score += 12
        else:
            score += 0

        ma_short_early = np.mean(close[-self.short_ma * 2: -self.short_ma])
        if ma_short > ma_short_early:
            score += 8

        # --- 2. MACD (0-30，比普通策略多5分) ---
        macd_signal, macd_hist = _calc_macd(close)

        if n >= 2:
            if macd_hist[-1] > 0 and macd_hist[-1] > macd_hist[-2]:
                score += 20
            elif macd_hist[-1] > 0:
                score += 12
            elif macd_hist[-1] < 0 and macd_hist[-1] > macd_hist[-2]:
                score += 12
            elif macd_hist[-1] < 0 and macd_hist[-2] <= 0 and macd_hist[-1] > 0:
                score += 25

            if macd_signal[-1] > 0:
                score += 8

        # --- 3. RSI (0-20，不变) ---
        rsi = _calc_rsi(close, period=14)
        if n >= 14:
            rsi_val = rsi[-1]
            if 40 <= rsi_val <= 70:
                score += 20
            elif 30 <= rsi_val < 40:
                score += 15
            elif 70 < rsi_val <= 80:
                score += 5
            elif rsi_val < 30:
                score += 10
            else:
                score += 0

        # --- 4. 成交量 (0-20，不变) ---
        vol_avg_5 = np.mean(volume[-5:])
        vol_avg_20 = np.mean(volume[-20:]) if n >= 20 else vol_avg_5

        if vol_avg_20 > 0:
            vol_ratio = vol_avg_5 / vol_avg_20
            if 1.2 <= vol_ratio <= 3.0:
                score += 15
            elif vol_ratio > 3.0:
                score += 5
            elif vol_ratio >= 0.8:
                score += 10
            else:
                score += 5

        # --- 5. 近 N 日涨幅 (0-10，不变) ---
        if n >= 10 and close[-2] > 0:
            pct_10 = (close[-1] - close[-10]) / close[-10] * 100
            if 0 < pct_10 < 30:
                score += 10
            elif 30 <= pct_10 < 50:
                score += 5
            elif pct_10 < -10:
                score += 0

        # --- 6. 板块热度加成 (0-5) ---
        if data.board_name:
            score += self.sector_bonus

        return min(100, max(0, score))

    def filter(self, data: StockData) -> bool:
        """放宽过滤条件：股价 > 2 元，上市 > 30 天"""
        if data.daily is None or len(data.daily) < 30:
            return False
        if data.daily["close"].iloc[-1] < 2:
            return False
        return True
