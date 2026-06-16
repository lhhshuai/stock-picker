"""策略基类"""

from abc import ABC, abstractmethod


class StockData:
    """策略输入的数据封装"""
    def __init__(
        self,
        code: str,
        name: str,
        daily_df,
        financial=None,
        board_name: str = None,    # 所属概念板块名称
        leader_rank: int = None,   # 在板块内的龙头排名（1=最强）
    ):
        self.code = code
        self.name = name
        self.daily = daily_df  # DataFrame: [date, open, high, low, close, volume, ...]
        self.financial = financial  # Series/Dict: [pe, pb, roe, ...]
        self.board_name = board_name
        self.leader_rank = leader_rank


class BaseStrategy(ABC):
    """所有策略的基类"""

    name: str = "Base"
    description: str = ""

    @abstractmethod
    def score(self, data: StockData) -> float:
        """
        对单只股票打分，返回 0-100。
        分数越高越值得买入。
        """
        ...

    def filter(self, data: StockData) -> bool:
        """
        前置过滤条件，不满足直接跳过（不参与打分）。
        默认不过滤。
        """
        return True


class CompositeStrategy:
    """组合策略：多个子策略加权综合"""

    def __init__(self, strategies: list[tuple[BaseStrategy, float]]):
        """
        strategies: [(strategy_instance, weight), ...]
        weights 会自动归一化
        """
        self.strategies = strategies
        total_w = sum(w for _, w in strategies)
        self.weights = [w / total_w for _, w in strategies]

    def score(self, data: StockData) -> float:
        if not data.daily or len(data.daily) < 30:
            return 0.0
        return sum(
            s.score(data) * w
            for (s, _), w in zip(self.strategies, self.weights)
        )

    def filter(self, data: StockData) -> bool:
        return all(s.filter(data) for s, _ in self.strategies)
