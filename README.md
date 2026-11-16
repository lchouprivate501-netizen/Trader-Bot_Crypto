# Trader-Bot_Crypto：BTC / ETH / SOL 合約 EA（Freqtrade + FreqAI）

全自動的趨勢跟隨 EA（Expert Advisor），每個幣用**驗證通過**的那一個：**ETH、SOL 用合約 EA**（USDT 永續、多空、逐倉），**BTC 用現貨 EA**（只做多；BTC 的合約 EA 未通過驗證）。參數凍結、依**事前登記**的協議驗證過。可以交給 Freqtrade 用金鑰直接交易，也可以交給 **AI（Claude、Grok 或其他支援 MCP 的 AI）**：無金鑰的引擎算出該做什麼，AI 照指令在你的交易所下單。附維護 Agent，持續檢查 EA 是否還有效。

> 不保證獲利。趨勢跟隨的代價：牛市跑輸買入持有、多單要付資金費、回撤可能到 25–36%。上線前至少 30 天 PAPER / dry-run。

## 主要策略：合約 EA

多單沿用驗證過的現貨 EA（突破進場、寬吊燈停損、跌破趨勢出場）；空單只在趨勢 EMA 已經下降 30 天時、價格跌破前 N 小時低點才進場，用 **3 倍日波動的緊停損**（熊市反彈又快又猛），趨勢轉多就出場。逐倉，槓桿 1–3 倍、讓清算價距離 ≥ 2 倍停損距離（槓桿只減少保證金，不放大部位）。FreqAI（LightGBM、purged walk-forward）預測波動，決定部位大小，讓每筆停損約虧 EA 資金的 10%。

| 合約 EA | 判定 | 從未測過的 2018-06 → 2021-06 | 2024-12 → 2026-10 熊市 | 全歷史連續回測 |
|---|---|---|---|---|
| `ETHFuturesEA` | **通過** | +219.6%，回撤 26.6%（持有 +366% / 86.8%），PF 3.70，32 筆；2018 年 +44%（持有 −77%） | **+65.7%**（持有 −40.9%），回撤 20.4% | 2018-06 → 2026-10 +1,046%，回撤 26.6%，0 次強平 |
| `SOLFuturesEA` | **通過** | SOL 規則原封不動套到 6 個沒研究過的幣：5/6 獲利、平均 +50.3%、回撤 36%（持有 93%） | +7.4%（持有 −58.0%），回撤 25.4% | 2021-06 → 2026-10 +448%，回撤 35.8%，0 次強平 |
| `BTCFuturesEA` | 未通過（熊市 −6.9%、空單合計虧損） | +92.4%，回撤 34.0% | −6.9%（持有 −23.1%） | 只做影子紀錄 |

每邊手續費 0.05%、含資金費。2020 年以前沒有永續資料，2018–2019 用現貨價格代替、資金費設為 0（事前寫在協議裡）。細節：[`futures-validation-results.md`](skills/freqai-ea-trading/references/futures-validation-results.md)、研究過程：[`futures-design.md`](skills/freqai-ea-trading/references/futures-design.md)。

**BTC 用現貨 EA** `BTCTrendEA`（驗證通過）：2018-06 → 2021-06 +137.9%，回撤 31.1%（持有回撤 70.4%）；2024-12 → 2026-10 +0.7%（持有 −23.1%）。見 [`validation-results.md`](skills/freqai-ea-trading/references/validation-results.md)。

## 功能

| 功能 | 說明 | 位置 |
|---|---|---|
| 合約 EA | `FuturesEABase` 與 BTC/ETH/SOL 合約 EA：多空、逐倉、槓桿規則、30% 價格停損上限；Binance USDT-M 永續設定（預設 dry-run） | `user_data/strategies/`、`user_data/configs/*_perp.json` |
| 現貨 EA | `EABase` 與 `BTCTrendEA`、`ETHRiskOnEA`、`SOLMomentumEA`（只做多） | `user_data/strategies/`、`user_data/configs/*_ea.json` |
| **AI 交易辦公室（控制台）** | 在瀏覽器裡看整個系統怎麼運作：行情室 → EA 引擎室（三個工位）→ 交易台 → AI 交易員 → 交易所，守衛與維護 Agent 在旁監看；每個角色正在做什麼、引擎的趨勢線／突破線／跌破線、止損路徑、部位、帳本與事件紀錄。即時模式讀本機引擎，回放模式用真實回測一步步重播 | `desk/console.py`、`desk/console/` |
| AI 交易台 | 每個幣一條指令（OPEN / MOVE_STOP / CLOSE…，含多空與槓桿）、開倉前風控、帳本（含資金費）、HALT、使用者專屬的實盤開關 | `desk/ea_desk.py` |
| MCP 伺服器 | `freqai-ea-desk`：`ea_guide`、`ea_status`、`ea_signals`、`ea_risk_check`、`ea_record`、`ea_halt`；只用 Python 標準函式庫 | `desk/mcp_server.py` |
| 無金鑰引擎 | 背景執行三個 Freqtrade dry-run 機器人（ETH、SOL 合約；BTC 現貨）與守衛，REST 只聽本機 | `desk/ea_engine.py` |
| 研發與驗證 | 回測、只限研發期的調參、事前登記驗證（自動判 PASS/FAIL）；`--market perp` 為合約 | `scripts/ea_lab.py`、`references/*protocol.md` |
| 回測工具 | 歷史資料下載（現貨與永續、標記價格、資金費）、2020 以前的永續代用資料、離線回測、盯市回撤報告、出場分析、FreqAI 預測力檢查 | `scripts/` |
| TradingView 研究圖 | Lightweight Charts™ 多面板研究頁（K 線、趨勢、突破線與跌破線、多空交易、權益 vs 持有、回撤、FreqAI 波動） | `scripts/tv_research.py`、`tradingview/` |
| 維護 Agent | 每週用新資料跑凍結的 EA（合約與現貨），和驗證過的正常範圍比較，判 HEALTHY / WATCH / DEGRADED / HALT；合約強平一律 ALERT；HALT 自動停止新進場 | `agents/ea-maintainer.md`、`maintenance/` |
| 自動化 | GitHub Actions：每週健康檢查（開 issue）、交易台測試 | `.github/workflows/` |
| Freqtrade 直接交易 | Docker Compose：ETH、SOL 合約 EA 與 BTC 現貨 EA 各一個容器 + 實盤守衛 | `deploy/` |

（`desk/`、`scripts/`、`maintenance/` 等都在 `skills/freqai-ea-trading/` 底下。）

## 快速開始

```bash
git clone https://github.com/lchouprivate501-netizen/Trader-Bot_Crypto
cd Trader-Bot_Crypto
bash skills/freqai-ea-trading/scripts/setup_env.sh          # Freqtrade 2026.10 + FreqAI（約 1–2 GB）
python3 skills/freqai-ea-trading/desk/ea_engine.py start     # 三個無金鑰引擎 + 守衛（第一次要訓練幾分鐘）
python3 skills/freqai-ea-trading/desk/ea_engine.py status    # 等 usable=true
python3 skills/freqai-ea-trading/desk/ea_desk.py signals     # 每個幣現在該做什麼
python3 skills/freqai-ea-trading/desk/console.py --open      # AI 交易辦公室：http://127.0.0.1:8765
```

沒有啟動引擎也可以先打開控制台：它會用 2024-12 → 2026-11 的真實回測回放，讓你看到三個 EA 在熊市裡怎麼做多、做空、移動止損與出場。`python3 skills/freqai-ea-trading/desk/console.py --export office.html` 可以匯出一個不需要伺服器的回放網頁。

接著把 AI 接上（下一節），讓它每 5–15 分鐘跑一輪。預設 PAPER（只記錄不下單）；實盤只有你能在終端機打開：`python3 skills/freqai-ea-trading/desk/ea_desk.py live on`。每個 EA 的資金在 `~/.freqai-ea/config.json` 設定（預設 1000 USDT）；不想用合約的話，可以在同一個檔把 SOL 改回現貨 `SOLMomentumEA`（也通過驗證）。

## 接上 AI

Claude Code（skill ＋ 維護 Agent ＋ MCP 伺服器一次裝好）：

```
/plugin install freqai-crypto-trading --marketplace lchouprivate501-netizen/Trader-Bot_Crypto
```

舊版 Claude Code：`/plugin marketplace add lchouprivate501-netizen/Trader-Bot_Crypto`，再 `/plugin install freqai-crypto-trading@trader-bot-crypto`。

Claude Desktop、Grok、Cursor 等支援 MCP 的 AI：新增 stdio MCP 連接器，`command` = `python3`，`args` = `<倉庫>/skills/freqai-ea-trading/desk/mcp_server.py`。只能執行指令的 AI 用 `python3 skills/freqai-ea-trading/desk/ea_desk.py …`。完整說明：[`ai-agents.md`](skills/freqai-ea-trading/references/ai-agents.md)；AI 的作業手冊：[`AGENTS.md`](skills/freqai-ea-trading/AGENTS.md)。

## 安全設計

- 不需要、也不接受交易所金鑰：引擎強制 dry-run，AI 在你的交易所頁面下單。
- 合約只用逐倉、只用引擎給的槓桿（清算價距離 ≥ 2 倍停損距離）；槓桿不放大部位。驗證與回測 0 次強平。
- AI 不能開實盤、不能解除 HALT（要你在終端機互動確認）；任何時候都能 `ea_halt` 停止新進場。
- 開倉前風控：數量不超過 EA 的部位比例、單筆風險 ≤ 資金 10%、不追價超過 2%、守衛 HALT 或累計虧損達資金 35% 就停新單。
- 止損單一定掛在交易所，只能往有利方向移（多單往上、空單往下）；引擎壞掉時不開新倉、保留止損。
- 想直接用 Freqtrade 自動下單的人：[`deployment.md`](skills/freqai-ea-trading/references/deployment.md)（金鑰只放 git-ignored 的 `deploy/ea.env`，關閉提幣權限）。

## 目錄

| 路徑 | 內容 |
|---|---|
| `skills/freqai-ea-trading/SKILL.md` | Skill 說明（Claude 會自動讀取） |
| `skills/freqai-ea-trading/AGENTS.md` | AI 作業手冊（合約與現貨的下單方式） |
| `skills/freqai-ea-trading/user_data/` | 策略（`FuturesEABase`、`{BTC,ETH,SOL}FuturesEA`、`EABase`、`BTCTrendEA`、`ETHRiskOnEA`、`SOLMomentumEA`）、FreqAI 模型、設定檔 |
| `skills/freqai-ea-trading/desk/` | AI 交易台、MCP 伺服器、AI 交易辦公室（`console.py`、`console/`）、引擎啟動器、預設設定、整合測試（現貨 51 項、合約 25 項、控制台 16 項） |
| `skills/freqai-ea-trading/scripts/` | `setup_env.sh`、`download_binance_vision.py`、`perp_proxy.py`、`ea_lab.py`、`replay_build.py`、`ft_offline.py`、`mtm_report.py`、`exit_analysis.py`、`prediction_quality.py`、`tv_research.py` |
| `skills/freqai-ea-trading/maintenance/` | 健康檢查引擎 `ea_guard.py`、維護協議、基準線（現貨與 `*_perp`）、維護紀錄與報告 |
| `skills/freqai-ea-trading/references/` | 合約與現貨的設計、驗證協議與結果、部署、AI 安裝、完整驗證輸出 |
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

歷史資料來自 Binance 公開資料庫 data.binance.vision（現貨、USDT-M 永續、標記價格、資金費率）；參考價來自 OKX / Binance 公開 API（都不需金鑰）。本倉庫自行撰寫的部分為 MIT（見 [LICENSE](LICENSE)），第三方元件見 [NOTICE](NOTICE)。
