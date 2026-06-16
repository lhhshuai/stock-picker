"""全局配置"""

# --- 数据源 ---
TUSHARE_TOKEN = ""  # 填入你的 tushare token，留空则只用 akshare

# --- 缓存 ---
CACHE_DIR = "cache"
CACHE_DAYS = 7  # 缓存有效期（天），超过自动刷新

# --- 策略默认权重（多因子） ---
FACTOR_WEIGHTS = {
    "value": 0.25,
    "growth": 0.25,
    "momentum": 0.20,
    "quality": 0.15,
    "volatility": 0.15,
}

# --- AI 策略（可选） ---
LLM_PROVIDER = "openai"  # openai / dashscope
LLM_API_KEY = ""
LLM_MODEL = "qwen-plus"  # 或 gpt-4o-mini 等

# --- 股票池默认范围 ---
DEFAULT_MARKET = ["SH", "SZ"]  # 上海证券交易所、深圳证券交易所
