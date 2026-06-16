"""数据获取层：akshare 为主，tushare 为辅"""

import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

import config
from data.storage import (
    init_db,
    is_cache_fresh,
    load_daily_kline,
    save_daily_kline,
    save_stock_list,
    load_stock_list,
)

init_db()


def get_stock_pool() -> list[dict]:
    """
    获取 A 股股票池。
    返回 [{"code": "sh600000", "name": "浦发银行", "market": "SH"}, ...]
    """
    # 先从缓存加载
    cached = load_stock_list()
    if len(cached) > 1500:  # A 股约 5000+ 只
        return cached

    import akshare as ak

    try:
        # 实时行情获取全部 A 股
        df = ak.stock_zh_a_spot_em()
        stocks = []
        for _, row in df.iterrows():
            code_raw = row["代码"]
            market = "SH" if code_raw.startswith(("6", "sh")) else "SZ"
            # 统一为 sh600000 / sz000001 格式
            code = f"{market.lower()}{code_raw.zfill(6)}"
            stocks.append({
                "code": code,
                "name": row.get("名称", ""),
                "market": market,
            })
        save_stock_list(stocks)
        return stocks
    except Exception as e:
        print(f"[fetcher] 获取股票池失败: {e}")
        return cached


def get_daily_kline(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """
    获取单只股票的日 K 线。
    优先读缓存，过期则从 akshare 拉取并写入缓存。
    返回 DataFrame: [date, open, high, low, close, volume, amount,
                      amplitude, pct_change, price_change, turnover_pct]
    """
    # 尝试从缓存读取
    if is_cache_fresh(code):
        try:
            return load_daily_kline(code, days)
        except Exception:
            pass  # 缓存损坏则重新拉取

    import akshare as ak

    try:
        # 映射 code 到 akshare 格式
        ak_code = code[2:].zfill(6)  # sh600000 -> 600000

        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")

        df = ak.stock_zh_a_hist(
            symbol=ak_code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",  # 前复权
        )

        if df.empty:
            return None

        # 统一列名
        df = df.rename(columns={
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "pct_change",
            "涨跌额": "price_change",
            "换手率": "turnover_pct",
        })

        # 只保留最近 days 天
        df = df.tail(days).copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        # 写入缓存
        save_daily_kline(code, df)

        return df

    except Exception as e:
        print(f"[fetcher] 获取 {code} 日K线失败: {e}")
        return None


def get_financial_data(code: str) -> Optional[pd.DataFrame]:
    """
    获取财务数据（估值 & 盈利指标）。
    需要 tushare pro 权限。如果没有 token 则返回 None。
    返回 DataFrame 包含: pe, pb, roe, revenue_yoy, profit_yoy 等
    """
    if not config.TUSHARE_TOKEN:
        return None

    import tushare as ts

    pro = ts.pro_api(config.TUSHARE_TOKEN)

    ts_code = code[2:].upper() + ".SH" if code.startswith("sh") else code[2:].upper() + ".SZ"

    try:
        # 估值指标
        indicator = pro.daily_basic(
            ts_code=ts_code,
            fields="ts_code,trade_date,pe,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
                   "total_share,float_share,free_share,total_mv,circ_mv",
        )

        if indicator.empty:
            return None

        # 取最新一条
        latest = indicator.sort_values("trade_date", ascending=False).iloc[0]

        # 净利润同比增速（利润表）
        try:
            profit = pro.performance_express(
                ts_code=ts_code,
                fields="ts_code,report_date,net_profit_yoy,revenue_yoy",
            )
            if not profit.empty:
                latest = pd.concat([
                    pd.Series(latest),
                    profit.sort_values("report_date", ascending=False).iloc[0][
                        ["report_date", "net_profit_yoy", "revenue_yoy"]
                    ],
                ])
        except Exception:
            pass

        return latest

    except Exception as e:
        print(f"[fetcher] 获取 {code} 财务数据失败: {e}")
        return None


def get_batch_financial(stocks: list[dict], batch_size: int = 100) -> pd.DataFrame:
    """批量获取财务数据，带限流"""
    if not config.TUSHARE_TOKEN:
        return pd.DataFrame()

    import tushare as ts

    pro = ts.pro_api(config.TUSHARE_TOKEN)
    all_rows = []

    codes = [s["code"] for s in stocks]
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        ts_codes = [c[2:].upper() + (".SH" if c.startswith("sh") else ".SZ") for c in batch]
        try:
            df = pro.daily_basic(
                ts_code=",".join(ts_codes),
                fields="ts_code,trade_date,pe,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
                       "total_share,float_share,free_share,total_mv,circ_mv",
            )
            if not df.empty:
                all_rows.append(df)
        except Exception as e:
            print(f"[fetcher] 批量获取财务数据失败: {e}")

        time.sleep(0.5)  # 限流

    if all_rows:
        return pd.concat(all_rows, ignore_index=True)
    return pd.DataFrame()


def get_stock_pool_with_leaders() -> list[dict]:
    """
    获取股票池，附加概念板块龙头信息。
    返回增强的股票列表，每个 dict 可能包含:
    - board_name: 所属概念板块
    - leader_rank: 龙头排名（1=最强）
    - is_leader: 是否为龙头股
    """
    stocks = get_stock_pool()
    if not stocks:
        return stocks

    from data.leader_fetcher import fetch_leader_stocks

    leader_data = fetch_leader_stocks()
    leaders_df = leader_data.get("leaders", pd.DataFrame())
    mapping = leader_data.get("mapping", {})

    # 构建 code -> leader_rank 快速查找
    rank_lookup = {}
    if not leaders_df.empty:
        for _, row in leaders_df.iterrows():
            rank_lookup[row["code"]] = int(row["leader_rank"])

    # 为股票池附加板块信息
    for stock in stocks:
        code = stock["code"]
        if code in rank_lookup:
            stock["board_name"] = mapping.get(code)
            stock["leader_rank"] = rank_lookup[code]
            stock["is_leader"] = True
        else:
            stock["board_name"] = None
            stock["leader_rank"] = None
            stock["is_leader"] = False

    return stocks
