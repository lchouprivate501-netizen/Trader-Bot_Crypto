---
name: freqai-ea-trading
description: >-
  Automated trend-following trading EAs (Expert Advisors, 自動交易系統, 合約 EA) for BTC, ETH and
  SOL on Freqtrade + FreqAI. Primary: USDT-M perpetual futures EAs for ETH and SOL (ETHFuturesEA,
  SOLFuturesEA: long breakouts above a slow trend plus shorts on breakdowns while the trend falls,
  isolated margin, liquidation kept beyond 2x the stop) and the spot BTCTrendEA for BTC (its
  futures version failed validation). Chandelier stops held on the exchange, fixed-risk sizing
  from FreqAI's volatility forecast. Pre-registered validation protocols (untouched 2018-2021,
  2025-26 bear market, transfer test on six alts, robustness), TradingView Lightweight Charts
  research pages, Docker deployment, and an EA trading desk (stdlib MCP server + CLI) through
  which an AI agent executes the EAs' long/short signals on the user's exchange from key-less
  dry-run engines. Use when asked to build, validate, run, monitor or adapt an automated crypto
  trading EA/bot (spot or futures) with Freqtrade or FreqAI, or to trade / run a round of the BTC,
  ETH or SOL EAs for the user.
---

# FreqAI 自動交易 EA：BTC / ETH / SOL（合約 + 現貨）

全自動的趨勢跟隨 EA，所有決策都是機械式的，Freqtrade 可以 24 小時無人值守地下單、移動停損、出場。**主要策略：ETH、SOL 用合約 EA（USDT 永續、多空、逐倉）；BTC 用現貨 EA（只做多）**——每個幣用的是驗證通過的那一個。

| 幣 | 主要策略 | 市場 | 驗證 |
|---|---|---|---|
| ETH | `ETHFuturesEA` | USDT 永續、多空、逐倉 1–3 倍 | 通過（現貨 `ETHRiskOnEA` 未通過） |
| SOL | `SOLFuturesEA` | USDT 永續、多空、逐倉 1–3 倍 | 通過（現貨 `SOLMomentumEA` 也通過，可替代） |
| BTC | `BTCTrendEA` | 現貨、只做多 | 通過（合約 `BTCFuturesEA` 未通過，只做影子紀錄） |

> 不保證獲利。是否「驗證通過」由事前登記的協議決定（現貨：`references/validation-protocol.md`；合約：`references/futures-validation-protocol.md`，都在任何回測之前推上 GitHub）。

## 合約 EA（主要策略）驗證結果

`FuturesEABase` ＝ 現貨 EA 的多單（參數不變）＋ 新的空單（趨勢 EMA 已下降 30 天時跌破前 N 小時低點進場、3 倍日波動的緊吊燈停損、趨勢轉多出場；ETH 只在 BTC 空頭時做空）＋ 逐倉（槓桿讓清算價距離 ≥ 2 倍停損距離，1–3 倍，只減少保證金、不放大部位）。每邊手續費 0.05%、含資金費。

| 合約 EA | 判定 | V1 2018-06 → 2021-06 | V2 2024-12 → 2026-10（熊市） | 空單淨損益 | 全歷史連續回測 |
|---|---|---|---|---|---|
| ETHFuturesEA | **通過** | +219.6%，回撤 26.6%（持有 +366% / 86.8%），PF 3.70，32 筆 | **+65.7%**（持有 −40.9%），回撤 20.4% | V1 +5,554、V2 +3,628 | 2018-06 → 2026-10 +1,046%，回撤 26.6%，0 強平 |
| SOLFuturesEA | **通過** | V3：SOL 規則套 6 個沒研究過的幣，5/6 獲利、平均 +50.3%、回撤 36.2%（持有 93%） | +7.4%（持有 −58.0%），回撤 25.4% | V2 +533、V3 +14,094 | 2021-06 → 2026-10 +448%，回撤 35.8%，0 強平 |
| BTCFuturesEA | **未通過**（V2 −6.9%、空單合計 −227） | +92.4%，回撤 34.0% | −6.9%（持有 −23.1%） | V1 +211、V2 −438 | — |

研發期的關鍵發現：直接鏡像多單的空單三個幣都虧錢；空單要賺錢，必須只在趨勢真的下降時做、而且停損要比多單緊很多（3 倍 vs 10 倍日波動），因為熊市反彈又快又猛。BTC 的空單只在很窄的參數範圍內賺錢，驗證時果然失效。2018 年 V1 前段沒有永續資料，用現貨價格代替、資金費設為 0。細節：`references/futures-design.md`、`references/futures-validation-results.md`。

## 現貨 EA 驗證結果

| EA | 判定 | V1 從未測過的 2018-06 → 2021-06 | V2 2024-12 → 2026-10（熊市） | 全歷史連續回測 |
|---|---|---|---|---|
| BTCTrendEA | **通過** | +137.9%，回撤 31.1%（持有 +395.5% / 70.4%），PF 3.76，17 筆 | +0.7%（持有 −23.1%），回撤 18.8% | 2018-06 → 2026-10 +303.7%，回撤 31.1% |
| ETHRiskOnEA | **未通過**（V1 只有 12 筆 < 15） | +192.5%，回撤 22.9%（持有 86.8%），PF 14.3 | +27.2%（持有 −40.9%），回撤 15.5% | +387.8%（持有 +288.3%），回撤 22.9% |
| SOLMomentumEA | **通過** | V3：SOL 規則套 6 個沒研究過的幣，6/6 獲利、平均 +36%、回撤 26%（持有 93%） | +1.4%（持有 −58.0%），回撤 13.3% | 2021-06 → 2026-10 +246.2%，回撤 22.0% |

現貨 EA 的代價：牛市跑輸買入持有、熊市只能空手（不會賺）、每年只有 4–5 筆。ETH 現貨未通過是因為樣本太少，不能事後放寬門檻。細節：`references/validation-results.md`。

## 檔案

| 路徑 | 內容 |
|---|---|
| `user_data/strategies/EABase.py` | EA 引擎：突破進場、吊燈停損（交易所掛單）、趨勢/風險出場、固定風險部位、FreqAI 特徵與目標 |
| `user_data/strategies/BTCTrendEA.py` | BTC：100 日趨勢 + 突破進場 + 寬吊燈停損 |
| `user_data/strategies/ETHRiskOnEA.py` | ETH：只在 BTC 處於 100 日多頭時交易 ETH 的突破 |
| `user_data/strategies/SOLMomentumEA.py` | SOL：50 日 EMA 上升中的長週期突破、最寬停損 |
| `user_data/strategies/FuturesEABase.py` | 合約 EA 引擎：多單同 `EABase` ＋ 空單、逐倉槓桿規則、30% 價格停損上限 |
| `user_data/strategies/{BTC,ETH,SOL}FuturesEA.py` | 三個合約 EA（多單參數 = 現貨 EA，空單參數凍結於研發期） |
| `user_data/configs/config_{btc,eth,sol}_perp.json` | Binance USDT-M 永續、逐倉設定；預設 dry-run |
| `user_data/freqaimodels/PurgedLGBMMultiTarget.py` | 去除 label 洩漏（purged walk-forward）的 LightGBM 多目標模型 |
| `user_data/configs/config_{btc,eth,sol}_ea.json` | Binance 現貨設定；`ea_params` 可覆寫參數；預設 dry-run |
| `scripts/ea_lab.py` | `backtest` / `tune`（只限研發期）/ `validate`（事前登記的 V1–V4，自動判 PASS/FAIL）；`--market perp` 為合約 EA（多空、資金費拆分） |
| `scripts/perp_proxy.py` | 2020-01 以前沒有永續資料時，用現貨 K 線當合約價格代用、資金費設 0（只給合約 V1 驗證用） |
| `deploy/` | Dockerfile（freqtrade[freqai]==2026.10）、docker-compose（三個 EA 各一個容器）、`ea.env.example` |
| `references/futures-validation-protocol.md`、`futures-validation-results.md`、`futures-design.md` | 合約 EA 的事前登記協議、驗證結果、研發紀錄 |
| `references/validation-protocol.md`、`validation-results.md` | 現貨 EA 的事前登記協議與驗證結果 |
| `references/ea-design.md` | 設計、圖表研究過程、研發期調參紀錄 |
| `references/deployment.md` | 上線檢查表、監控、緊急停止 |
| `references/results/validation_*.json` | 驗證的完整輸出（`*_perp.json` 為合約） |
| `scripts/setup_env.sh` | 安裝固定版本的 Freqtrade 2026.10 + FreqAI venv |
| `scripts/download_binance_vision.py` | 從 data.binance.vision 下載歷史 K 線（不需金鑰；`--daily-tail` 補當月） |
| `scripts/ft_offline.py` | 回測包裝：連不到交易所時用靜態市場清單（`FT_OFFLINE=1`），並略過不必要的 deepcopy 加速 |
| `scripts/mtm_report.py` | 盯市報告：由每筆成交重建權益曲線，算真正經歷到的回撤、逐年、曝險、同期持有 |
| `scripts/exit_analysis.py` | 逐筆交易與出場原因分析（出場後 3 / 14 天價格怎麼走） |
| `scripts/prediction_quality.py` | FreqAI 預測力檢查（波動 IC vs 天真預測，逐年） |
| `scripts/tv_research.py`、`tradingview/` | TradingView Lightweight Charts 研究頁產生器（K 線、趨勢 EMA、突破線、交易、權益 vs 持有、回撤、FreqAI 波動）與研究筆記 |

全部工具都在這個資料夾內，不依賴其他 skill。

## 讓 AI 依 EA 下單（EA 交易台）

三個**無金鑰**的 Freqtrade dry-run 引擎跑 EA 與 FreqAI，只算出該做什麼；交易台比對引擎與 AI 的帳本，每個幣給一條指令（含 `market` 合約/現貨、`side` 多/空、槓桿），AI 在使用者的交易所執行（ETH、SOL 永續合約逐倉；BTC 現貨）。**要替使用者交易時，先讀 [`AGENTS.md`](AGENTS.md) 並照做。**

| 路徑 | 內容 |
|---|---|
| `AGENTS.md` | AI 作業手冊：每輪流程、各 action 的做法、絕對不可以、上線檢查表 |
| `desk/ea_desk.py` | 交易台（指令、下單前風控、帳本、停損紀錄、HALT、實盤開關）；也是 CLI：`signals` / `check` / `record` / `status` / `halt` |
| `desk/mcp_server.py` | stdio MCP 伺服器 `freqai-ea-desk`（`ea_guide`、`ea_status`、`ea_signals`、`ea_risk_check`、`ea_record`、`ea_halt`），只用標準函式庫 |
| `desk/ea_engine.py` | 背景啟動 / 停止三個無金鑰引擎與 EA 守衛（REST 只聽 127.0.0.1，帳密隨機產生） |
| `desk/config.json` | 預設值：追價上限 2%、停損上移門檻 0.5%、單筆風險 ≤ 資金 10%、累計虧損 35% 停新單；使用者在 `~/.freqai-ea/config.json` 覆寫 |
| `desk/test_desk.py`、`desk/test_desk_perp.py` | 整合測試：模擬 Freqtrade API。現貨 51 項（指令、風控、帳本、MCP）；合約 25 項（做空、槓桿與保證金、停損方向、資金費、現貨不能做空） |
| `references/ai-agents.md` | Claude Code / Claude Desktop / claude.ai / Grok / 其他 AI 的安裝方式 |

指令：`OPEN`（開倉並掛止損；合約為逐倉、指定槓桿、多或空）、`HOLD`、`MOVE_STOP`（停損只往有利方向：多單往上、空單往下）、`CLOSE`（引擎出場）、`CLOSE_NOW`（價格穿過停損）、`MISSED`（不追價）、`WAIT`、`SHADOW`（未通過驗證的 EA，只看不做）、`BLOCKED`、`ENGINE_DOWN`、`ERROR`。預設 PAPER；實盤與解除 HALT 只有使用者能在終端機互動確認，AI 不能做。

## 維護 Agent（確保 EA 持續有效）

| 元件 | 作用 |
|---|---|
| `agents/ea-maintainer.md`（`.claude/agents/` 有連結） | Claude Code 子代理：例行檢查、診斷、寫維護紀錄、開 issue、只能透過候選版本流程改版 |
| `maintenance/ea_guard.py` | 健康檢查引擎：`forward`（凍結參數跑 2026-11-01 之後的新資料）、`live`（實盤 API 守衛，HALT 時自動 `/stopentry`）、`replay`、`baseline` |
| `maintenance/maintenance-protocol.md` | 事前登記的檢查項目 C1–C7、門檻、各狀態動作、Agent 能做與不能做的事、改版與 ETH 升級條件 |
| `maintenance/baselines.json` | 每個 EA 由驗證過的歷史算出的「正常範圍」（區塊自助法回撤、連敗、10 筆獲利因子、上漲捕捉率） |
| `maintenance/log.md` | 維護紀錄（第一次前向檢查、回放自我測試、研究線索） |
| `.github/workflows/ea-health.yml` | 每週一自動前向檢查；DEGRADED/HALT 時開或更新 `ea-health` issue |
| `deploy/docker-compose.yml` 的 `ea-guard` | 每 15 分鐘檢查三個機器人；HALT 時送 `/stopentry`（只停新進場，不平倉、不恢復） |

自我測試：守衛在 2025–26 熊市逐月回放，真的 EA 22 個月全部 HEALTHY；故意弄壞的版本第 2 個月就 DEGRADED、後來 HALT。實盤守衛對模擬 API 的整合測試 7/7 通過（`maintenance/test_guard_live.py`）。

## 規則（給執行這個 skill 的 agent）

1. 調參只能在研發期 `20210601-20241212`；V1/V2/V3 每個 EA 版本只跑一次。改規則就是新版本：改 `freqai.identifier` 與策略名稱，重新登記、重新驗證。合約 EA 的多單參數就是現貨 EA 的凍結參數，兩邊都不能改。
2. 回報時一定附上：驗證是否通過（逐條）、最差年份、盯市最大回撤、同期買入持有；合約 EA 另附多單 / 空單損益、資金費、強平次數。不能只報總報酬。
5. 合約只用逐倉與策略給的槓桿（1–3 倍）；不提高槓桿、不改全倉、不讓部位名目超過權益。
3. 不在 repo 或設定檔寫入 API 金鑰；金鑰只放 `deploy/ea.env`（git-ignored）並關閉提幣權限。
4. 新 EA 上線前至少 30 天 dry-run，並與同期回測比對。

## 常用指令

```bash
SK=skills/freqai-ea-trading
bash $SK/scripts/setup_env.sh
export FT_VENV=~/crypto-trading/venvs/freqai-ea FT_HOME=~/crypto-trading/freqai-ea/user_data
PY=$FT_VENV/bin/python
$PY $SK/scripts/download_binance_vision.py --pairs BTC/USDT ETH/USDT --timeframes 1h 15m --start 2017-08 --datadir $FT_HOME/data/binance
$PY $SK/scripts/download_binance_vision.py --pairs SOL/USDT AVAX/USDT NEAR/USDT DOT/USDT ADA/USDT LINK/USDT DOGE/USDT --timeframes 1h 15m --start 2020-01 --datadir $FT_HOME/data/binance
$PY $SK/scripts/download_binance_vision.py --trading-mode futures --pairs BTC/USDT ETH/USDT SOL/USDT AVAX/USDT NEAR/USDT DOT/USDT ADA/USDT LINK/USDT DOGE/USDT --timeframes 1h 15m --start 2020-01 --datadir $FT_HOME/data/binance
$PY $SK/scripts/perp_proxy.py --datadir $FT_HOME/data/binance              # 只在跑合約 V1 驗證前需要（2020 以前用現貨代用）

$PY $SK/scripts/ea_lab.py backtest --market perp --coin eth --userdir $FT_HOME --keep runs/eth_perp   # 合約 EA 研發期回測
$PY $SK/scripts/ea_lab.py validate --market perp --coin eth --userdir $FT_HOME                        # 合約 EA 事前登記驗證

$PY $SK/scripts/ea_lab.py backtest --coin btc --userdir $FT_HOME --keep runs/btc      # 研發期回測
$PY $SK/scripts/ea_lab.py validate --coin btc --userdir $FT_HOME                       # 事前登記的驗證
$PY $SK/scripts/tv_research.py \
    --run "runs/btc/<result>.zip::BTC EA" --datadir $FT_HOME/data/binance --models $FT_HOME/models --out ea.html

python3 $SK/desk/ea_engine.py start                                                      # AI 交易台用的無金鑰引擎 + 守衛
python3 $SK/desk/ea_desk.py signals                                                     # 每個幣的指令（AI 每輪呼叫）
docker compose -f $SK/deploy/docker-compose.yml up -d --build                          # 或：Freqtrade 用金鑰直接交易（預設 dry-run）+ 實盤守衛
$PY $SK/maintenance/ea_guard.py forward --market perp --all --userdir $FT_HOME          # 合約 EA 前向健康檢查（新資料）
$PY $SK/maintenance/ea_guard.py forward --all --userdir $FT_HOME                        # 現貨 EA 前向健康檢查
```

交易所 API 被擋的環境（例如雲端沙盒）回測時加 `FT_OFFLINE=1`。
