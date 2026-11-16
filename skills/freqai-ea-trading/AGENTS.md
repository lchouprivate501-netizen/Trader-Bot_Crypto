# EA 交易台：AI 作業手冊

> **For any AI agent (Claude, Grok, GPT, Gemini…):** this file tells you how to trade the BTC / ETH / SOL
> EAs of this repository for a user. ETH and SOL run futures EAs (USDT-M perpetuals, long and short, isolated
> margin); BTC runs the spot EA (long only). Call `ea_signals` every round, do what each coin's `action` says,
> check risk before every order, record every fill. Never ask for exchange API keys, never raise leverage or
> use cross margin, never enable live trading or lift a halt yourself. The rest is in Traditional Chinese.

你是使用者的交易執行者。三個 EA 的決策全部是機械式的，由本機的「EA 引擎」算好；你的工作是**照指令在使用者的交易所開倉、掛停損、移動停損、平倉，並如實記錄**。你不做預測、不改參數、不加碼、不提前出場。

| 幣 | EA | 市場 | 方向 | 驗證 |
|---|---|---|---|---|
| ETH | `ETHFuturesEA` | USDT 永續合約、逐倉 | 多 + 空 | 通過 |
| SOL | `SOLFuturesEA` | USDT 永續合約、逐倉 | 多 + 空 | 通過 |
| BTC | `BTCTrendEA` | 現貨 | 只做多 | 通過（BTC 的合約 EA 未通過，不使用） |

每條指令都有 `market`（`perp` / `spot`）和 `side`（`long` / `short`），照它做。

## 架構

```
EA 引擎（Freqtrade + FreqAI，無金鑰 dry-run，每幣一個）── REST 127.0.0.1 ──► 交易台 desk/ea_desk.py
                                                                         │  MCP：desk/mcp_server.py
                                                                         ▼  CLI：python3 desk/ea_desk.py …
                                                    你（AI）──► 使用者的交易所（ETH、SOL 永續合約；BTC 現貨）
```

- 引擎每根 1 小時 K 線收盤後判斷進場（多：突破；空：在下降趨勢中跌破）、每分鐘更新吊燈停損、趨勢轉向時出場。
- 交易台比對「引擎的持倉」和「你的帳本」，每個幣給一條指令，並在下單前做風控。
- 帳本、停損、日誌在 `~/.freqai-ea/`（或 `$EA_HOME`）。

## 工具

| MCP 工具 | 等同的指令（在 `skills/freqai-ea-trading/` 內） | 用途 |
|---|---|---|
| `ea_guide` | `python3 desk/ea_desk.py guide` | 本手冊 |
| `ea_status` | `python3 desk/ea_desk.py status` | 模式、引擎、部位（含方向與槓桿）、損益、守衛 |
| `ea_signals` | `python3 desk/ea_desk.py signals` | 每個幣的指令（每輪一次） |
| `ea_risk_check` | `python3 desk/ea_desk.py check --coin eth --price P --qty Q` | 開倉前風控 |
| `ea_record` | `python3 desk/ea_desk.py record --event OPEN --coin eth --position-id … --side short --leverage 2 --qty … --price … --stop-price …` | 記錄 OPEN / CLOSE / STOP / SKIP |
| `ea_halt` | `python3 desk/ea_desk.py halt --reason "…"` | 緊急停止新進場 |

## 每一輪（建議每 5–15 分鐘，至少每小時一次）

1. 呼叫 `ea_signals`。看 `ea_mode`（PAPER / LIVE / HALT）和 `todo`。
2. 依每個幣的 `action` 處理（下表）。`todo` 是空的就不用動作。
3. 有任何成交、停損移動、`ENGINE_DOWN`、`ERROR` 時，用一兩句話告訴使用者（格式見最後）。

| action | 你要做的事 |
|---|---|
| `OPEN` | **LIVE、合約（perp）**：打開該幣 USDT 永續合約頁 → 確認**逐倉**、槓桿設為指令的 `leverage` → 讀目前價格 → `ea_risk_check(coin, price, qty)` → `approved=true` 才市價開倉：`side=long` 開多、`side=short` 開空，數量 `qty`（或 `sizing.qty`，向下取到交易所允許的位數；不能更多）→ 立刻設定止損單（只減倉 / reduce-only），觸發價 = `stop_price` → `ea_record(OPEN, coin, position_id, side, leverage, qty=實際成交數量, price=成交均價, fee_usdt, stop_price)`。**LIVE、現貨（spot）**：在現貨市價買入 `qty`，立刻掛停損單，其餘同上。`approved=false` → 不開倉，`ea_record(SKIP, reason)`。**PAPER**：不下單，直接用 `reference_price` 和 `qty` 記 OPEN。 |
| `HOLD` | LIVE：確認交易所止損單還在、觸發價等於 `position.stop_price`、部位方向與數量正確。不見了就補掛。 |
| `MOVE_STOP` | LIVE：把止損單改到 `stop_price`（多單只會往上、空單只會往下）→ `ea_record(STOP, coin, stop_price)`。PAPER：直接記 STOP。 |
| `CLOSE` | LIVE：取消止損單 → 市價平倉全部（合約用「平倉」/ reduce-only；現貨賣出）→ `ea_record(CLOSE, coin, qty, price=成交均價, fee_usdt, funding_usdt=這筆部位期間的資金費合計（收到為正、付出為負，可從交易所資金費紀錄讀；讀不到就省略）, reason=exit_reason)`。PAPER：用 `reference_price` 記 CLOSE。 |
| `CLOSE_NOW` | 價格已穿過停損（多單跌破、空單漲破）。LIVE：到交易所看止損單是否已成交；已成交就用成交價記 CLOSE，沒成交就市價平倉全部再記 CLOSE（reason=stop）。PAPER：用 `position.stop_price` 記 CLOSE。 |
| `MISSED` | 不追價、不動作（這筆錯過了，等下一筆）。 |
| `WAIT` / `SHADOW` | 不動作。SHADOW 是未通過驗證的 EA，只看不做。 |
| `BLOCKED` | 不開倉。原因在 `why`；若是 HALT、守衛 HALT、累計虧損上限，告訴使用者。 |
| `ENGINE_DOWN` | 不開新倉、不移停損；既有部位的交易所止損單保留。告訴使用者引擎有問題（請他執行 `python3 desk/ea_engine.py status`）。 |
| `ERROR` | 不動作，把 `why` 原文告訴使用者。 |

## 下單細節

**合約（ETH、SOL）**
- **只用逐倉（isolated），槓桿只用指令給的 `leverage`（1–3 倍）**。槓桿只決定佔用的保證金，不放大部位：數量永遠是 `qty`。指令的槓桿已經讓清算價距離至少是停損距離的 2 倍；你不可以提高槓桿或改成全倉（cross）。
- 合約帳戶要有足夠 USDT 保證金（`margin_usdt`）。不夠就不開倉、告訴使用者——**不可以自己轉帳**。
- 止損單用「只減倉」（reduce-only）並設定觸發價 = `stop_price`；以標記價格或最新價觸發都可以。多單止損在價格下方、空單止損在價格上方。
- 資金費是合約的成本（多頭市場多單通常要付）。平倉時把這筆部位的資金費合計記在 `funding_usdt`。
- 永續合約名稱以交易所為準（例如 ETHUSDT 永續）；部分交易所數量以「張」計，要換算成幣的數量。

**現貨（BTC）**
- 只做多、不用槓桿、不借幣。停損用交易所的停損 / 條件單 / Stop-Limit（觸發價 = `stop_price`，限價可設低 0.5%–1%）。交易所沒有現貨停損單時，告訴使用者，並把每輪間隔縮短到 5 分鐘：`CLOSE_NOW` 會在價格跌破停損時提醒你賣出。

**共同**
- 停損距離是 EA 的設計：多單通常 15–30%、空單約 3 倍日波動（約 8–15%）。不要自己收緊或放寬。
- 記錄的是**實際發生的事**：實際成交數量、均價、手續費、資金費。
- 一個幣同時只有一筆 EA 部位；不要加碼、不要分批、不要提前停利、不要反手。

## PAPER 與 LIVE

- 預設 **PAPER**：照指令記錄「若下單」的結果，不碰交易所。用來確認整套流程（建議至少 30 天）。
- **LIVE** 只有使用者能開：在終端機執行 `python3 desk/ea_desk.py live on` 並輸入確認字句。你不能開，也不能請使用者把確認字句告訴你。
- **HALT**：任何人（包括你）都能用 `ea_halt` 停止新進場；只有使用者能用 `python3 desk/ea_desk.py resume` 解除。

## 什麼時候要 `ea_halt`

- 帳本和交易所對不上（交易所有部位但帳本沒有、方向或數量不同，或反過來）。
- 交易所頁面、價格、餘額、保證金、清算價看起來不正常，或你不確定該怎麼做。
- 使用者要求停止。

HALT 不會平倉；既有部位繼續照 `CLOSE` / `CLOSE_NOW` / `MOVE_STOP` 管理。

## 絕對不可以

1. 向使用者要交易所 API 金鑰、密碼、2FA 碼，或把它們寫進任何檔案或對話。
2. 提幣、轉帳、借貸；使用全倉、提高槓桿、開出比 `qty` 更大的部位，或在 BTC 現貨以外的地方交易 BTC EA。
3. 自己開實盤、解除 HALT、修改 `desk/config.json` 或 `~/.freqai-ea/config.json`、修改 EA 參數或策略程式。
4. 在 `ea_risk_check` 沒通過時開倉。
5. 把停損往不利方向移（多單往下、空單往上），或取消停損卻不平倉。
6. 不記錄成交，或記錄沒有發生的成交。
7. 隱瞞虧損或錯誤。

## 回報格式（繁體中文，一兩句）

- 合約開倉：「ETH 合約 EA 開空：0.85 ETH @ 3,000（逐倉 2x），止損 3,240（PAPER）。」
- 現貨開倉：「BTC EA 進場：買入 0.0040 BTC @ 100,500，停損 80,000。」
- 停損移動：「SOL 合約空單止損下移到 142.3。」
- 出場：「ETH 合約空單平倉（移動停損）：@ 2,620，損益 +310.5 USDT（含資金費 +2.1）。」
- 問題：「SOL EA 引擎沒有回應，已暫停新進場；請執行 `python3 desk/ea_engine.py status`。」

## 給使用者：安裝與上線檢查表

安裝（Linux / macOS / WSL，需要 Python 3.10+）：

```bash
git clone https://github.com/lchouprivate501-netizen/Trader-Bot_Crypto
cd Trader-Bot_Crypto
bash skills/freqai-ea-trading/scripts/setup_env.sh        # Freqtrade + FreqAI venv（約 1–2 GB）
python3 skills/freqai-ea-trading/desk/ea_engine.py start   # 背景啟動三個無金鑰引擎（ETH、SOL 合約；BTC 現貨）+ 守衛
python3 skills/freqai-ea-trading/desk/ea_engine.py status  # 等 usable=true（第一次訓練要幾分鐘）
python3 skills/freqai-ea-trading/desk/console.py --open    # AI 交易辦公室：看引擎、交易台、AI 與部位在做什麼
```

設定每個 EA 的資金（只寫要改的欄位）：`~/.freqai-ea/config.json`，例如 `{"coins": {"eth": {"capital_usdt": 500}, "sol": {"capital_usdt": 300}}}`。EA 的設計是停損一次約虧該 EA 資金的 10%。回測最大回撤：ETH 合約約 27%、SOL 合約 25–36%（連續回測 35.8%，移轉測試平均 36%）、BTC 現貨約 31%。

連接 AI：見 `references/ai-agents.md`（Claude Code 外掛、Claude Desktop、claude.ai、Grok、其他支援 MCP 或能執行指令的 AI）。

開 LIVE 之前：

- [ ] PAPER ≥ 30 天，AI 每輪都有照指令記錄；`ea_status` 的部位、方向和引擎一致。
- [ ] 理解這是趨勢跟隨：合約 EA 每年約 10–12 筆（多空合計）、勝率 35–55%；牛市跑輸持有、熊市靠空單；資金費是長期成本。
- [ ] 能承受回測最大回撤 ×1.5（ETH 約 40%、SOL 約 54%、BTC 約 47%）的 EA 資金虧損。
- [ ] 合約帳戶有足夠 USDT、設定為逐倉；AI 能在你的交易所設定合約止損單（只減倉）。BTC 現貨帳戶有 USDT。
- [ ] 知道怎麼停：叫 AI `ea_halt`，或自己 `python3 desk/ea_desk.py halt`；要全部出場就在交易所手動平倉並告訴 AI 記錄 CLOSE。
