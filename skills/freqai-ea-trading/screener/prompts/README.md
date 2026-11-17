# 日內篩選器 × 新聞催化劑：排程 Prompt 架構

把「全網日內篩選器」和「新聞催化劑」交給 AI 每天自動跑：程式負責算得出來的部分（流動性、波動、盤整統計、公告與 RSS），AI 負責程式做不好的部分（讀新聞、確認來源、照規則分級、寫報告），每天的結果存成紀錄，每週拿實際走勢來驗證新聞到底有沒有用。

> 已驗證：篩選器挑得出流動性夠、會動的幣；**不能**預測哪個幣會盤整。新聞催化劑**還沒驗證**（歷史新聞拿不到，只能前向驗證）。
> 細節：[`references/intraday-screener.md`](../../references/intraday-screener.md)、協議：[`references/intraday-screener-protocol.md`](../../references/intraday-screener-protocol.md)。

## 檔案

| 檔案 | 用途 |
|---|---|
| [`daily_watchlist.md`](daily_watchlist.md) | **每日主排程**：篩選 → 新聞研究 → 分級 → 報告 → 紀錄 |
| [`pre_session.md`](pre_session.md) | 盤前更新：早上之後的新消息、今晚總經；不重排、不寫紀錄 |
| [`weekly_review.md`](weekly_review.md) | 每週檢討：前向驗證、資料管線健康度；只報告不改設定 |
| [`ai_report.schema.json`](ai_report.schema.json) | AI 分級報告的 JSON 格式（前向驗證讀 `focus`、`avoid`） |
| [`ai_report.example.json`](ai_report.example.json) | 符合格式的範例（內容虛構） |
| [`../persist_runs.sh`](../persist_runs.sh) | 雲端排程用：把紀錄存到 / 取回 `screener-runs` 分支 |

## 架構

```mermaid
flowchart TB
  subgraph 排程
    D["每日 台北 08:35<br/>daily_watchlist.md"]
    P["每日 台北 19:25<br/>pre_session.md"]
    W["每週一 台北 09:40<br/>weekly_review.md"]
  end
  subgraph 程式層（可重現、已測試）
    S["intraday_screener.py scan --news --log<br/>門檻・分數・近4h・時段"]
    N["news_catalyst.py<br/>Bybit / OKX 公告・媒體 RSS<br/>對應幣・分類・時間衰減"]
    R["research.py forward<br/>紀錄 vs 之後 24 小時<br/>（Binance 歷史資料庫）"]
  end
  subgraph AI 層（判斷、未驗證）
    A["網路搜尋：每個幣 48h 新聞<br/>總經行事曆・解鎖・交易所公告"]
    C["分級規則：焦點 / 觀察 / 避開<br/>來源分級 T1–T3・確認規則"]
  end
  subgraph 輸出
    L[("RUN_ROOT/UTC日期/<br/>scan-HHMMZ.json<br/>ai_report.json・report.md")]
    M["推播訊息（12 行內）"]
  end
  D --> S --> N
  S --> L
  D --> A --> C --> L
  C --> M
  P --> L
  P --> M
  W --> R
  L --> R --> M
```

### 分層與責任

| 層 | 誰做 | 狀態 | 做什麼 | 不做什麼 |
|---|---|---|---|---|
| L1 門檻與分數 | 程式 | **已驗證**（事前登記、保留期） | 流動性、波動、非加密排除、滑價、11 因子分數 | 不預測盤整 |
| L2 程式新聞 | 程式 | 未驗證（權重 0） | 公告 / RSS → 對應幣 → 分類 → 衰減分數；官方下架公告剔除 | 不改排名 |
| L3 AI 新聞研究 | AI | 未驗證 | 每個幣 48 小時的催化劑、來源分級、確認、總經時間 | 不推論漲跌、不給價位 |
| L4 分級 | AI（固定規則） | 未驗證（前向驗證中） | 焦點 ≤ 5、避開、觀察；寫出與程式標記的差異 | 不因「近4h」升級 |
| L5 紀錄與驗證 | 程式 | 驗證流程已事前登記 | 每天最早一次紀錄；60 天後判 HN1/HN2、HA1/HA2 | 不自動改權重 |

### 為什麼這樣設計

- **能驗證的交給程式、要判斷的交給 AI**：數字一律從篩選器 JSON 取，AI 不估算；AI 只做讀新聞與照規則分級。
- **已驗證與未驗證分開寫**：提示詞第 2 節列出驗證過的事實，報告只能照講；「焦點」明寫是未驗證的規則標記。
- **每天一次、固定時點的紀錄**：每日清單在台北 08:35（UTC 00:35）跑，和驗證研究的決策時點一致；前向驗證只取每天最早的紀錄，盤前更新不寫紀錄。
- **提示詞有版本號**：改提示詞就改版本，AI 組的前向驗證從改版日重新累計（協議規定），避免邊跑邊調。
- **失敗要說出來**：每個提示詞都有失敗處理表和自我檢查；交易所、新聞來源、網路搜尋的降級都寫進「資料狀態」。

## 排程時間

| 排程 | 台北（UTC+8） | UTC | cron（`CRON_TZ=Asia/Taipei`） | 為什麼是這個時間 |
|---|---|---|---|---|
| 每日清單 | 每天 08:35 | 00:35 | `35 8 * * *` | UTC 日收盤後，和研究的決策時點一致 |
| 盤前更新 | 每天 19:25 | 11:25 | `25 19 * * *` | 歷史上最少盤整的 UTC 12–16（台北 20–24）之前 |
| 每週檢討 | 週一 09:40 | 週一 01:40 | `40 9 * * 1` | 每日清單之後 |

分鐘數故意避開整點與半點（排程比較不擁擠）。只想要一個排程就只開「每日清單」；前向驗證只需要它。

## 怎麼排進自動化

### A. 本機排程（建議：交易所即時資料、紀錄留在本機）

需要：能執行指令與網路搜尋的 AI CLI（例如 Claude Code）、Python 3.10+、這個倉庫。

```bash
# crontab -e（系統時區設成 Asia/Taipei；或把時間換成 UTC）
35 8 * * *  cd ~/Trader-Bot_Crypto && claude -p "$(cat skills/freqai-ea-trading/screener/prompts/daily_watchlist.md)" >> ~/.intraday-screener/cron.log 2>&1
25 19 * * * cd ~/Trader-Bot_Crypto && claude -p "$(cat skills/freqai-ea-trading/screener/prompts/pre_session.md)"    >> ~/.intraday-screener/cron.log 2>&1
40 9 * * 1  cd ~/Trader-Bot_Crypto && claude -p "$(cat skills/freqai-ea-trading/screener/prompts/weekly_review.md)"  >> ~/.intraday-screener/cron.log 2>&1
```

非互動模式需要先允許它用到的工具（執行 `python3` / `bash`、讀寫檔案、網路搜尋），允許方式依你用的 CLI 版本而定（Claude Code 看 `claude --help` 與設定檔的 permissions）。不要允許它碰交易所金鑰或下單工具。

### B. Claude Code 雲端排程（scheduled task）

提示詞可以直接寫：

```
依 skills/freqai-ea-trading/screener/prompts/daily_watchlist.md 執行，參數 PERSIST=git。
```

要注意三件事：

1. **紀錄會消失**：每次排程是新的容器，所以用 `PERSIST=git`，紀錄存到倉庫的 `screener-runs` 分支（`persist_runs.sh` 在另一個 worktree 操作，不碰程式碼分支）。三個提示詞都會先取回、再推回。
2. **網路**：環境要允許 `fapi.binance.com`、`api.bybit.com`、`www.okx.com`、`data.binance.vision`、`www.coindesk.com`、`www.theblock.co`、`cointelegraph.com`、`decrypt.co`（用 CryptoPanic 再加 `cryptopanic.com`），以及網路搜尋。
3. **交易所可能擋雲端機房**：雲端機房多在美國，Binance / Bybit / OKX 都可能回 403 / 451，篩選器會一路退到 `archive`（資料到昨天收盤、沒有滑價與資金費），報告會寫出來。要即時資料請用本機排程。

### C. 其他 AI（Grok、ChatGPT agent、Gemini CLI…）

把提示詞全文貼進排程。需要兩種能力：執行 shell 指令（跑 Python）與網路搜尋。沒有網路搜尋時，提示詞會自動降級（只用程式新聞層、不給焦點）。

### 選用：CryptoPanic

設定環境變數 `CRYPTOPANIC_TOKEN` 後，程式新聞層會多一個聚合來源（有幣別標記）。金鑰只放在環境變數或排程平台的秘密設定，不要貼進提示詞、對話或檔案。這個來源的介面沒有在這個環境實際連線測試過。

## 紀錄目錄（`RUN_ROOT`，預設 `~/.intraday-screener/runs`）

```
RUN_ROOT/
├── 2026-11-18/
│   ├── scan-0035Z.json      ← 篩選器完整結果（含新聞），前向驗證用每天最早的這個
│   ├── ai_report.json       ← AI 分級（ai_report.schema.json），前向驗證讀 focus / avoid
│   ├── report.md            ← 每日報告
│   ├── pre_session.json     ← 盤前更新（不影響前向驗證）
│   └── pre_session.md
├── forward-2026-11-23.json  ← 每週前向驗證結果
├── weekly-2026-11-23.md
└── latest.html              ← 最近一次清單的網頁版
```

## 開始前檢查

- [ ] 本機先手動跑一次：`python3 skills/freqai-ea-trading/screener/intraday_screener.py scan --news`，確認交易所與至少一個新聞來源連得上。
- [ ] 手動貼一次 `daily_watchlist.md` 給 AI 跑，看 `report.md` 與 `ai_report.json` 是否符合格式（`ai_report.json` 可用任何 JSON Schema 驗證器對 `ai_report.schema.json` 檢查）。
- [ ] 確認排程平台的通知會顯示 AI 的最後回覆（推播模板就是給它用的）。
- [ ] 理解：60 天內前向驗證只會說「樣本不足」；在那之前「焦點」只是規則標記。
- [ ] 不要在驗證期間改提示詞或 `config.json`；真的要改，改版本號並接受重新累計。
