"""概念板块龙头股数据获取层

功能：
1. 获取热门概念板块排名
2. 获取各板块成分股
3. 筛选龙头股（按成交额+价格强度排序）
"""

import time
from typing import Optional

import pandas as pd
import requests

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

# 请求头（伪装浏览器）
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.eastmoney.com/",
    "Accept": "application/json, text/plain, */*",
}


def get_hot_concept_boards() -> pd.DataFrame:
    """
    获取热门概念板块排名。
    优先 akshare，失败则返回空 DataFrame（龙头筛选降级为不生效）。
    """
    if is_cache_fresh_for("concept_boards"):
        try:
            cached = load_concept_boards()
            if cached is not None and not cached.empty:
                return cached
        except Exception:
            pass

    # 方案1: akshare
    try:
        import akshare as ak
        df = ak.stock_board_concept_name_em()
        cols_needed = [c for c in ["板块名称", "板块代码", "涨跌幅", "成分股数量"] if c in df.columns]
        if cols_needed:
            df = df[cols_needed].copy()
            df = df.sort_values("涨跌幅", ascending=False).head(TOP_CONCEPT_COUNT).reset_index(drop=True)
        save_concept_boards(df)
        return df
    except Exception as e:
        print(f"[leader_fetcher] akshare 板块获取失败: {e}")

    # 方案2: 直连东方财富
    try:
        boards = _fetch_direct_concept_boards()
        if not boards.empty:
            save_concept_boards(boards)
            return boards
    except Exception as e:
        print(f"[leader_fetcher] 直连东方财富板块失败: {e}")

    print("[leader_fetcher] 概念板块数据获取失败，龙头筛选将降级为不生效")
    cached = load_concept_boards()
    return cached if cached is not None else pd.DataFrame()


def _fetch_direct_concept_boards() -> pd.DataFrame:
    """直连东方财富概念板块排名 API"""
    boards = []
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "50", "po": "1", "np": "1", "fltt": "2",
            "invt": "2", "fid": "f3", "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024",
            "fields": "f1,f2,f3,f4,f12,f14,f15,f16",
        }
        r = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("data") and data["data"].get("diff"):
                for item in data["data"]["diff"]:
                    boards.append({
                        "板块名称": item.get("f14", ""),
                        "板块代码": item.get("f12", ""),
                        "涨跌幅": item.get("f3", 0),
                        "成分股数量": item.get("f15", 0),
                    })
        if boards:
            df = pd.DataFrame(boards)
            df = df.sort_values("涨跌幅", ascending=False).head(TOP_CONCEPT_COUNT)
            return df.reset_index(drop=True)
    except Exception as e:
        print(f"[leader_fetcher] 直连板块API失败: {e}")
    return pd.DataFrame()


def get_concept_constituents(board_code: str) -> pd.DataFrame:
    """
    获取指定概念板块的成分股列表。
    """
    # 方案1: akshare
    try:
        import akshare as ak
        df = ak.stock_board_concept_cons_em(symbol=board_code)
        if not df.empty:
            return df
    except Exception as e:
        print(f"[leader_fetcher] akshare 成分股获取失败: {e}")

    # 方案2: 直连东方财富
    try:
        df = _fetch_direct_constituents(board_code)
        if not df.empty:
            return df
    except Exception as e:
        print(f"[leader_fetcher] 直连成分股API失败: {e}")

    return pd.DataFrame()


def _fetch_direct_constituents(board_code: str) -> pd.DataFrame:
    """直连东方财富获取概念板块成分股"""
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "200", "po": "1", "np": "1", "fltt": "2",
            "invt": "2", "fid": "f3", "fs": f"b:{board_code}",
            "fields": "f2,f3,f4,f5,f6,f12,f14",
        }
        r = requests.get(url, params=params, headers=_HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if data.get("data") and data["data"].get("diff"):
                records = []
                for item in data["data"]["diff"]:
                    records.append({
                        "代码": item.get("f12", ""),
                        "名称": item.get("f14", ""),
                        "最新价": item.get("f2", 0),
                        "涨跌幅": item.get("f3", 0),
                        "成交额": item.get("f6", 0),
                        "换手率": item.get("f5", 0),
                    })
                if records:
                    return pd.DataFrame(records)
    except Exception as e:
        print(f"[leader_fetcher] 直连成分股解析失败: {e}")
    return pd.DataFrame()


def _calc_leader_score(constituent_df: pd.DataFrame) -> pd.DataFrame:
    """
    在单个概念板块的成分股中，计算每只股票的"龙头得分"。
    龙头得分 = 成交额排名分(40%) + 涨跌幅排名分(30%) + 换手率排名分(30%)
    """
    if constituent_df.empty:
        return constituent_df

    df = constituent_df.copy()

    amount_col = pct_col = turnover_col = None
    for col in df.columns:
        cl = str(col).lower()
        if "成交" in col and "额" in col:
            amount_col = col
        elif "涨" in col and "幅" in col:
            pct_col = col
        elif "换手" in col:
            turnover_col = col

    if amount_col and amount_col in df.columns:
        df["_amount_score"] = df[amount_col].rank(ascending=False, pct=True) * 40
    else:
        df["_amount_score"] = 20

    if pct_col and pct_col in df.columns:
        df["_pct_score"] = df[pct_col].rank(ascending=False, pct=True) * 30
    else:
        df["_pct_score"] = 15

    if turnover_col and turnover_col in df.columns:
        df["_turnover_score"] = df[turnover_col].rank(ascending=False, pct=True) * 30
    else:
        df["_turnover_score"] = 15

    df["leader_score"] = df["_amount_score"] + df["_pct_score"] + df["_turnover_score"]

    drop_cols = [c for c in df.columns if c.startswith("_")]
    df = df.drop(columns=drop_cols)
    df = df.sort_values("leader_score", ascending=False).reset_index(drop=True)
    return df


def _normalize_code(raw_code: str) -> str:
    """统一股票代码格式为 sh600000 / sz000001"""
    raw_code = str(raw_code).strip()
    if raw_code.startswith(("sh", "SH", "sz", "SZ")):
        return raw_code[:2].lower() + raw_code[2:].zfill(6)
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

    if not leaders_df.empty:
        save_leader_mapping(leaders_df, mapping)

    return {
        "boards": boards,
        "leaders": leaders_df,
        "mapping": mapping,
    }
