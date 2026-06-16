# 中国股市选股系统

Python 量化选股系统，支持技术面 / 基本面 / 多因子 / AI 多种策略。

## 快速开始

```bash
cd stock-picker
pip install -r requirements.txt
streamlit run app.py
```

## 配置

编辑 `config.py`，填入你的 tushare token（可选）和大模型 API Key（AI 策略可选）。

## 策略

| 策略 | 说明 |
|------|------|
| 技术面 | 均线、MACD、RSI、成交量 |
| 基本面 | PE/PB 估值、ROE、成长性 |
| 多因子 | 价值+成长+动量+质量+波动 加权打分 |
| AI 选股 | LLM 舆情分析 + 传统因子融合 |

## 项目结构

```
stock-picker/
├── config.py
├── app.py                  # Streamlit 主程序
├── data/
│   ├── __init__.py
│   ├── fetcher.py          # 数据获取
│   └── storage.py          # 本地缓存
├── strategies/
│   ├── __init__.py
│   ├── base.py             # 策略基类
│   ├── technical.py        # 技术面
│   ├── fundamental.py      # 基本面
│   └── multifactor.py      # 多因子
├── utils/
│   ├── __init__.py
│   ├── indicators.py       # 技术指标
│   └── backtest.py         # 简易回测
└── requirements.txt
```
