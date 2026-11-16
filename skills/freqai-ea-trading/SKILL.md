---
name: freqai-ea-trading
description: >-
  Automated trend-following trading EAs (Expert Advisors, 自動交易系統) for BTC, ETH and SOL
  on Freqtrade + FreqAI: BTCTrendEA, ETHRiskOnEA (trades ETH only while BTC is risk-on),
  SOLMomentumEA. Breakout entries above a slow trend, chandelier stops held on the exchange,
  fixed-risk position sizing from FreqAI's volatility forecast. Includes a pre-registered
  validation protocol (untouched 2018-2021 pre-sample, post-sample, SOL transfer test on six
  alts, robustness), TradingView Lightweight Charts research pages, and Docker deployment
  for unattended dry-run/live trading. Use when asked to build, validate, run, monitor or
  adapt an automated crypto trading EA/bot with Freqtrade or FreqAI.
---

# FreqAI 自動交易 EA：BTC / ETH / SOL

三個只做多、現貨、全自動的趨勢跟隨 EA。共用引擎 `EABase`，每個幣依自己的特性調整，所有決策都是機械式的，Freqtrade 可以 24 小時無人值守地下單、移動停損、出場。

> 不保證獲利。是否「驗證通過」由事前登記的協議決定（`references/validation-protocol.md`，在任何 EA 回測之前推上 GitHub），結果見 `references/validation-results.md`。

## 檔案

| 路徑 | 內容 |
|---|---|
| `user_data/strategies/EABase.py` | EA 引擎：突破進場、吊燈停損（交易所掛單）、趨勢/風險出場、固定風險部位、FreqAI 特徵與目標 |
| `user_data/strategies/BTCTrendEA.py` | BTC：100 日趨勢 + 突破進場 + 寬吊燈停損 |
| `user_data/strategies/ETHRiskOnEA.py` | ETH：只在 BTC 處於 100 日多頭時交易 ETH 的突破 |
| `user_data/strategies/SOLMomentumEA.py` | SOL：50 日 EMA 上升中的長週期突破、最寬停損 |
| `user_data/freqaimodels/PurgedLGBMMultiTarget.py` | 去除 label 洩漏的 LightGBM（與網格 skill 相同） |
| `user_data/configs/config_{btc,eth,sol}_ea.json` | Binance 現貨設定；`ea_params` 可覆寫參數；預設 dry-run |
| `scripts/ea_lab.py` | `backtest` / `tune`（只限研發期）/ `validate`（事前登記的 V1–V4，自動判 PASS/FAIL） |
| `deploy/` | Dockerfile（freqtrade[freqai]==2026.10）、docker-compose（三個 EA 各一個容器）、`ea.env.example` |
| `references/validation-protocol.md` | 事前登記的期間與門檻 |
| `references/validation-results.md` | 驗證結果 |
| `references/ea-design.md` | 設計、圖表研究過程、研發期調參紀錄 |
| `references/deployment.md` | 上線檢查表、監控、緊急停止 |

依賴同倉庫的 `skills/freqai-grid-trading/scripts/`（回測包裝 `ft_offline.py`、盯市報告 `grid_report.py`、資料下載、TradingView 圖表 `tv_research.py`）。

## 規則（給執行這個 skill 的 agent）

1. 調參只能在研發期 `20210601-20241212`；V1/V2/V3 每個 EA 版本只跑一次。改規則就是新版本：改 `freqai.identifier` 與策略名稱，重新登記、重新驗證。
2. 回報時一定附上：驗證是否通過（逐條）、最差年份、盯市最大回撤、同期買入持有。不能只報總報酬。
3. 不在 repo 或設定檔寫入 API 金鑰；金鑰只放 `deploy/ea.env`（git-ignored）並關閉提幣權限。
4. 新 EA 上線前至少 30 天 dry-run，並與同期回測比對。

## 常用指令

```bash
SK=skills/freqai-ea-trading; G=skills/freqai-grid-trading
bash $G/scripts/setup_env.sh
export FT_VENV=~/crypto-trading/venvs/freqai-grid FT_HOME=~/crypto-trading/freqai-grid/user_data
PY=$FT_VENV/bin/python
$PY $G/scripts/download_binance_vision.py --pairs BTC/USDT ETH/USDT --timeframes 1h 15m --start 2017-08 --datadir $FT_HOME/data/binance
$PY $G/scripts/download_binance_vision.py --pairs SOL/USDT AVAX/USDT NEAR/USDT DOT/USDT ADA/USDT LINK/USDT DOGE/USDT --timeframes 1h 15m --start 2020-01 --datadir $FT_HOME/data/binance

$PY $SK/scripts/ea_lab.py backtest --coin btc --userdir $FT_HOME --keep runs/btc      # 研發期回測
$PY $SK/scripts/ea_lab.py validate --coin btc --userdir $FT_HOME                       # 事前登記的驗證
$PY $G/scripts/tv_research.py --strategy-path $SK/user_data/strategies \
    --run "runs/btc/<result>.zip::BTC EA" --datadir $FT_HOME/data/binance --models $FT_HOME/models --out ea.html

docker compose -f $SK/deploy/docker-compose.yml up -d --build                          # 24/7 自動交易（預設 dry-run）
```

交易所 API 被擋的環境（例如雲端沙盒）回測時加 `FT_OFFLINE=1`。
