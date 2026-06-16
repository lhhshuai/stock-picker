"""Streamlit 主程序 — A股智能选股系统"""

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from data.fetcher import get_daily_kline, get_financial_data, get_stock_pool
from data.leader_fetcher import fetch_leader_stocks, get_hot_concept_boards
from strategies.base import StockData
from strategies.technical import TechnicalStrategy
from strategies.fundamental import FundamentalStrategy
from strategies.multifactor import MultiFactorStrategy
from strategies.leader import LeaderStrategy, LeaderTechnicalStrategy

st.set_page_config(page_title="A股选股系统", page_icon="📊", layout="wide")

# ============ 辅助函数 ============


def _classify_tier(score: float) -> tuple[str, str, str]:
    """根据总分返回 (badge, tier_label, recommendation)"""
    if score >= 80:
        return "🟢", "强烈推荐", "龙头形态完美，建议重点关注"
    elif score >= 60:
        return "🟡", "谨慎关注", "基本面尚可，等待时机"
    else:
        return "🔴", "观望", "暂时不推荐，建议观望"


# ============ 侧边栏 ============
st.sidebar.title("⚙️ 选股配置")

selected_strategies = st.sidebar.multiselect(
    "选择策略",
    options=["技术面", "基本面", "多因子", "龙头策略", "龙头技术面"],
    default=["技术面", "多因子"],
)

enable_leaders = st.sidebar.checkbox("启用龙头股筛选", value=False)

top_n = st.sidebar.slider("选出前 N 只", 5, 200, 30, step=5)
min_score = st.sidebar.slider("最低分数", 0, 80, 30, step=5)

market_filter = st.sidebar.multiselect(
    "市场筛选",
    options=["全部", "沪市", "深市"],
    default=["全部"],
)

keyword = st.sidebar.text_input("排除关键词（如 ST、新股）", "")

# ============ 主界面 ============
st.title("📊 A股智能选股系统")
st.caption(f"数据时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# 初始化策略实例
tech = TechnicalStrategy()
fund = FundamentalStrategy()
multi = MultiFactorStrategy()
leader_multi = LeaderStrategy(base_strategy=multi)
leader_tech = LeaderTechnicalStrategy()

strategy_map = {
    "技术面": tech,
    "基本面": fund,
    "多因子": multi,
    "龙头策略": leader_multi,
    "龙头技术面": leader_tech,
}

# ============ 热门概念板块预览 ============
if enable_leaders:
    with st.expander("🔥 热门概念板块"):
        try:
            boards_df = get_hot_concept_boards()
            if boards_df is not None and not boards_df.empty:
                st.dataframe(
                    boards_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "板块名称": st.column_config.TextColumn("板块名称"),
                        "板块代码": st.column_config.TextColumn("代码"),
                        "涨跌幅": st.column_config.ProgressColumn(
                            "涨跌幅(%)", format="%.2f%%", min_value=0, max_value=10
                        ),
                        "成分股数量": st.column_config.NumberColumn("成分股数量"),
                    },
                )
            else:
                st.info("暂无板块数据，请检查网络连接")
        except Exception as e:
            st.warning(f"获取板块数据失败: {e}")

# ============ 运行按钮 ============
running = st.button("🚀 开始选股", type="primary", use_container_width=True)

if running:
    start_time = time.time()

    # 1. 获取股票池（龙头模式用增强版）
    with st.spinner("正在获取股票池..."):
        if enable_leaders:
            from data.fetcher import get_stock_pool_with_leaders

            stocks = get_stock_pool_with_leaders()
        else:
            stocks = get_stock_pool()

    if not stocks:
        st.error("无法获取股票池数据，请检查网络连接。")
        st.stop()

    st.info(f"共获取 {len(stocks)} 只股票，为提高速度，最多处理前 200 只")
    stocks = stocks[:200]

    # 2. 市场过滤
    if "沪市" in market_filter and "深市" in market_filter:
        pass
    elif "沪市" in market_filter:
        stocks = [s for s in stocks if s["market"] == "SH"]
    elif "深市" in market_filter:
        stocks = [s for s in stocks if s["market"] == "SZ"]

    # 3. 关键词过滤
    if keyword:
        kw = keyword.upper()
        if "ST" in kw:
            stocks = [s for s in stocks if "ST" not in s["name"].upper()]
        else:
            stocks = [s for s in stocks if kw not in s["name"].upper()]

    st.write(f"过滤后剩余 **{len(stocks)}** 只股票")

    # 4. 逐只打分
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, stock in enumerate(stocks):
        if keyword and keyword.replace("ST", "") in stock["name"].upper():
            continue

        daily = get_daily_kline(stock["code"], days=120)
        financial = get_financial_data(stock["code"])

        data = StockData(
            code=stock["code"],
            name=stock["name"],
            daily_df=daily,
            financial=financial,
            board_name=stock.get("board_name"),
            leader_rank=stock.get("leader_rank"),
        )

        row = {
            "代码": stock["code"],
            "名称": stock["name"],
            "最新价": float(daily["close"].iloc[-1]) if daily is not None else None,
            "涨跌幅(%)": float(daily["pct_change"].iloc[-1]) if daily is not None else None,
        }

        # 板块信息
        if enable_leaders:
            row["所属板块"] = stock.get("board_name", "-")
            row["是否龙头"] = "🏆 是" if stock.get("is_leader") else "—"

        # 各策略打分
        for name in selected_strategies:
            strat = strategy_map[name]
            if strat.filter(data):
                row[name] = round(strat.score(data), 1)
            else:
                row[name] = 0

        # 总分
        if selected_strategies:
            total = sum(row.get(n, 0) for n in selected_strategies) / len(selected_strategies)
        else:
            total = 0
        row["总分"] = round(total, 1)

        # 三档分级
        badge, tier_label, rec_text = _classify_tier(total)
        row["评级"] = f"{badge} {tier_label}"
        row["推荐理由"] = rec_text

        results.append(row)

        # 进度更新
        if i % 20 == 0:
            progress_bar.progress((i + 1) / len(stocks))
            status_text.text(f"已处理 {i + 1}/{len(stocks)}")

    progress_bar.progress(1.0)
    status_text.text("✅ 选股完成！")

    elapsed = time.time() - start_time

    # 5. 结果处理
    df = pd.DataFrame(results)
    df = df[df["总分"] >= min_score].sort_values("总分", ascending=False).head(top_n)

    st.success(f"选股完成！耗时 {elapsed:.1f} 秒，共选出 {len(df)} 只股票")

    # 6. 分级统计
    if not df.empty:
        st.subheader("📊 分级统计")
        df["badge"] = df["评级"].str.extract(r"(🟢|🟡|🔴)", expand=False)
        n_strong = (df["badge"] == "🟢").sum()
        n_caution = (df["badge"] == "🟡").sum()
        n_wait = (df["badge"] == "🔴").sum()
        col1, col2, col3 = st.columns(3)
        col1.metric("🟢 强烈推荐", n_strong)
        col2.metric("🟡 谨慎关注", n_caution)
        col3.metric("🔴 观望", n_wait)

    # 7. 结果展示
    st.subheader("📋 选股结果")

    if df.empty:
        st.info("没有找到符合条件的股票，请降低最低分数或调整策略。")
    else:
        # 显示表（去掉推荐理由列）
        display_df = df.copy()
        show_cols = [c for c in display_df.columns if c not in ("推荐理由", "badge")]
        st.dataframe(display_df[show_cols], use_container_width=True, hide_index=True)

        # 导出按钮
        csv = df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button(
            label="📥 导出 Excel/CSV",
            data=csv,
            file_name=f"选股结果_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )

    # 8. 龙头股精选区块
    if enable_leaders and not df.empty:
        leader_results = df[df["是否龙头"] == "🏆 是"]
        if not leader_results.empty:
            st.subheader("🏆 龙头股精选")
            st.write("以下股票为热门概念板块的龙头股，享有龙头加成")
            leader_display = leader_results[show_cols].copy()
            st.dataframe(leader_display, use_container_width=True, hide_index=True)

    # 9. 个股详情
    if not df.empty:
        st.subheader("🔍 个股详情")
        selected = st.selectbox(
            "选择股票查看详情",
            df["名称"].tolist(),
        )
        if selected:
            sel_row = df[df["名称"] == selected].iloc[0]
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("股票代码", sel_row["代码"])
            col2.metric("最新价", f"{sel_row['最新价']:.2f}" if sel_row["最新价"] else "-")
            col3.metric("涨跌幅", f"{sel_row['涨跌幅(%)']:.2f}%" if sel_row["涨跌幅(%)"] is not None else "-")
            col4.metric("评级", sel_row.get("评级", "-"))

            if enable_leaders and sel_row.get("所属板块", "-") != "-":
                st.info(f"所属概念板块: **{sel_row['所属板块']}**")

            cols = st.columns(len(selected_strategies))
            for j, name in enumerate(selected_strategies):
                cols[j].metric(name, f"{sel_row[name]:.1f}/100")

            # 显示 K 线图
            daily = get_daily_kline(sel_row["代码"], days=60)
            if daily is not None and not daily.empty:
                st.line_chart(daily.set_index("date")[["close", "open", "high", "low"]])
