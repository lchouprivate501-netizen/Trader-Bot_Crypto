# Trader Bot

Grok Bot「Trader」的私人交易公司：**研發部**在 nautilus_trader 上研發、回測、優化短線/剝頭皮策略；**執行部**只拿通過門檻的策略，依紀律在瀏覽器登入的交易所交易 USDT 永續（預設 **Pionex**，2 倍逐倉、可多可空）。所有工具透過同一個 stdio MCP 連接器提供。

- 不持有交易所金鑰、程式不下單；下單只由 Trader 在瀏覽器進行。
- 不使用任何 LLM 模型或付費工具；分析是純規則的多時間框架分析。
- 起始模式 **PAPER**。策略在樣本外通過全部門檻後，Trader 自行切 **LIVE** 並通知使用者。
- 安裝：見 [INSTALL.md](INSTALL.md)（`bash bootstrap.sh`）。每輪怎麼做：見 [docs/TRADER_PLAYBOOK.md](docs/TRADER_PLAYBOOK.md)。

倉庫：https://github.com/lchouprivate501-netizen/pionex-macd  
本機目錄 `~/crypto-trading/pionex-macd`、venv `~/crypto-trading/venvs/pionex-trading-skills`、模組 `pionex_trading_skills` 是現有連接器的相容入口，請不要改掉這三個路徑／名稱。

## 組織圖（13 個角色）

### 研發部（6 人）— `rnd/`

| 角色 | 負責 | 用的工具/程式 |
|---|---|---|
| 1. 想策略 | 從執行部紀錄與市場觀察提出假設，登記為 `idea` | `rnd_registry`、`journal/events.jsonl`、`rnd/strategies/registry.json` |
| 2. 寫程式 | 依模板把策略寫成 `rnd/strategies/<name>.py`（`signals()`、`near()`、`SPACE`） | `rnd/strategies/base.py` |
| 3. 回測 | nautilus_trader 組合層級回測（手續費用啟用中交易所的 taker、硬性風控同實盤） | `rnd_run_backtest` → `rnd/engine.py` |
| 4. 優化 | optuna 只在前 70% 資料、少量參數、≤300 次 | `rnd/optimize.py`（`rnd_run_backtest(trials=…)`） |
| 5. 看報表 | 樣本外門檻表 PASS/FAIL、各幣種/各月份拆解 | `rnd_report` → `rnd/report.py` |
| 6. 改策略 | 依報表與實盤紀錄修改或淘汰策略（改完是新版本，要重新走完整流程；不准對樣本外調參） | `rnd_registry`、`rnd_report` |

### 執行部（7 人）— `exec/`

| 角色 | 負責 | 用的工具 |
|---|---|---|
| 7. 消息面 | 找出危險、不可交易時段（USD 高影響數據、OKX 公告），失敗即封鎖 | `news_danger_windows` |
| 8. 掃描市場 | 啟用中交易所白名單內，依 24h 成交額選前 10–15 名，附波動率 | `market_scan` |
| 9. 篩選 | 快要觸發策略的標的 | `shortlist` |
| 10. 分析 | 規則式多時間框架分析（5m/15m/1h/4h、RSI、ATR、資金費率），提供第二意見 | `analyze_symbol` |
| 11. 交易計劃 | 只取 `tradable=true` 訊號：進場/停損/停利/數量/有效期 | `live_signals` |
| 12. 風險管控 | 硬性上限（不可放寬）：每筆 ≤0.5% 風險、日虧 3% 停新單、回撤 15% HALT、連虧 7 筆停 24h、單幣保證金 ≤10%、最多 3 倉、2x 逐倉、禁止提幣/轉帳 | `risk_check`、`risk_state` |
| 13. 交易紀錄 | 成交、權益、決策與放棄原因寫入帳本與日誌，回流研發部 | `journal_write` |

公司層級：`company_status`、`mode_get` / `mode_set`、`job_status`、`setup_check`、`exchange_get` / `exchange_set`。

## 工作循環

```mermaid
flowchart LR
  subgraph RND[研發部]
    A[想策略] --> B[寫程式] --> D[優化<br/>前70%] --> C[回測<br/>nautilus] --> E[看報表<br/>後30%門檻]
    E -->|REJECTED| F[改策略] --> B
  end
  E -->|PASSED| G{{登記簿 PASSED}}
  G -->|Trader mode_set LIVE<br/>並通知使用者| X
  subgraph X[執行部 每 5 分鐘]
    N[消息面] --> S[掃描] --> L[篩選] --> AN[分析] --> P[交易計劃] --> R[風控] -->|approved| O[(瀏覽器下單)]
    O --> J[交易紀錄]
  end
  J -->|實盤績效| A
  R -->|回撤15%| H[HALT]
```

## 更換或新增交易所

預設是 Pionex（`company/exchanges/pionex.json`，由 `company/exchange.json` 指向）。

1. 呼叫 `exchange_get` 查看目前設定與可用設定檔。
2. 若要沿用 Pionex：不用改。
3. 若要新增或更換：複製 `company/exchanges/_template.json` 為 `<name>.json` 並填欄位，或把同一份 JSON 傳給 `exchange_set`。也可以 `exchange_set("pionex")` 切回預設。
4. 交易所必須支援 USDT 保證金永續、逐倉、至少 2 倍槓桿。下單永遠只在瀏覽器進行。
5. **不要**在設定檔或對話中提供 API 金鑰；含金鑰欄位的請求會被拒絕。
6. `LIVE` 且仍有未平倉時，`exchange_set` 會拒絕（fail-closed）。更換成功後會依新白名單重掃市場；回測與風控手續費用該設定檔的 taker。

## 自動轉實盤門檻（`company/live_criteria.json`）

樣本外（最後 30%，從未用於調參）必須**全部**通過：交易 ≥300 筆、扣費後獲利因子 ≥1.3、最大回撤 ≤15%、平均每筆淨利 ≥2× 來回手續費、扣掉最好的單一幣種/月份/前兩筆後淨利仍 > 0。

## 使用的開源專案

| 專案 | 網址 | 版本 | 授權 | 用途 |
|---|---|---|---|---|
| nautilus_trader | https://github.com/nautechsystems/nautilus_trader | 1.231.0 | LGPL-3.0-or-later | 研發部組合層級回測引擎 |
| optuna | https://github.com/optuna/optuna | 5.0.0 | MIT | 只在樣本內（前 70%）調參 |
| mcp (Python SDK) | https://github.com/modelcontextprotocol/python-sdk | 2.3.0 | MIT | stdio MCP 伺服器 |
| uv | https://github.com/astral-sh/uv | 0.13.8 | Apache-2.0 / MIT | 安裝器與虛擬環境 |
| graphify (`graphifyy`) | https://github.com/Graphify-Labs/graphify | 0.9.108 | Apache-2.0 | 程式庫知識圖譜（獨立 venv） |
| pandas | https://github.com/pandas-dev/pandas | 2.3.3 | BSD-3-Clause | 資料與訊號 |
| pyarrow | https://github.com/apache/arrow | 26.0.1 | Apache-2.0 | Parquet K 線 |
| requests | https://github.com/psf/requests | 2.32.5 | Apache-2.0 | OKX / 日曆等公開 HTTP |

本倉庫自行撰寫的部分為 MIT（見 LICENSE）。市場資料來自 OKX 公開 REST（不需金鑰）；經濟日曆來自 ForexFactory 公開週曆 JSON。

## 目錄

| 路徑 | 內容 |
|---|---|
| `company/` | 硬性風控、上線門檻、交易所設定檔、回測標的、共用路徑與 OKX 公開資料 |
| `rnd/` | 資料下載、策略模板與種子策略、nautilus 回測、optuna 優化、報表、`strategies/registry.json` |
| `exec/` | 消息面、掃描、篩選、分析、訊號、風控、帳本、日誌、單輪週期 |
| `mcp/` | MCP 套件 `pionex_trading_skills`（相容模組名） |
| `scripts/` | 5 分鐘排程器、MCP 煙霧測試、交易所設定檔測試 |
| `state/`、`journal/` | 模式、帳本、權益與日誌（本機，不進 git） |

手續費來自啟用中交易所設定檔；Pionex 預設 maker 0.02%、taker 0.05%。回測與風控一律以 taker/邊計算（保守）。資金費率未計入回測。
