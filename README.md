# Trader-Bot_Crypto：BTC / ETH / SOL 趨勢跟隨 EA（Freqtrade + FreqAI）

三個只做多、現貨的自動交易 EA（Expert Advisor），每個針對一個幣種設計，參數凍結、依**事前登記**的協議驗證過。可以交給 Freqtrade 用金鑰直接交易，也可以交給 **AI（Claude、Grok 或其他支援 MCP 的 AI）**：無金鑰的引擎算出該做什麼，AI 照指令在你的交易所下單。附維護 Agent，持續檢查 EA 是否還有效。

> 不保證獲利。趨勢跟隨的代價：牛市跑輸買入持有、熊市只能空手、每年只有 4–5 筆。回測最大回撤約 30%。上線前至少 30 天 PAPER / dry-run。

## 三個 EA

| EA | 設計 | 驗證判定 | 從未測過的 2018-06 → 2021-06 | 2024-12 → 2026-10 熊市 |
|---|---|---|---|---|
| `BTCTrendEA` | 100 日 EMA 之上、突破前 240 小時高點進場；10 倍日波動的吊燈停損 | **通過** | +137.9%，回撤 31.1%（持有 +395.5% / 70.4%），獲利因子 3.76，17 筆 | +0.7%（持有 −23.1%） |
| `ETHRiskOnEA` | 只在 BTC 處於 100 日多頭時，交易 ETH 在 50 日 EMA 之上的突破 | **未通過**（只有 12 筆 < 15） | +192.5%，回撤 22.9%（持有 86.8%），獲利因子 14.3 | +27.2%（持有 −40.9%） |
| `SOLMomentumEA` | 50 日 EMA 上升中、突破前 720 小時高點；最寬的停損、最小的部位 | **通過** | 規則原封不動套到 6 個沒研究過的幣：6/6 獲利，平均 +36% | +1.4%（持有 −58.0%） |

共同引擎 `EABase`：突破進場 → 停損單掛在交易所並依吊燈停損上移 → 跌破趨勢（ETH 另加 BTC 轉弱）出場；FreqAI（LightGBM、purged walk-forward）預測波動，用來決定部位大小，讓每筆停損約虧 EA 資金的 10%。ETH 未通過是樣本數不足，依協議不能事後放寬，所以只做影子紀錄。細節：[`validation-results.md`](skills/freqai-ea-trading/references/validation-results.md)。

## 功能

| 功能 | 說明 | 位置 |
|---|---|---|
| EA 策略 | 三個 EA 與共用引擎、FreqAI 模型、Binance 現貨設定（預設 dry-run） | `skills/freqai-ea-trading/user_data/` |
| AI 交易台 | 每個幣一條指令（OPEN / MOVE_STOP / CLOSE…）、下單前風控、帳本、HALT、使用者專屬的實盤開關 | `desk/ea_desk.py` |
| MCP 伺服器 | `freqai-ea-desk`：`ea_guide`、`ea_status`、`ea_signals`、`ea_risk_check`、`ea_record`、`ea_halt`；只用 Python 標準函式庫 | `desk/mcp_server.py` |
| 無金鑰引擎 | 背景執行三個 Freqtrade dry-run 機器人與守衛，REST 只聽本機 | `desk/ea_engine.py` |
| 研發與驗證 | 回測、只限研發期的調參、事前登記的 V1–V4 驗證（自動判 PASS/FAIL） | `scripts/ea_lab.py`、`references/validation-protocol.md` |
| 回測工具 | 歷史資料下載、離線回測、盯市回撤報告、出場分析、FreqAI 預測力檢查 | `scripts/` |
| TradingView 研究圖 | Lightweight Charts™ 多面板研究頁（K 線、趨勢、突破線、交易、權益 vs 持有、回撤、FreqAI 波動） | `scripts/tv_research.py`、`tradingview/` |
| 維護 Agent | 每週用新資料跑凍結的 EA，和驗證過的正常範圍比較，判 HEALTHY / WATCH / DEGRADED / HALT；HALT 自動停止新進場 | `agents/ea-maintainer.md`、`maintenance/` |
| 自動化 | GitHub Actions：每週健康檢查（開 issue）、交易台測試 | `.github/workflows/` |
| Freqtrade 直接交易 | Docker Compose：三個 EA 各一個容器 + 實盤守衛 | `deploy/` |

（`desk/`、`scripts/`、`maintenance/` 等都在 `skills/freqai-ea-trading/` 底下。）

## 快速開始

```bash
git clone https://github.com/lchouprivate501-netizen/Trader-Bot_Crypto
cd Trader-Bot_Crypto
bash skills/freqai-ea-trading/scripts/setup_env.sh          # Freqtrade 2026.10 + FreqAI（約 1–2 GB）
python3 skills/freqai-ea-trading/desk/ea_engine.py start     # 三個無金鑰引擎 + 守衛（第一次要訓練幾分鐘）
python3 skills/freqai-ea-trading/desk/ea_engine.py status    # 等 usable=true
python3 skills/freqai-ea-trading/desk/ea_desk.py signals     # 每個幣現在該做什麼
```

接著把 AI 接上（下一節），讓它每 5–15 分鐘跑一輪。預設 PAPER（只記錄不下單）；實盤只有你能在終端機打開：`python3 skills/freqai-ea-trading/desk/ea_desk.py live on`。每個 EA 的資金在 `~/.freqai-ea/config.json` 設定（預設 1000 USDT）。

## 接上 AI

Claude Code（skill ＋ 維護 Agent ＋ MCP 伺服器一次裝好）：

```
/plugin install freqai-crypto-trading --marketplace lchouprivate501-netizen/Trader-Bot_Crypto
```

舊版 Claude Code：`/plugin marketplace add lchouprivate501-netizen/Trader-Bot_Crypto`，再 `/plugin install freqai-crypto-trading@trader-bot-crypto`。

Claude Desktop、Grok、Cursor 等支援 MCP 的 AI：新增 stdio MCP 連接器，`command` = `python3`，`args` = `<倉庫>/skills/freqai-ea-trading/desk/mcp_server.py`。只能執行指令的 AI 用 `python3 skills/freqai-ea-trading/desk/ea_desk.py …`。完整說明：[`ai-agents.md`](skills/freqai-ea-trading/references/ai-agents.md)；AI 的作業手冊：[`AGENTS.md`](skills/freqai-ea-trading/AGENTS.md)。

## 安全設計

- 不需要、也不接受交易所金鑰：引擎強制 dry-run，AI 在你的交易所頁面下單。
- AI 不能開實盤、不能解除 HALT（要你在終端機互動確認）；任何時候都能 `ea_halt` 停止新進場。
- 下單前風控：數量不超過 EA 的部位比例、單筆風險 ≤ 資金 10%、不追高超過 2%、守衛 HALT 或累計虧損達資金 35% 就停新單。
- 停損單一定掛在交易所，只能往上移；引擎壞掉時不開新倉、保留停損。
- 想直接用 Freqtrade 自動下單的人：[`deployment.md`](skills/freqai-ea-trading/references/deployment.md)（金鑰只放 git-ignored 的 `deploy/ea.env`，關閉提幣權限）。

## 目錄

| 路徑 | 內容 |
|---|---|
| `skills/freqai-ea-trading/SKILL.md` | Skill 說明（Claude 會自動讀取） |
| `skills/freqai-ea-trading/AGENTS.md` | AI 作業手冊 |
| `skills/freqai-ea-trading/user_data/` | 策略 `EABase`、`BTCTrendEA`、`ETHRiskOnEA`、`SOLMomentumEA`；FreqAI 模型；設定檔 |
| `skills/freqai-ea-trading/desk/` | AI 交易台、MCP 伺服器、引擎啟動器、預設設定、整合測試 |
| `skills/freqai-ea-trading/scripts/` | `setup_env.sh`、`download_binance_vision.py`、`ea_lab.py`、`ft_offline.py`、`mtm_report.py`、`exit_analysis.py`、`prediction_quality.py`、`tv_research.py` |
| `skills/freqai-ea-trading/maintenance/` | 健康檢查引擎 `ea_guard.py`、維護協議、基準線、維護紀錄與報告 |
| `skills/freqai-ea-trading/references/` | 設計、驗證協議與結果、部署、AI 安裝、完整驗證輸出 |
| `skills/freqai-ea-trading/tradingview/` | Lightweight Charts 版本鎖定（npm）、頁面模板、研究筆記 |
| `skills/freqai-ea-trading/deploy/` | Dockerfile、docker-compose、`ea.env.example` |
| `agents/ea-maintainer.md` | EA 維護 Agent（`.claude/agents/` 有連結） |
| `.claude-plugin/` | Claude Code 外掛與外掛市集清單 |
| `.github/workflows/` | `ea-health.yml`（每週健康檢查）、`ea-desk-test.yml`（交易台測試） |
| `AGENTS.md` | 給所有 AI 的倉庫說明與規則 |

## 使用的開源專案

| 專案 | 網址 | 版本 | 授權 | 用途 |
|---|---|---|---|---|
| Freqtrade（含 FreqAI） | https://github.com/freqtrade/freqtrade | 2026.10 | GPL-3.0 | 回測與交易引擎（獨立 venv，`scripts/setup_env.sh`） |
| LightGBM | https://github.com/microsoft/LightGBM | 4.7.0 | MIT | FreqAI 模型 |
| TA-Lib（Python） | https://github.com/TA-Lib/ta-lib-python | 0.8.3 | BSD-2-Clause | 指標 |
| pandas / NumPy | https://github.com/pandas-dev/pandas | — | BSD-3-Clause | 資料處理 |
| TradingView Lightweight Charts™ | https://github.com/tradingview/lightweight-charts | 5.2.1 | Apache-2.0 | 研究圖表（npm，`tradingview/`） |

歷史資料來自 Binance 公開資料庫 data.binance.vision；參考價來自 OKX / Binance 公開 API（都不需金鑰）。本倉庫自行撰寫的部分為 MIT（見 [LICENSE](LICENSE)），第三方元件見 [NOTICE](NOTICE)。
