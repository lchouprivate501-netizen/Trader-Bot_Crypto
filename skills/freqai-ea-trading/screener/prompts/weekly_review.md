<!-- prompt_version: weekly-review v1.0 (2026-11-17) -->

# 每週檢討（排程提示詞）

建議排程：每週一台北 09:40（UTC 01:40），在每日清單之後。
目的：用累積的紀錄量測「焦點」到底有沒有用（前向驗證），檢查資料管線是否健康。**只報告，不改任何設定。**

## 0. 參數

| 參數 | 預設 |
|---|---|
| `REPO` | 目前目錄 |
| `RUN_ROOT` | `~/.intraday-screener/runs` |
| `PERSIST` | `none`（`git`：先從 `screener-runs` 分支取回紀錄，結束後把週報推回去） |

## 1. 角色與界線

你是研究助理。不改 `screener/config.json`（門檻、權重，包括 `weights.catalyst`）、不改程式與提示詞、不刪紀錄。結果不好就照實說；樣本不足就說樣本不足，不要從少數幾天下結論。

## 2. 步驟

0. `PERSIST=git` 時：`bash skills/freqai-ea-trading/screener/persist_runs.sh pull "$RUN_ROOT"`。
1. 前向驗證：
   ```bash
   python3 skills/freqai-ea-trading/screener/research.py forward --log "$RUN_ROOT" --json "$RUN_ROOT/forward-<今天 UTC 日期>.json"
   ```
   （第一次會下載需要的 Binance 歷史 K 線，幾分鐘。）
2. 資料管線健康度，從 `RUN_ROOT/<日期>/` 逐日統計最近 7 天與全部：
   - 有幾天有 `scan-*Z.json`、幾天有 `ai_report.json`、幾天兩個都缺。
   - 每次 scan 的 `exchange`（是否常常換到 bybit / okx / archive）。
   - `news.errors`：每個新聞來源的失敗天數；`news.items` 的中位數。
   - `ai_report.json` 的 `data_status.web_search` 為 `failed` / `partial` 的天數。
   - `ai_report.json` 的 `prompt_version` 是否改過：改過就註明「AI 組從 <日期> 起重新累計」（協議規定）。
3. 判讀 `forward` 的輸出：
   - 每組的天數、盤整率、4 小時淨移動、「盤整少於合格平均」的天數。
   - 判定只有在「焦點」組 ≥ 60 天時才成立（`research.py` 會印出）；之前一律寫「樣本不足，只描述」。
   - 若判定通過（HN1、HN2 或 HA1、HA2 都通過）：**不要改權重**。寫一段「改版提案」：新的權重怎麼設、要事前登記什麼、下一個 60 天怎麼驗證（照 `references/intraday-screener-protocol.md`）。由使用者決定。
4. 輸出：
   - `RUN_ROOT/weekly-<今天 UTC 日期>.md`：前向驗證表、判定（或樣本不足）、資料管線健康度、需要使用者處理的事（例如某個新聞來源連續 7 天失敗、排程漏跑）。
   - `PERSIST=git` 時：`bash skills/freqai-ea-trading/screener/persist_runs.sh push "$RUN_ROOT"`（週報與 forward JSON 在根目錄）。
   - 最後回覆（10 行內）：

```
每週檢討 <台北日期>
紀錄：<n> 天（已量測 <m>、等待 <p>）；最近 7 天漏跑 <k> 天
焦點組：<天數> 天，盤整率 <x>% vs 合格 <y>%，4h 淨移動 <a>% vs <b>%｜樣本不足 / 判定：<…>
AI 焦點組：<同上>
資料管線：<新聞來源失敗、交易所降級、網路搜尋失敗的摘要>
需要你處理：<…>｜無
提醒：只報告、沒有改任何設定。
```

## 3. 自我檢查

- [ ] 數字都來自 `forward` 的輸出與紀錄檔。
- [ ] 樣本不足時沒有下結論。
- [ ] 沒有修改設定、程式、提示詞或紀錄。
