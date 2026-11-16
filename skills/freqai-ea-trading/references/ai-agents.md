# 在 Claude、Grok 或其他 AI 中使用 EA

這個專案是開源的（MIT），任何 AI 都可以下載使用。AI 透過兩種方式之一操作 EA 交易台：

- **MCP 工具**（建議）：`desk/mcp_server.py`，標準 stdio MCP，只用 Python 標準函式庫，不需要安裝套件。
- **指令列**：`python3 desk/ea_desk.py signals|check|record|status|halt`，輸出 JSON。給能執行終端機指令、但不支援 MCP 的 AI。

AI 的作業手冊是 [`AGENTS.md`](../AGENTS.md)（MCP 工具 `ea_guide` 會回傳同一份內容）。

## 共同步驟（使用者在自己的電腦上做一次）

需要：Linux / macOS / Windows WSL、Python 3.10+、約 2 GB 磁碟、能連到 Binance（或 Bybit / Gate）公開行情。

```bash
git clone https://github.com/lchouprivate501-netizen/Trader-Bot_Crypto
cd Trader-Bot_Crypto
bash skills/freqai-ea-trading/scripts/setup_env.sh          # Freqtrade 2026.10 + FreqAI 的 venv
python3 skills/freqai-ea-trading/desk/ea_engine.py start     # 背景啟動 3 個無金鑰引擎 + 守衛
python3 skills/freqai-ea-trading/desk/ea_engine.py status    # 等每個引擎 usable=true
python3 skills/freqai-ea-trading/desk/test_desk.py           # （可選）交易台自我測試，51 項
```

- 引擎是 Freqtrade 的 dry-run，不需要也不接受交易所金鑰；它只算出 EA 該做什麼。
- 每個 EA 的資金預設 1000 USDT，在 `~/.freqai-ea/config.json` 修改，例如 `{"coins": {"btc": {"capital_usdt": 500}}}`。EA 的設計是停損一次約虧該資金的 10%。
- 預設 PAPER（只記錄不下單）。實盤只有使用者能開：`python3 skills/freqai-ea-trading/desk/ea_desk.py live on`。
- 電腦重開後要再執行一次 `ea_engine.py start`。

## Claude Code

外掛市集（會一起安裝 EA skill、`ea-maintainer` 維護 Agent 與 `freqai-ea-desk` MCP 伺服器）：

```
/plugin marketplace add lchouprivate501-netizen/Trader-Bot_Crypto
/plugin install freqai-crypto-trading@trader-bot-crypto
```

或只加 MCP 伺服器：

```bash
claude mcp add freqai-ea-desk -- python3 /絕對路徑/Trader-Bot_Crypto/skills/freqai-ea-trading/desk/mcp_server.py
```

在本倉庫目錄內開啟 Claude Code 時，`.claude/skills/` 與 `.claude/agents/` 會自動載入 skill 與維護 Agent。

## Claude Desktop

編輯 `claude_desktop_config.json`（設定 → 開發者 → 編輯設定），加入：

```json
{
  "mcpServers": {
    "freqai-ea-desk": {
      "command": "python3",
      "args": ["/絕對路徑/Trader-Bot_Crypto/skills/freqai-ea-trading/desk/mcp_server.py"]
    }
  }
}
```

重新啟動 Claude Desktop 後，對話中說「照 EA 交易台每輪流程執行一次」即可。

## claude.ai（網頁 / App）

可以把 `skills/freqai-ea-trading/` 壓縮成 zip，在 Skills 設定上傳，讓 Claude 了解 EA 的設計、驗證與作業手冊。但網頁版連不到你電腦上的引擎，**要讓 Claude 實際執行交易，請用 Claude Code 或 Claude Desktop**。

## Grok

Grok 用戶端若支援本機（stdio）MCP 連接器，新增一個連接器：

| 欄位 | 值 |
|---|---|
| 名稱 | `freqai-ea-desk` |
| command | `python3`（或 Python 3.10+ 的絕對路徑） |
| args | `/絕對路徑/Trader-Bot_Crypto/skills/freqai-ea-trading/desk/mcp_server.py` |
| env | 可省略；要把資料放別處時設 `EA_HOME=/路徑` |

然後給 Grok 這段指示（放在系統提示或第一則訊息）：

> 你是我的 EA 交易執行者。先呼叫 `ea_guide` 讀作業手冊並照做。每一輪呼叫 `ea_signals`，依每個幣的 action 在我的交易所現貨下單或記錄；買入前一定 `ea_risk_check`，成交後一定 `ea_record`。不要向我要 API 金鑰、不要提幣或轉帳、不能自己開實盤或解除 HALT。有成交或問題時用一兩句話回報我。

Grok 用戶端只支援遠端（HTTP）MCP 時：本專案目前只提供本機 stdio 版本；可以讓 Grok 執行 `python3 desk/ea_desk.py …` 指令（見下一節），或把 `AGENTS.md` 貼給它，由你代為執行指令。

## 其他 AI（ChatGPT / Codex、Gemini CLI、Cursor、Cline、Windsurf…）

- 支援 MCP 的用戶端：用上面 Claude Desktop 的同一段 JSON（大多數用戶端的 `mcpServers` 格式相同）。
- 能執行終端機指令的 AI：在 `skills/freqai-ea-trading/` 內執行

  ```bash
  python3 desk/ea_desk.py guide                       # 作業手冊
  python3 desk/ea_desk.py signals                     # 每輪：每個幣的指令
  python3 desk/ea_desk.py check --coin btc --price 100500
  python3 desk/ea_desk.py record --event OPEN --coin btc --position-id EA-BTC-7-2026111601 --qty 0.0039 --price 100500 --stop-price 80000
  python3 desk/ea_desk.py halt --reason "帳本對不上"
  ```

- 會自動讀取 `AGENTS.md` 的 AI（Codex、Cursor 等）：倉庫根目錄的 `AGENTS.md` 會把它們導到這份手冊。

## 讓 AI 定時執行

EA 的進場判斷每小時一次、停損每分鐘更新，AI 至少每小時、最好每 5–15 分鐘跑一輪。依你的 AI 用戶端：

- Claude Code：`/loop 10m 照 skills/freqai-ea-trading/AGENTS.md 執行一輪 EA 交易台`。
- 有排程功能的用戶端：每 10–15 分鐘送出「執行一輪 EA 交易台」。
- 沒有排程時，交易所上的停損單仍會保護部位；但出場（趨勢轉弱）與停損上移要等 AI 下一次執行。

## 安全設計（為什麼可以放心交給 AI）

| 風險 | 設計 |
|---|---|
| 金鑰外洩 | 引擎不需要金鑰（強制 dry-run、清空金鑰欄位、移除 `FREQTRADE__*` 環境變數）；交易台與 MCP 伺服器不讀金鑰。 |
| AI 自己開實盤 | `live on` 與 `resume` 需要互動式終端機與確認字句；MCP 沒有這兩個工具。 |
| 下單過大 | `ea_risk_check` 依 EA 的部位比例、單筆風險上限（資金 10%）、資金上限計算最大數量。 |
| 追高 | 價格超過引擎進場價 2% 不進場（`MISSED`）。 |
| 停損被往下移 | `ea_record STOP` 拒絕降低停損。 |
| 引擎壞掉 | 引擎連不上、停擺、不是 dry-run、策略不符 → `ENGINE_DOWN`，不開新倉。 |
| EA 失效 | EA 守衛依驗證過的正常範圍判定 HALT → 停止新進場；累計虧損達資金 35% → 停止新進場。 |
| 帳本與交易所不一致 | 每筆成交都要記；同一幣兩筆部位 → `ERROR`；AI 不確定時可 `ea_halt`。 |
