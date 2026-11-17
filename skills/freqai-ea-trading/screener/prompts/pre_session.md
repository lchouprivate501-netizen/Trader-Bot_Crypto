<!-- prompt_version: pre-session v1.0 (2026-11-17) -->

# 盤前更新（排程提示詞）

建議排程：每天台北 19:25（UTC 11:25），在歷史上最少盤整的 UTC 12–16（台北 20:00–24:00）開始前。
目的：只更新「早上之後發生的事」——新的避開理由、焦點的催化劑是否還成立、今晚的總經事件。**不重新排名、不寫前向驗證紀錄。**

## 0. 參數

| 參數 | 預設 | 說明 |
|---|---|---|
| `REPO` | 目前目錄 | Trader-Bot_Crypto 的路徑 |
| `RUN_ROOT` | `~/.intraday-screener/runs` | 和每日清單同一個 |
| `EXCHANGE` | 早上 `ai_report.json` 用的那一家 | 連不到依序 `bybit` → `okx` |
| `PERSIST` | `none` | `git`：開始前從 `screener-runs` 分支取回紀錄、結束後把今天的更新推回去 |

## 1. 角色與界線

和 `daily_watchlist.md` 第 1 節完全相同（研究助理、不下單、不給價位與槓桿、不要金鑰、不改設定與程式、不捏造、數字只從工具輸出取）。另外：

- **不要用 `--log`**：前向驗證每天只用最早的一次紀錄，盤前更新不能產生新的紀錄。
- **不要修改早上的 `ai_report.json`**（前向驗證讀它）；更新寫在另外的檔案。
- **不能因為「近4h」把觀察升為焦點**：驗證顯示近 4 小時盤勢不能預測下一個 4 小時。分級只能因為新聞改變。

## 2. 步驟

0. `PERSIST=git` 時：`bash skills/freqai-ea-trading/screener/persist_runs.sh pull "$RUN_ROOT"`。
1. 找今天的 `RUN_DIR`：`RUN_ROOT/<今天 UTC 日期>/`。讀 `ai_report.json` 的 `focus`、`watch`、`avoid`。
   - 找不到（早上的排程失敗）：在回覆說明，然後只做步驟 3 的總經部分，不產生清單。
2. 盤勢描述（含程式新聞層），對焦點 + 觀察前 10：
   ```bash
   python3 skills/freqai-ea-trading/screener/intraday_screener.py now <幣1> <幣2> ... --exchange "$EXCHANGE" --news
   ```
   記下每個幣的「近4h」與是否「沒通過篩選門檻」（例如今天被公告下架）。
3. 網路搜尋**早上那次之後**（大約 12 小時內）的新消息：
   - 每個焦點與避開的幣 1 次搜尋；觀察清單只查有程式新聞標記的。
   - 今晚台北 20:00 → 明早 08:00 的總經事件與確切時間。
   - 來源分級與確認規則同 `daily_watchlist.md` 步驟 4。
4. 調整分級（只因為新聞）：
   - 焦點 → 避開：出現任何「避開」條件（`daily_watchlist.md` 步驟 5）。
   - 焦點 → 觀察：催化劑被否認、撤回，或事件已經發生而且超過 24 小時。
   - 觀察 → 焦點：只有出現新的 confirmed 催化劑才可以，並且焦點總數仍 ≤ 5。
5. 輸出：
   - `RUN_DIR/pre_session.json`：`{"prompt_version", "generated_utc", "changes": [{"coin", "from", "to", "reason_zh", "sources": [...]}], "macro_tonight": [...], "now": {幣: 近4h 狀態}}`
   - `RUN_DIR/pre_session.md`：變動表、今晚總經（台北時間、落在哪個時段）、焦點與避開的最新清單、固定聲明。
   - `PERSIST=git` 時：`bash skills/freqai-ea-trading/screener/persist_runs.sh push "$RUN_ROOT" <今天 UTC 日期>`。
   - 最後回覆（10 行內）：

```
盤前更新 <台北日期 時間>
焦點（更新後）：<幣（催化劑）>…｜無
新增避開：<幣（原因）>…｜無
取消焦點：<幣（原因）>…｜無
今晚總經：<台北時間 事件>…｜無
近4h（描述，不是訊號）：<幣 狀態>…
提醒：台北 20:00–24:00 歷史最少盤整，但約 1/3 的 4 小時仍會盤整；新聞焦點未驗證；不是投資建議。
```

## 3. 自我檢查

- [ ] 沒有寫 `--log`、沒有改 `ai_report.json`。
- [ ] 每個分級變動都有新聞來源網址與時間，沒有任何變動是因為「近4h」。
- [ ] 沒有價位、槓桿、「會漲 / 會跌」。
