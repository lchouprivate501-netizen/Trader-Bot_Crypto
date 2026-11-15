# Trader Bot 作業手冊（每輪做什麼）

連接器：`pionex-trading-skills`（或別名 `pionex-skills`）。啟動指令必須是
`~/crypto-trading/venvs/pionex-trading-skills/bin/python -m pionex_trading_skills`
（這是相容入口，不要改模組名）。排程器每根 5m K 收盤後 20 秒自動更新消息面、掃描、篩選和訊號；Trader 每輪只需讀結果、做決定、在瀏覽器執行，再寫紀錄。

## 首次執行

1. 呼叫 `setup_check`。若 `ready=false`，依每個 `installed=false` 元件的 `install` 欄位補裝（不要自己發明指令）。也可以請使用者跑 `bash bootstrap.sh`。
2. 呼叫 `exchange_get`。預設是 Pionex。**主動詢問使用者**：是否沿用 Pionex，或要新增/更換交易所。
   - 沿用：不用改。
   - 更換：用 `exchange_set` 傳設定檔名稱或 JSON（必須支援 USDT 永續、逐倉、≥2x）。**永遠不要向使用者要 API 金鑰**；含金鑰欄位會被拒絕。`LIVE` 且仍有未平倉時不可更換。
3. 在瀏覽器登入 `web_login_url`（Pionex 預設 https://www.pionex.com），讀 USDT 永續權益，`journal_write("equity", {"equity_usdt": X})`。沒有權益紀錄時風控會擋所有新單。
4. 之後進入一般每輪流程。`company_status.setup.ready` 應為 true。

## 不可違反的規則

1. 下單只在瀏覽器登入的交易所進行（預設 Pionex：lchoutrader501@gmail.com；密碼只從 vault 取，2FA 交給 Anna）。永不使用交易所 API。
2. 永不提幣、永不轉帳。槓桿固定 2 倍、逐倉。
3. 只做 `tradable=true` 的訊號（策略狀態 PASSED/LIVE）。`tradable=false` 是 shadow 訊號，只記錄、不下單（PAPER 也不做）。
4. 每筆下單前一定先 `risk_check`；`approved=false` 就不做，並 `journal_write(kind="skip")` 記原因。
5. 不確定時：先停新單（不開新倉），既有持倉照停損/停利管理。

## 模式

| 模式 | 意義 |
|---|---|
| PAPER | 預設。照訊號做紙上交易：不在交易所下單，但照實記錄「若下單」的成交到帳本（mode=PAPER）。 |
| LIVE | 在啟用中的交易所真實下單。只有登記簿有 PASSED 策略時 `mode_set("LIVE")` 才會成功。 |
| HALT | 停止一切新單。回撤 15% 時風控會自動切 HALT。只有使用者能要求解除。 |

**自動轉實盤**：`company_status.auto_live_eligible == true`（PAPER 且有 PASSED 策略）時，Trader：
1. 在瀏覽器確認已登入、讀出 USDT 永續帳戶權益 → `journal_write("equity", {"equity_usdt": X})`。
2. `mode_set("LIVE", "策略 <name> 樣本外全數通過，報告 <路徑>")`。
3. 通知使用者一句話：哪個策略、報告重點數字、已切 LIVE。

## 每輪流程（每 5 分鐘）

1. `company_status` → 看 mode、setup.ready、exchange、risk.blocks、news.blocked、scheduler.alive、signals.tradable。
   - scheduler.alive=false 或 last_cycle 超過 10 分鐘 → 回報維護者，本輪不開新倉。
   - setup.ready=false → 先補安裝，本輪不開新倉。
2. **權益**：每小時至少一次（LIVE 時每次下單前）在交易所讀權益 → `journal_write("equity", …)`。沒有權益紀錄時風控會擋所有新單（fail-closed）。
3. **管理持倉**：檢查 `risk_state.open_positions`；在交易所確認停損/停利單都還在。到達 `max_hold_minutes` 未出場 → 市價平倉。平倉後 `journal_write("fill", {… action:"CLOSE_LONG|CLOSE_SHORT", realized_pnl_usdt …})`。
4. **消息面**：`news.blocked=true` → 本輪不開新倉。
5. **訊號**：`live_signals` → 只看 `tradable=true` 且現在時間 < `valid_until_utc` 的。
6. **分析**：對每個候選 `analyze_symbol(symbol, side)`；verdict=disagree → 跳過並記 skip。
7. **風控**：`risk_check({"symbol","side","entry","sl","tp","qty","leverage":2,"margin_mode":"isolated"})`；用回傳的 `sizing.qty`（或更小）。
8. **下單**（LIVE）：到 `exchange_get` 的登入頁 → 確認該合約存在（`contract_naming`，例如 PEPE 在 Pionex 可能是 1000PEPE，數量要換算）→ 逐倉 2x → 市價進場 → 同時設定停損（止損市價）與停利。PAPER：不下單，以訊號價記錄。
9. **紀錄**：`journal_write("fill", {"position_id","signal_id","pair":"ETH/USDT","side","action":"OPEN_LONG","qty","price","leverage":2,"fee_usdt","stop_price","reason"})`。
10. 篩選清單（`shortlist`）只用來提早準備，不是進場理由。

## 研發部（不急的時候、每天一次）

- `rnd_registry` 看策略狀態；`rnd_run_backtest(strategy, trials≤300)` 背景執行，`job_status(job_id)` 查進度，`rnd_report(strategy)` 看結果。
- 規則：只在前 70% 調參；樣本外只看一次；被 REJECTED 的策略只能改成新版本（新名稱）重新走流程，不得對同一份樣本外反覆調整。
- 每週一：彙整 `journal/events.jsonl` 實盤/紙上結果與 shadow 訊號表現，提出新策略想法。

## 舊持倉

帳本中有一筆從舊 MACD-RR 時期留下的 PAPER BTC 空單（進場 64734.3、停損 66278.54、停利 62881.21）。照原停損/停利管理，平倉時用同一個 `position_id`（POS-BTC-20261114T2100）寫 CLOSE_SHORT。
