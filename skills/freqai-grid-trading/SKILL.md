---
name: freqai-grid-trading
description: >-
  Freqtrade + FreqAI grid trading (網格交易) for BTC, ETH and SOL — three coin-specific spot
  grids on one FreqAI-steered grid engine: BTCAccumGridAI (BTC core + accumulation grid in
  the 100-day uptrend), ETHRiskOnGridAI (ETH grid only while BTC is risk-on),
  SOLTrendGridAI (SOL trend-aligned wide grid with trailing profit lock). FreqAI forecasts
  volatility for grid spacing and spike pauses. Includes data download, purged
  walk-forward backtests, mark-to-market reports, in-sample tuning, FreqAI ablation and
  prediction-quality checks, and dry-run/live deployment. Use when asked to build,
  backtest, tune, deploy, monitor or adapt grid trading bots with Freqtrade or FreqAI, or
  to check whether these grids still work.
---

# FreqAI 網格交易：BTC / ETH / SOL

一個網格引擎（`GridAIBase`）+ 三個針對幣種特性設計的現貨網格。FreqAI（LightGBM、purged walk-forward、每 30 天重訓）預測**未來波動**來決定格距、在波動放大前暫停加倉，並提供**很弱的方向傾向**；方向一律由慢速 EMA 趨勢濾網決定（ETH 另加 BTC risk-on 濾網）。三個設計都是在樣本內比較多種結構（含永續多空網格）後，依證據選出來的。

> 不保證獲利。下面所有數字都是歷史回測（含手續費與資金費率），不是未來報酬。實盤前至少 30 天 dry-run。

## 檔案

| 路徑 | 內容 |
|---|---|
| `user_data/strategies/GridAIBase.py` | 網格引擎：LIFO 網格、掛單在網格價、跟漲 ref、grid_break / regime_off / trail_lock、FreqAI 特徵與目標 |
| `user_data/strategies/BTCAccumGridAI.py` | BTC：60% 核心倉 + 12 格，只在 100 日趨勢之上 |
| `user_data/strategies/ETHRiskOnGridAI.py` | ETH：40% 核心倉 + 10 格，只在 ETH 50 日趨勢之上且 BTC risk-on 時 |
| `user_data/strategies/SOLTrendGridAI.py` | SOL：30% 核心倉 + 6 格寬網格，只順上升趨勢，回撤 6 格鎖利 |
| `user_data/freqaimodels/PurgedLGBMMultiTarget.py` | 去除訓練窗尾端 label 洩漏的 LightGBM 多目標模型 |
| `user_data/configs/config_{btc,eth,sol}.json` | 各幣設定（Binance 現貨；`grid_params` 可覆寫策略參數，含 `ai_vol`/`ai_drift` 消融開關） |
| `scripts/setup_env.sh` | 安裝 `freqtrade[freqai]==2026.10` 並建立 userdir |
| `scripts/download_binance_vision.py` | 從 data.binance.vision 下載多年 K 線（現貨；永續另含 mark / funding），免金鑰 |
| `scripts/backtest.sh` | 單幣完整 walk-forward 回測 + 盯市報告 |
| `scripts/grid_report.py` | 由成交單重建逐小時盯市權益：報酬、CAGR、最大回撤、逐年、對照買入持有、樣本內/外 |
| `scripts/tune.py` | 只在樣本內做參數網格搜尋（平行、重用 FreqAI 快取） |
| `scripts/prediction_quality.py` | FreqAI walk-forward 預測的 IC 檢查（對照天真預測） |
| `scripts/ft_offline.py` | 回測包裝：跳過 Freqtrade 對 trade 的深拷貝（結果相同、快數倍）；`FT_OFFLINE=1` 時改用靜態市場清單（交易所 API 被擋時） |
| `references/strategy-design.md` | 引擎機制、FreqAI 設計與證據、三個幣為什麼這樣設計 |
| `references/backtest-results.md` | 2021-06 → 2026-10 回測結果（樣本內 / 樣本外 / 逐年 / 消融 / 手續費壓力） |
| `references/tuning-log.md` | 樣本內 195 組調參的完整紀錄（含被否決的永續多空版本） |
| `references/results/*.json` | 最終回測的完整報告（`grid_report.py` 輸出） |
| `references/deployment.md` | dry-run → live 檢查表、金鑰與風控、例行監控 |

## 三個策略一覽

| | BTCAccumGridAI | ETHRiskOnGridAI | SOLTrendGridAI |
|---|---|---|---|
| 市場 | BTC/USDT 現貨 | ETH/USDT 現貨 | SOL/USDT 現貨 |
| 開一輪 | BTC > EMA(2400h)×1.03 | ETH > EMA(1200h) **且** BTC > EMA(2400h) | SOL > EMA(1200h) 且 EMA 上升 |
| 形狀 | 核心 60% + 12 格 × 2.5σ | 核心 40% + 10 格 × 2.5σ | 核心 30% + 6 格 × 2σ（≥1.5%） |
| 出場 | regime_off、grid_break | regime_off（含 BTC risk-off）、grid_break | trail_lock、regime_off、grid_break |
| FreqAI | 24h 波動預測 → 格距、波動放大暫停加倉、弱方向傾向 | 同左 + BTC 特徵 | 同左 + BTC、ETH 特徵 |

### 回測摘要（2021-06 → 2026-10，現貨、每邊手續費 0.10%、盯市回撤）

| | 全期間 | 最大回撤 | 樣本外 2024-12-12 → 2026-10 | 同期買入持有 |
|---|---|---|---|---|
| BTCAccumGridAI | +178.5%（CAGR 20.8%） | 25.5%（持有 77%） | −8.2% | −23.1% |
| ETHRiskOnGridAI | +75.2%（CAGR 10.9%） | 27.1%（持有 81%） | +4.2% | −40.9% |
| SOLTrendGridAI | +80.2%（CAGR 11.5%） | 47.6%（持有 97%） | −27.0% | −58.0% |

三個全期間都賺錢、回撤遠低於持有；樣本外（熊市）只有 ETH 為正。SOL 最弱，不建議直接實盤。對使用者轉述時要連同這些缺點一起講。

設計理由、被否決的設計與證據：`references/strategy-design.md`。完整回測（逐年、消融、手續費壓力、預測力、成交稽核）：`references/backtest-results.md`。全部 195 組樣本內調參：`references/tuning-log.md`。

## 標準流程

```bash
SK=skills/freqai-grid-trading            # 在本倉庫內；或 ~/.claude/skills/freqai-grid-trading
bash $SK/scripts/setup_env.sh            # 1) 環境（可重複執行）
export FT_VENV=~/crypto-trading/venvs/freqai-grid FT_HOME=~/crypto-trading/freqai-grid/user_data
PY=$FT_VENV/bin/python

# 2) 資料（現貨 1h + 5m，三個幣約 70 MB；4h/1d 由 1h 自動重採樣）
$PY $SK/scripts/download_binance_vision.py --trading-mode spot --timeframes 1h 5m --start 2020-06 --datadir $FT_HOME/data/binance

# 3) 完整 walk-forward 回測 + 盯市報告（第一次會訓練約 66 個 FreqAI 視窗）
bash $SK/scripts/backtest.sh btc 20210601-20261101 2024-12-12     # eth / sol 同理
#    交易所 API 不通時：FT_OFFLINE=1 bash $SK/scripts/backtest.sh ...

# 4) FreqAI 預測力檢查（波動 IC 必須勝過天真預測）
$PY $SK/scripts/prediction_quality.py --identifier btc-accum-grid-v2 --pair BTC/USDT \
    --datadir $FT_HOME/data/binance --models $FT_HOME/models

# 5) （可選）只在樣本內調參 / 消融，再看一次樣本外
$PY $SK/scripts/tune.py --coin btc --userdir $FT_HOME --grid '{"step_mult":[1.5,2.5,3.5]}'
$PY $SK/scripts/tune.py --coin btc --userdir $FT_HOME --grid '{"ai_vol":[true,false],"ai_drift":[true,false]}'
```

之後的 dry-run / live：`references/deployment.md`。

## 規則（給執行這個 skill 的 agent）

1. **不准對樣本外調參。** 樣本內 = `20210601-20241212`（FreqAI 30 天視窗邊界）；樣本外 = 2024-12-12 之後。改了策略就是新版本：改 `freqai.identifier`（特徵或目標有變時必改），重跑完整流程。
2. **回報盯市回撤，不是 Freqtrade 的「已平倉回撤」。** 一律用 `grid_report.py`，並附上同期買入持有作對照。
3. **細節時間框架用 5m。** 15m 會低估網格來回；成交一律掛在網格價（引擎已處理）。
4. **手續費保守**：現貨 0.10%（Binance VIP0，無 BNB 折扣；`backtest.sh` / `tune.py` 已設定）。改用永續時用 taker 0.05% 並確認回測含資金費率。
5. **不寫入任何 API 金鑰**到 repo 或設定檔；實盤金鑰用環境變數、關閉提幣。預設現貨；若改永續，槓桿維持 1x、逐倉。
6. 對使用者說明結果時，**明講不保證獲利**、指出最差年份與最大回撤，不要只報總報酬。
7. FreqAI 預測力退化（波動 IC 連續兩個月輸給天真預測）→ 建議停止開新輪並回到研發。

## 換幣種 / 換交易所

1. 複製最接近的策略（低波動、長期趨勢強 → BTC 版；高 beta、跟著 BTC 走 → ETH 版；高波動動能型 → SOL 版），改類別名與 `GRID`。
2. 複製設定檔，改 `strategy`、`pair_whitelist`、`include_corr_pairlist`、`freqai.identifier`。
3. 下載資料 → `backtest.sh`（新幣種要加進 `backtest.sh` 與 `tune.py` 的手續費對照）→ `prediction_quality.py` → 樣本內 `tune.py`（含 `ai_vol`/`ai_drift` 消融）→ 樣本外只看一次。
4. 換交易所：改 `exchange.name`（Freqtrade 支援的交易所），交易對命名照該交易所；最小下單量要能容納一格（見 deployment.md）。

## 疑難排解

| 症狀 | 原因 / 解法 |
|---|---|
| `Could not load markets` | 交易所 API 被擋：回測用 `FT_OFFLINE=1`（`ft_offline.py`）；實盤需要能連到交易所 |
| `The data contains non-finite values` | 舊版特徵；目前版本已把 ±inf 轉 NaN。刪掉 `models/<identifier>` 重跑 |
| `tune.py` 拒絕時間範圍 | 終點必須是起點 + k×30 天（FreqAI 視窗邊界），例如 `20210601-20241212`；否則平行回測會同時重訓並覆寫最後一個視窗的快取 |
| 回測很慢 | 第一次要訓練；之後重用 `models/<identifier>/backtesting_predictions`。多個回測平行時把 `n_jobs` 設 1（`-c` 疊一個覆寫檔） |
| 網格幾乎不成交 | 每格金額低於交易所最小下單量，或 `step_min` 太大 |
