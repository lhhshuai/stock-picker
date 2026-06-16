"""概念板块龙头股数据获取层

功能：
1. 获取热门概念板块排名
2. 获取各板块成分股
3. 筛选龙头股（按成交额+价格强度排序）
"""

import time
from typing import Optional

import pandas as pd

import config
from data.storage import (
    is_cache_fresh_for,
    load_concept_boards,
    load_leader_mapping,
    save_concept_boards,
    save_leader_mapping,
)

# 热门概念板块数量
TOP_CONCEPT_COUNT = 5
# 每个板块选出的龙头股数量
LEADERS_PER_BOARD = 3
# akshare API 调用间隔（秒）
API_DELAY = 1.0


def get_hot_concept_boards() -> pd.DataFrame:
    """
    获取热门概念板块排名。
    返回 DataFrame，列包括: 板块名称, 板块代码, 涨跌幅, 成分股数量等。
    优先从缓存读取，过期则从 akshare 拉取。
    """
    if is_cache_fresh_for("concept_boards"):
        try:
            cached = load_concept_boards()
            if cached is not None and not cached.empty:
                return cached
        except Exception:
            pass

    import akshare as ak

    try:
        df = ak.stock_board_concept_name_em()
        cols_needed = [c for c in ["板块名称", "板块代码", "涨跌幅", "成分股数量"] if c in df.columns]
        if cols_needed:
            df = df[cols_needed].copy()
            df = df.sort_values("涨跌幅", ascending=False).head(TOP_CONCEPT_COUNT).reset_index(drop=True)
        save_concept_boards(df)
        return df
    except Exception as e:
        print(f"[leader_fetcher] 获取概念板块失败: {e}")
        cached = load_concept_boards()
        return cached if cached is not None else pd.DataFrame()


def get_concept_constituents(board_code: str) -> pd.DataFrame:
    """
    获取指定概念板块的成分股列表。
    返回 DataFrame，列包括: 代码, 名称, 涨跌幅, 最新价, 成交额, 换手率 等。
    """
    import akshare as ak

    try:
        df = ak.stock_board_concept_cons_em(symbol=board_code)
        return df
    except Exception as e:
        print(f"[leader_fetcher] 获取板块 [{board_code}] 成分股失败: {e}")
        return pd.DataFrame()


def _calc_leader_score(constituent_df: pd.DataFrame) -> pd.DataFrame:
    """
    在单个概念板块的成分股中，计算每只股票的"龙头得分"。
    龙头得分 = 成交额排名分(40%) + 涨跌幅排名分(30%) + 换手率排名分(30%)
    返回添加了 leader_score 列的 DataFrame，已按分数降序排列。
    """
    if constituent_df.empty:
        return constituent_df

    df = constituent_df.copy()

    # 匹配列名（akshare 返回中文列名）
    amount_col = pct_col = turnover_col = None
    for col in df.columns:
        cl = str(col).lower()
        if "成交" in col and "额" in col:
            amount_col = col
        elif "涨" in col and "幅" in col:
            pct_col = col
        elif "换手" in col:
            turnover_col = col

    # 成交额排名分 (0-40)
    if amount_col and amount_col in df.columns:
        df["_amount_score"] = df[amount_col].rank(ascending=False, pct=True) * 40
    else:
        df["_amount_score"] = 20

    # 涨跌幅排名分 (0-30)
    if pct_col and pct_col in df.columns:
        df["_pct_score"] = df[pct_col].rank(ascending=False, pct=True) * 30
    else:
        df["_pct_score"] = 15

    # 换手率排名分 (0-30)
    if turnover_col and turnover_col in df.columns:
        df["_turnover_score"] = df[turnover_col].rank(ascending=False, pct=True) * 30
    else:
        df["_turnover_score"] = 15

    df["leader_score"] = df["_amount_score"] + df["_pct_score"] + df["_turnover_score"]

    # 清理临时列
    drop_cols = [c for c in df.columns if c.startswith("_")]
    df = df.drop(columns=drop_cols)

    df = df.sort_values("leader_score", ascending=False).reset_index(drop=True)
    return df


def _normalize_code(raw_code: str) -> str:
    """统一股票代码格式为 sh600000 / sz000001"""
    raw_code = str(raw_code).strip()
    if raw_code.startswith(("sh", "SH", "sz", "SZ")):
        return raw_code[:2].lower() + raw_code[2:].zfill(6)
    # 判断沪/深
    if raw_code.startswith("6"):
        market = "SH"
    else:
        market = "SZ"
    return f"{market.lower()}{raw_code.zfill(6)}"


def fetch_leader_stocks() -> dict:
    """
    主入口：获取热门概念板块的龙头股。
    返回 dict: {
        "boards": pd.DataFrame (热门板块列表),
        "leaders": pd.DataFrame (龙头股列表),
        "mapping": dict (code -> board_name 的映射)
    }
    """
    boards = get_hot_concept_boards()
    if boards.empty:
        return {"boards": boards, "leaders": pd.DataFrame(), "mapping": {}}

    all_leaders = []
    mapping = {}

    for _, board_row in boards.iterrows():
        board_code = str(board_row.get("板块代码", ""))
        board_name = str(board_row.get("板块名称", ""))

        if not board_code:
            continue

        constituents = get_concept_constituents(board_code)
        time.sleep(API_DELAY)

        if constituents.empty:
            continue

        scored = _calc_leader_score(constituents)

        # 取前 LEADERS_PER_BOARD 只
        top = scored.head(LEADERS_PER_BOARD)
        for rank, (_, stock_row) in enumerate(top.iterrows(), start=1):
            raw_code = str(stock_row.get("代码", ""))
            code = _normalize_code(raw_code)

            leader_info = {
                "code": code,
                "name": str(stock_row.get("名称", "")),
                "board_code": board_code,
                "board_name": board_name,
                "leader_rank": rank,
                "leader_score": stock_row.get("leader_score", 0),
                "latest_price": stock_row.get("最新价", 0),
                "pct_change": stock_row.get("涨跌幅", 0),
                "amount": stock_row.get("成交额", 0),
            }
            all_leaders.append(leader_info)
            mapping[code] = board_name

        time.sleep(API_DELAY)

    leaders_df = pd.DataFrame(all_leaders) if all_leaders else pd.DataFrame()

    # 持久化缓存
    if not leaders_df.empty:
        save_leader_mapping(leaders_df, mapping)

    return {
        "boards": boards,
        "leaders": leaders_df,
        "mapping": mapping,
    }
