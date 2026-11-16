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

## 驗證結果（事前登記協議，各跑一次）

| EA | 判定 | V1 從未測過的 2018-06 → 2021-06 | V2 2024-12 → 2026-10（熊市） | 全歷史連續回測 |
|---|---|---|---|---|
| BTCTrendEA | **通過** | +137.9%，回撤 31.1%（持有 +395.5% / 70.4%），PF 3.76，17 筆 | +0.7%（持有 −23.1%），回撤 18.8% | 2018-06 → 2026-10 +303.7%，回撤 31.1% |
| ETHRiskOnEA | **未通過**（V1 只有 12 筆 < 15） | +192.5%，回撤 22.9%（持有 86.8%），PF 14.3 | +27.2%（持有 −40.9%），回撤 15.5% | +387.8%（持有 +288.3%），回撤 22.9% |
| SOLMomentumEA | **通過** | V3：SOL 規則套 6 個沒研究過的幣，6/6 獲利、平均 +36%、回撤 26%（持有 93%） | +1.4%（持有 −58.0%），回撤 13.3% | 2021-06 → 2026-10 +246.2%，回撤 22.0% |

趨勢跟隨的代價：牛市跑輸買入持有、熊市只能空手（不會賺）、每年只有 4–5 筆。ETH 未通過是因為樣本太少，不能事後放寬門檻；只建議 dry-run 累積紀錄。細節：`references/validation-results.md`。

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
| `references/results/validation_*.json` | 驗證的完整輸出 |
| `tradingview/research_notes.json` | TradingView 研究頁的筆記（圖表模板與函式庫在 freqai-grid-trading skill） |

依賴同倉庫的 `skills/freqai-grid-trading/scripts/`（回測包裝 `ft_offline.py`、盯市報告 `grid_report.py`、資料下載、TradingView 圖表 `tv_research.py`）。

## 維護 Agent（確保 EA 持續有效）

| 元件 | 作用 |
|---|---|
| `.claude/agents/ea-maintainer.md` | Claude Code 子代理：例行檢查、診斷、寫維護紀錄、開 issue、只能透過候選版本流程改版 |
| `maintenance/ea_guard.py` | 健康檢查引擎：`forward`（凍結參數跑 2026-11-01 之後的新資料）、`live`（實盤 API 守衛，HALT 時自動 `/stopentry`）、`replay`、`baseline` |
| `maintenance/maintenance-protocol.md` | 事前登記的檢查項目 C1–C7、門檻、各狀態動作、Agent 能做與不能做的事、改版與 ETH 升級條件 |
| `maintenance/baselines.json` | 每個 EA 由驗證過的歷史算出的「正常範圍」（區塊自助法回撤、連敗、10 筆獲利因子、上漲捕捉率） |
| `maintenance/log.md` | 維護紀錄（第一次前向檢查、回放自我測試、研究線索） |
| `.github/workflows/ea-health.yml` | 每週一自動前向檢查；DEGRADED/HALT 時開或更新 `ea-health` issue |
| `deploy/docker-compose.yml` 的 `ea-guard` | 每 15 分鐘檢查三個機器人；HALT 時送 `/stopentry`（只停新進場，不平倉、不恢復） |

自我測試：守衛在 2025–26 熊市逐月回放，真的 EA 22 個月全部 HEALTHY；故意弄壞的版本第 2 個月就 DEGRADED、後來 HALT。實盤守衛對模擬 API 的整合測試 7/7 通過（`maintenance/test_guard_live.py`）。

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

docker compose -f $SK/deploy/docker-compose.yml up -d --build                          # 24/7 自動交易（預設 dry-run）+ 實盤守衛
$PY $SK/maintenance/ea_guard.py forward --all --userdir $FT_HOME                        # 前向健康檢查（新資料）
```

交易所 API 被擋的環境（例如雲端沙盒）回測時加 `FT_OFFLINE=1`。
