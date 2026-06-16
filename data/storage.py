"""本地缓存管理：SQLite 存储日 K 线和股票列表，避免重复请求 API"""

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import config

CACHE_PATH = Path(config.CACHE_DIR) / "stocks.db"


def _get_conn() -> sqlite3.Connection:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """建表（幂等）"""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS stock_list (
                code TEXT PRIMARY KEY,
                name TEXT,
                market TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_kline (
                code TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                amplitude REAL,
                pct_change REAL,
                price_change REAL,
                turnover REAL,
                PRIMARY KEY (code, date)
            );

            CREATE INDEX IF NOT EXISTS idx_daily_code ON daily_kline(code);
            CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_kline(date);

            -- 概念板块排名
            CREATE TABLE IF NOT EXISTS concept_boards (
                board_code TEXT PRIMARY KEY,
                board_name TEXT,
                pct_change REAL,
                constituent_count INTEGER,
                updated_at TEXT
            );

            -- 龙头股映射
            CREATE TABLE IF NOT EXISTS leader_mapping (
                stock_code TEXT PRIMARY KEY,
                stock_name TEXT,
                board_code TEXT,
                board_name TEXT,
                leader_score REAL,
                latest_price REAL,
                pct_change REAL,
                amount REAL,
                updated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_leader_board ON leader_mapping(board_name);
        """)
        conn.commit()
    finally:
        conn.close()


def is_cache_fresh(code: str, days: int = None) -> bool:
    """检查某只股票缓存是否在有效期内"""
    if days is None:
        days = config.CACHE_DAYS
    conn = _get_conn()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT MAX(date) FROM daily_kline WHERE code = ? AND date >= ?",
            (code, cutoff),
        ).fetchone()
        return row[0] is not None
    finally:
        conn.close()


def save_daily_kline(code: str, df):
    """
    保存日 K 线到缓存。
    df 列名约定: date, open, high, low, close, volume, amount,
                amplitude, pct_change, price_change, turnover_pct
    """
    conn = _get_conn()
    try:
        for _, row in df.iterrows():
            conn.execute("""
                INSERT OR REPLACE INTO daily_kline
                    (code, date, open, high, low, close, volume, amount,
                     amplitude, pct_change, price_change, turnover)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code,
                str(row["date"]),
                row.get("open"),
                row.get("high"),
                row.get("low"),
                row.get("close"),
                row.get("volume"),
                row.get("amount"),
                row.get("amplitude"),
                row.get("pct_change"),
                row.get("price_change"),
                row.get("turnover_pct"),
            ))
        conn.commit()
    finally:
        conn.close()


def load_daily_kline(code: str, days_back: int = 120) -> "pandas.DataFrame":
    """从缓存加载最近 N 天的日 K 线"""
    import pandas as pd
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    conn = _get_conn()
    try:
        df = pd.read_sql_query("""
            SELECT date, open, high, low, close, volume, amount,
                   amplitude, pct_change, price_change, turnover
            FROM daily_kline
            WHERE code = ? AND date >= ?
            ORDER BY date
        """, conn, params=(code, cutoff))
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
    finally:
        conn.close()


def save_stock_list(stocks: list[dict]):
    """保存股票列表（code, name, market）"""
    conn = _get_conn()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for s in stocks:
            conn.execute("""
                INSERT OR REPLACE INTO stock_list (code, name, market, updated_at)
                VALUES (?, ?, ?, ?)
            """, (s["code"], s["name"], s["market"], now))
        conn.commit()
    finally:
        conn.close()


def load_stock_list() -> list[dict]:
    """加载股票列表"""
    import pandas as pd
    conn = _get_conn()
    try:
        df = pd.read_sql_query("SELECT code, name, market FROM stock_list", conn)
        return df.to_dict("records")
    finally:
        conn.close()


def is_cache_fresh_for(table: str, days: int = None) -> bool:
    """检查概念板块/龙头数据的缓存是否新鲜"""
    if days is None:
        days = config.CACHE_DAYS
    conn = _get_conn()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            f"SELECT MAX(updated_at) FROM {table} WHERE updated_at >= ?",
            (cutoff,),
        ).fetchone()
        return row[0] is not None
    finally:
        conn.close()


def save_concept_boards(df) -> None:
    """保存概念板块排名到缓存"""
    import pandas as pd
    conn = _get_conn()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for _, row in df.iterrows():
            conn.execute("""
                INSERT OR REPLACE INTO concept_boards
                    (board_code, board_name, pct_change, constituent_count, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                str(row.get("板块代码", "")),
                str(row.get("板块名称", "")),
                float(row.get("涨跌幅", 0)),
                int(row.get("成分股数量", 0)),
                now,
            ))
        conn.commit()
    finally:
        conn.close()


def load_concept_boards():
    """加载概念板块排名"""
    import pandas as pd
    conn = _get_conn()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM concept_boards ORDER BY pct_change DESC", conn
        )
        return df if not df.empty else None
    finally:
        conn.close()


def save_leader_mapping(leaders_df, mapping: dict) -> None:
    """保存龙头股及其所属板块映射"""
    conn = _get_conn()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for code, board_name in mapping.items():
            conn.execute("""
                INSERT OR REPLACE INTO leader_mapping
                    (stock_code, stock_name, board_code, board_name,
                     leader_score, latest_price, pct_change, amount, updated_at)
                VALUES (?, '', '', ?, 0, 0, 0, 0, ?)
            """, (code, board_name, now))
        conn.commit()
    finally:
        conn.close()


def load_leader_mapping():
    """
    加载龙头股映射。
    返回 (leaders_df, code_to_board_name_dict)
    """
    import pandas as pd
    conn = _get_conn()
    try:
        df = pd.read_sql_query(
            "SELECT stock_code, stock_name, board_name, leader_score, "
            "latest_price, pct_change, amount FROM leader_mapping "
            "ORDER BY leader_score DESC", conn
        )
        mapping = df.set_index("stock_code")["board_name"].to_dict() if not df.empty else {}
        return df, mapping
    finally:
        conn.close()
