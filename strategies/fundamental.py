"""基本面选股策略：估值 + 盈利 + 成长"""

from strategies.base import BaseStrategy, StockData


class FundamentalStrategy(BaseStrategy):
    name = "基本面"
    description = "低估值 + 高ROE + 成长性综合评分"

    def score(self, data: StockData) -> float:
        if data.financial is None:
            return 0.0

        score = 0.0
        f = data.financial  # pandas Series from tushare daily_basic

        # --- 1. 估值评分 (0-25) ---
        pe = _safe_get(f, "pe")
        pb = _safe_get(f, "pb")

        if pe is not None and pe > 0:
            if pe < 10:
                score += 25
            elif pe < 20:
                score += 20
            elif pe < 30:
                score += 15
            elif pe < 50:
                score += 8
            elif pe < 100:
                score += 3
            else:
                score += 0
        else:
            # 亏损或缺省，不给分也不直接过滤
            score += 0

        # PB 加分
        if pb is not None and pb > 0:
            if pb < 1:
                score += 5  # 破净股加分
            elif pb < 2:
                score += 3
            elif pb < 5:
                score += 1
            else:
                score += 0

        # --- 2. 股息率 (0-15) ---
        dv = _safe_get(f, "dv_ratio")  # 股息率
        if dv is not None and dv > 0:
            if dv > 5:
                score += 15
            elif dv > 3:
                score += 12
            elif dv > 2:
                score += 8
            elif dv > 1:
                score += 5
            else:
                score += 2
        else:
            score += 0

        # --- 3. 成长性 (0-30) ---
        # 从 financial 中获取（需要 tushare 利润表数据）
        revenue_yoy = _safe_get(f, "revenue_yoy")
        profit_yoy = _safe_get(f, "net_profit_yoy")

        if revenue_yoy is not None and revenue_yoy > 20:
            score += 10
        elif revenue_yoy is not None and revenue_yoy > 0:
            score += 5
        elif revenue_yoy is None:
            score += 5  # 数据缺失不扣分

        if profit_yoy is not None and profit_yoy > 30:
            score += 10
        elif profit_yoy is not None and profit_yoy > 0:
            score += 5
        elif profit_yoy is None:
            score += 5

        # --- 4. ROE 评分 (0-20) ---
        # 注意: daily_basic 没有 ROE，需要从其他地方获取
        # 这里用 placeholder，实际应从财务指标接口取
        roe = _safe_get(f, "roe_avg")
        if roe is not None:
            if roe > 20:
                score += 20
            elif roe > 15:
                score += 16
            elif roe > 10:
                score += 12
            elif roe > 5:
                score += 6
            else:
                score += 0
        else:
            # 无 ROE 数据时，用市值做近似：小市值公司通常 ROE 不太好看
            total_mv = _safe_get(f, "total_mv")  # 总市值（万元）
            if total_mv is not None:
                if total_mv > 1e6:  # > 100亿，通常较稳健
                    score += 10
                else:
                    score += 5

        # --- 5. 流动性/换手能力 (0-10) ---
        # 日均成交额越大越好
        float_share = _safe_get(f, "float_share")  # 流通股本（万股）
        circ_mv = _safe_get(f, "circ_mv")  # 流通市值（万元）

        if circ_mv is not None and circ_mv > 0:
            # 流通市值适中最好：50亿 - 500亿
            if 500000 < circ_mv < 5000000:
                score += 10
            elif circ_mv >= 100000:
                score += 6
            else:
                score += 3

        return min(100, max(0, score))

    def filter(self, data: StockData) -> bool:
        if data.financial is None:
            return False
        # 排除 ST（可以从 name 判断）
        if "ST" in (data.name or ""):
            return False
        return True


def _safe_get(series, key):
    """安全地从 Series 获取值，处理 NaN/None"""
    try:
        val = series.get(key)
        if val is None:
            return None
        import numpy as np
        import pandas as pd
        if isinstance(val, (np.floating, float)) and (np.isnan(val) or pd.isna(val)):
            return None
        return float(val)
    except Exception:
        return None
