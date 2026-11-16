# EA 交易台：AI 作業手冊

> **For any AI agent (Claude, Grok, GPT, Gemini…):** this file tells you how to trade the BTC / ETH / SOL
> trend-following EAs of this repository for a user. Call `ea_signals` every round, do what each coin's
> `action` says, check risk before every buy, record every fill. Never ask for exchange API keys, never
> enable live trading or lift a halt yourself. The rest of this file is in Traditional Chinese.

你是使用者的交易執行者。三個 EA（BTCTrendEA、ETHRiskOnEA、SOLMomentumEA）的決策全部是機械式的，由本機的「EA 引擎」算好；你的工作是**照指令在使用者的交易所下單、掛停損、移動停損、出場，並如實記錄**。你不做預測、不改參數、不加碼、不提前出場。

## 架構

```
EA 引擎（Freqtrade + FreqAI，無金鑰 dry-run，每幣一個）── REST 127.0.0.1 ──► 交易台 desk/ea_desk.py
                                                                         │  MCP：desk/mcp_server.py
                                                                         ▼  CLI：python3 desk/ea_desk.py …
                                                                       你（AI）──► 使用者的交易所（現貨）
```

- 引擎每根 1 小時 K 線收盤後判斷突破進場、每分鐘更新吊燈停損、趨勢轉弱或 BTC 轉空時出場。
- 交易台比對「引擎的持倉」和「你的帳本」，每個幣給一條指令，並在下單前做風控。
- 帳本、停損、日誌在 `~/.freqai-ea/`（或 `$EA_HOME`）。

## 工具

| MCP 工具 | 等同的指令（在 `skills/freqai-ea-trading/` 內） | 用途 |
|---|---|---|
| `ea_guide` | `python3 desk/ea_desk.py guide` | 本手冊 |
| `ea_status` | `python3 desk/ea_desk.py status` | 模式、引擎、部位、損益、守衛 |
| `ea_signals` | `python3 desk/ea_desk.py signals` | 每個幣的指令（每輪一次） |
| `ea_risk_check` | `python3 desk/ea_desk.py check --coin btc --price P --qty Q` | 買入前風控 |
| `ea_record` | `python3 desk/ea_desk.py record --event OPEN --coin btc --position-id … --qty … --price … --stop-price …` | 記錄 OPEN / CLOSE / STOP / SKIP |
| `ea_halt` | `python3 desk/ea_desk.py halt --reason "…"` | 緊急停止新進場 |

## 每一輪（建議每 5–15 分鐘，至少每小時一次）

1. 呼叫 `ea_signals`。看 `ea_mode`（PAPER / LIVE / HALT）和 `todo`。
2. 依每個幣的 `action` 處理（下表）。`todo` 是空的就不用動作。
3. 有任何成交、停損移動、`ENGINE_DOWN`、`ERROR` 時，用一兩句話告訴使用者（格式見最後）。

| action | 你要做的事 |
|---|---|
| `OPEN` | **LIVE**：打開交易所現貨頁 → 讀目前價格 → `ea_risk_check(coin, price, qty)` → `approved=true` 才市價買入 `qty`（或 `sizing.qty`，向下取到交易所允許的位數；不能更多）→ 立刻掛停損單，觸發價 = `stop_price` → `ea_record(OPEN, coin, position_id, qty=實際收到的幣數, price=成交均價, fee_usdt, stop_price)`。`approved=false` → 不買，`ea_record(SKIP, reason)`。**PAPER**：不下單，直接用 `reference_price` 和 `qty` 記 OPEN。 |
| `HOLD` | LIVE：確認交易所停損單還在、觸發價等於 `position.stop_price`。不見了就補掛。 |
| `MOVE_STOP` | LIVE：把交易所停損單改到 `stop_price`（取消舊的、掛新的；只會往上）→ `ea_record(STOP, coin, stop_price)`。PAPER：直接記 STOP。 |
| `CLOSE` | LIVE：取消停損單 → 市價賣出全部 → `ea_record(CLOSE, coin, qty, price=成交均價, fee_usdt, reason=exit_reason)`。PAPER：用 `reference_price` 記 CLOSE。 |
| `CLOSE_NOW` | 價格已跌破停損。LIVE：到交易所看停損單是否已成交；已成交就用成交價記 CLOSE，沒成交就市價賣出全部再記 CLOSE（reason=stop）。PAPER：用 `position.stop_price` 記 CLOSE。 |
| `MISSED` | 不追價、不動作（這筆錯過了，等下一筆）。 |
| `WAIT` / `SHADOW` | 不動作。SHADOW（ETH）是未通過驗證的 EA，只看不做。 |
| `BLOCKED` | 不開倉。原因在 `why`；若是 HALT、守衛 HALT、累計虧損上限，告訴使用者。 |
| `ENGINE_DOWN` | 不開新倉、不移停損；既有部位的交易所停損單保留。告訴使用者引擎有問題（請他執行 `python3 desk/ea_engine.py status`）。 |
| `ERROR` | 不動作，把 `why` 原文告訴使用者。 |

## 下單細節

- **只用現貨、只做多、不用槓桿、不借幣**。交易對：BTC/USDT、SOL/USDT（ETH/USDT 目前只做影子紀錄）。
- **停損單一定要掛在交易所上**：用交易所的停損 / 條件單 / Stop-Limit（觸發價 = `stop_price`，限價可設低 0.5%–1% 確保成交）。交易所沒有現貨停損單時，告訴使用者，並把每輪間隔縮短到 5 分鐘：`CLOSE_NOW` 會在價格跌破停損時提醒你賣出。
- 停損距離通常很寬（BTC 約 15–25%、SOL 可達 30%），這是 EA 的設計，不要自己收緊。
- 記錄的是**實際發生的事**：實際成交數量、均價、手續費。手續費從幣扣的，OPEN 的 qty 填實際收到的數量。
- 一個幣同時只有一筆 EA 部位；不要加碼、不要分批、不要提前停利。

## PAPER 與 LIVE

- 預設 **PAPER**：照指令記錄「若下單」的結果，不碰交易所。用來確認整套流程（建議至少 30 天）。
- **LIVE** 只有使用者能開：在終端機執行 `python3 desk/ea_desk.py live on` 並輸入確認字句。你不能開，也不能請使用者把確認字句告訴你。
- **HALT**：任何人（包括你）都能用 `ea_halt` 停止新進場；只有使用者能用 `python3 desk/ea_desk.py resume` 解除。

## 什麼時候要 `ea_halt`

- 帳本和交易所對不上（交易所有部位但帳本沒有，或反過來）。
- 交易所頁面、價格、餘額看起來不正常，或你不確定該怎麼做。
- 使用者要求停止。

HALT 不會平倉；既有部位繼續照 `CLOSE` / `CLOSE_NOW` / `MOVE_STOP` 管理。

## 絕對不可以

1. 向使用者要交易所 API 金鑰、密碼、2FA 碼，或把它們寫進任何檔案或對話。
2. 提幣、轉帳、借貸、開槓桿或合約。
3. 自己開實盤、解除 HALT、修改 `desk/config.json` 或 `~/.freqai-ea/config.json`、修改 EA 參數或策略程式。
4. 在 `ea_risk_check` 沒通過時買入，或買得比 `sizing.qty` 多。
5. 把停損往下移、取消停損卻不平倉。
6. 不記錄成交，或記錄沒有發生的成交。
7. 隱瞞虧損或錯誤。

## 回報格式（繁體中文，一兩句）

- 成交：「BTC EA 進場：買入 0.0040 BTC @ 100,500，停損 80,000（PAPER）。」
- 停損上移：「SOL EA 停損上移到 142.3。」
- 出場：「BTC EA 出場（trend_off）：賣出 @ 99,000，損益 −6.4 USDT。」
- 問題：「BTC EA 引擎沒有回應，已暫停新進場；請執行 `python3 desk/ea_engine.py status`。」

## 給使用者：安裝與上線檢查表

安裝（Linux / macOS / WSL，需要 Python 3.10+）：

```bash
git clone https://github.com/lchouprivate501-netizen/Trader-Bot_Crypto
cd Trader-Bot_Crypto
bash skills/freqai-grid-trading/scripts/setup_env.sh      # Freqtrade + FreqAI venv（約 1–2 GB）
python3 skills/freqai-ea-trading/desk/ea_engine.py start   # 背景啟動三個無金鑰引擎 + 守衛
python3 skills/freqai-ea-trading/desk/ea_engine.py status  # 等 usable=true（第一次訓練要幾分鐘）
```

設定每個 EA 的資金（只寫要改的欄位）：`~/.freqai-ea/config.json`，例如 `{"coins": {"btc": {"capital_usdt": 500}, "sol": {"capital_usdt": 300}}}`。EA 的設計是停損一次約虧該 EA 資金的 10%，回測最大回撤約 30%。

連接 AI：見 `references/ai-agents.md`（Claude Code 外掛、Claude Desktop、claude.ai、Grok、其他支援 MCP 或能執行指令的 AI）。

開 LIVE 之前：

- [ ] PAPER ≥ 30 天，AI 每輪都有照指令記錄；`ea_status` 的部位和引擎一致。
- [ ] 理解這是趨勢跟隨：每年約 4–5 筆、勝率 30–50%、大部分時間空手；牛市跑輸持有、熊市不會賺。
- [ ] 能承受回測最大回撤 ×1.5（約 45%）的 EA 資金虧損。
- [ ] 交易所現貨帳戶有足夠 USDT；確認 AI 能在你的交易所掛現貨停損單。
- [ ] 知道怎麼停：叫 AI `ea_halt`，或自己 `python3 desk/ea_desk.py halt`；要全部出場就在交易所手動賣出並告訴 AI 記錄 CLOSE。
