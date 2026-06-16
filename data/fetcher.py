"""数据获取层：新浪 + 东方财富双数据源

由于东方财富 push2 API 对非浏览器请求有反爬，
优先使用新浪行情 API，akshare 作为备选。
"""

import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

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

# 请求头
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.sina.com.cn/",
}

# 硬编码股票池（当所有网络请求都失败时的降级方案）
_STOCK_POOL_FALLBACK = [
    {"code": "sh600519", "name": "贵州茅台", "market": "SH"},
    {"code": "sz000858", "name": "五粮液", "market": "SZ"},
    {"code": "sh601318", "name": "中国平安", "market": "SH"},
    {"code": "sz000001", "name": "平安银行", "market": "SZ"},
    {"code": "sh600036", "name": "招商银行", "market": "SH"},
    {"code": "sz000333", "name": "美的集团", "market": "SZ"},
    {"code": "sz002594", "name": "比亚迪", "market": "SZ"},
    {"code": "sh600900", "name": "长江电力", "market": "SH"},
    {"code": "sz300750", "name": "宁德时代", "market": "SZ"},
    {"code": "sh601012", "name": "隆基绿能", "market": "SH"},
    {"code": "sz002475", "name": "立讯精密", "market": "SZ"},
    {"code": "sh600276", "name": "恒瑞医药", "market": "SH"},
    {"code": "sz000651", "name": "格力电器", "market": "SZ"},
    {"code": "sh601166", "name": "兴业银行", "market": "SH"},
    {"code": "sz002714", "name": "牧原股份", "market": "SZ"},
    {"code": "sh600809", "name": "山西汾酒", "market": "SH"},
    {"code": "sz000568", "name": "泸州老窖", "market": "SZ"},
    {"code": "sh601899", "name": "紫金矿业", "market": "SH"},
    {"code": "sz000625", "name": "长安汽车", "market": "SZ"},
    {"code": "sz300059", "name": "东方财富", "market": "SZ"},
    {"code": "sh600000", "name": "浦发银行", "market": "SH"},
    {"code": "sz002415", "name": "海康威视", "market": "SZ"},
    {"code": "sz002304", "name": "科大讯飞", "market": "SZ"},
    {"code": "sh601398", "name": "工商银行", "market": "SH"},
    {"code": "sz002371", "name": "北方华创", "market": "SZ"},
    {"code": "sh601288", "name": "农业银行", "market": "SH"},
    {"code": "sh601668", "name": "中国建筑", "market": "SH"},
    {"code": "sz300015", "name": "爱尔眼科", "market": "SZ"},
    {"code": "sh600887", "name": "伊利股份", "market": "SH"},
    {"code": "sz002352", "name": "顺丰控股", "market": "SZ"},
    {"code": "sh600030", "name": "中信证券", "market": "SH"},
    {"code": "sz002142", "name": "宁波银行", "market": "SZ"},
    {"code": "sh601601", "name": "中国太保", "market": "SH"},
    {"code": "sh600585", "name": "海螺水泥", "market": "SH"},
    {"code": "sz002532", "name": "天齐锂业", "market": "SZ"},
]


def get_stock_pool() -> list[dict]:
    """获取 A 股股票池。优先缓存，网络不通时用硬编码列表。"""
    cached = load_stock_list()
    if len(cached) > 5000:
        return cached

    # 方案1: akshare
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        stocks = []
        for _, row in df.iterrows():
            code_raw = row["代码"]
            market = "SH" if code_raw.startswith(("6", "sh")) else "SZ"
            code = f"{market.lower()}{code_raw.zfill(6)}"
            stocks.append({
                "code": code,
                "name": row.get("名称", ""),
                "market": market,
            })
        if len(stocks) > 5000:
            save_stock_list(stocks)
            return stocks
        print(f"[fetcher] akshare 获取到 {len(stocks)} 只")
    except Exception as e:
        print(f"[fetcher] akshare 失败: {e}")

    # 降级到硬编码列表
    print(f"[fetcher] 使用硬编码降级列表 ({len(_STOCK_POOL_FALLBACK)} 只)")
    return _STOCK_POOL_FALLBACK


def get_daily_kline(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """
    获取日 K 线。
    优先读缓存 → 腾讯 K 线 API → akshare → 返回 None
    """
    if is_cache_fresh(code):
        try:
            return load_daily_kline(code, days)
        except Exception:
            pass

    ak_code = code[2:].zfill(6)

    # 方案1: 腾讯 K 线 API（qfq 前复权）
    try:
        df = _fetch_tencent_kline(code, ak_code, days)
        if df is not None:
            save_daily_kline(code, df)
            return df
    except Exception as e:
        print(f"[fetcher] 腾讯 K线失败 ({code}): {e}")

    # 方案2: akshare
    try:
        import akshare as ak
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")

        df = ak.stock_zh_a_hist(
            symbol=ak_code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )

        if not df.empty:
            df = _rename_akshare_columns(df)
            df = df.tail(days).copy()
            save_daily_kline(code, df)
            return df
    except Exception as e:
        print(f"[fetcher] akshare K线失败 ({code}): {e}")

    return None


def _fetch_tencent_kline(code: str, ak_code: str, days: int) -> Optional[pd.DataFrame]:
    """从腾讯财经获取前复权日 K 线"""
    try:
        # 参数格式: param=sh600519,day,,,count,qfq（必须带 sh/sz 前缀）
        url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return None

        data = r.json()
        inner = data.get("data")
        if not isinstance(inner, dict):
            return None

        # 腾讯返回 key 格式: data.{code}.qfqday
        # 例如: data.sh600519 -> {qfqday: [...], qt: {...}, ...}
        klines = None
        for k in inner:
            v = inner.get(k)
            if isinstance(v, dict) and "qfqday" in v:
                klines = v["qfqday"]
                break

        if not klines:
            return None

        records = []
        for k in klines:
            if not isinstance(k, (list, tuple)) or len(k) < 6:
                continue
            records.append({
                "date": str(k[0]),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "amount": 0,
                "amplitude": 0,
                "pct_change": 0,
                "price_change": 0,
                "turnover_pct": 0,
            })

        if not records:
            return None

        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        # 计算衍生字段
        df["pct_change"] = df["close"].pct_change() * 100
        df["price_change"] = df["close"].diff()
        df["amplitude"] = ((df["high"] - df["low"]) / df["close"]) * 100
        df = df.fillna(0)
        return df

    except Exception as e:
        print(f"[fetcher] 腾讯 K 线解析失败: {e}")
        return None


def _rename_akshare_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={
        "日期": "date", "开盘": "open", "最高": "high", "最低": "low",
        "收盘": "close", "成交量": "volume", "成交额": "amount",
        "振幅": "amplitude", "涨跌幅": "pct_change",
        "涨跌额": "price_change", "换手率": "turnover_pct",
    })
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df


def get_financial_data(code: str) -> Optional[pd.DataFrame]:
    """需要 tushare pro token，否则返回 None"""
    if not config.TUSHARE_TOKEN:
        return None
    import tushare as ts
    pro = ts.pro_api(config.TUSHARE_TOKEN)
    ts_code = code[2:].upper() + ".SH" if code.startswith("sh") else code[2:].upper() + ".SZ"
    try:
        indicator = pro.daily_basic(
            ts_code=ts_code,
            fields="ts_code,trade_date,pe,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
                   "total_share,float_share,free_share,total_mv,circ_mv",
        )
        if indicator.empty:
            return None
        latest = indicator.sort_values("trade_date", ascending=False).iloc[0]
        return latest
    except Exception as e:
        print(f"[fetcher] 获取 {code} 财务数据失败: {e}")
        return None


def get_stock_pool_with_leaders() -> list[dict]:
    """获取股票池，附加概念板块龙头信息。"""
    stocks = get_stock_pool()
    if not stocks:
        return stocks

    from data.leader_fetcher import fetch_leader_stocks

    leader_data = fetch_leader_stocks()
    leaders_df = leader_data.get("leaders", pd.DataFrame())
    mapping = leader_data.get("mapping", {})

    rank_lookup = {}
    if not leaders_df.empty:
        for _, row in leaders_df.iterrows():
            rank_lookup[row["code"]] = int(row["leader_rank"])

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
