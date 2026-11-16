# 部署：模擬盤（dry-run）→ 實盤（live）與監控

> 回測數字不是承諾。任何策略在實盤前至少跑 **30 天 dry-run**，並與同期回測比對。

## 1. 一次性準備

```bash
bash skills/freqai-grid-trading/scripts/setup_env.sh        # freqtrade[freqai]==2026.10 + userdir + symlink
export FT_VENV=~/crypto-trading/venvs/freqai-grid FT_HOME=~/crypto-trading/freqai-grid/user_data
```

- 交易所：三個設定檔預設 `binance` **現貨**。換交易所只改 `exchange.name`、`pair_whitelist` 與 `include_corr_pairlist`（必須是 Freqtrade 官方支援的交易所，例如 OKX、Bybit、Kraken；Pionex 不在 Freqtrade 支援名單，本倉庫執行部的「瀏覽器下單」流程不適用於這三個機器人）。
- **API 金鑰不寫進 repo**。用環境變數覆寫：`FREQTRADE__EXCHANGE__KEY`、`FREQTRADE__EXCHANGE__SECRET`（OKX 另有 `FREQTRADE__EXCHANGE__PASSWORD`）。金鑰只開「交易」權限，**關閉提幣**，綁定 IP 白名單。
- 三個機器人各自獨立的帳戶或子帳戶最安全（每個設定檔 `max_open_trades=1`、`stake_amount=unlimited`，一輪最多用掉該帳戶 `alloc`=95% 的資金）。
- （不建議）改永續：`trading_mode: futures`、`margin_mode: isolated`、交易對改 `XXX/USDT:USDT`、帳戶單向持倉；槓桿維持 1x（`grid_params.leverage`）。開空要另外設 `grid_params.allow_short: true`——樣本內所有開空變體都比只做多差，見 `strategy-design.md`。

## 2. 模擬盤

```bash
$FT_VENV/bin/freqtrade trade -c skills/freqai-grid-trading/user_data/configs/config_btc.json \
  --userdir "$FT_HOME" --strategy-path skills/freqai-grid-trading/user_data/strategies \
  --freqaimodel-path skills/freqai-grid-trading/user_data/freqaimodels \
  --db-url sqlite:///$FT_HOME/btc-dryrun.sqlite
```

- 第一次啟動 FreqAI 會先下載資料並訓練（`train_period_days=180`），之後每 `live_retrain_hours=24` 小時重訓；`expiration_hours=48` 內沒有新模型就停止給訊號。
- 網格狀態存在 `trade.custom_data["grid"]`，重啟不會遺失。
- 建議開 `api_server`（FreqUI）或 Telegram 監看；`jwt_secret_key`、密碼一樣只用環境變數提供。

## 3. 轉實盤檢查表

全部打勾才把 `dry_run` 改成 `false`：

- [ ] dry-run ≥ 30 天，網格成交次數、每格毛利、session 出場原因與同期回測（`backtest.sh <coin> <同期>`）同一量級。
- [ ] `grid_report.py` 的盯市最大回撤在你能承受的範圍；把回測最大回撤 ×1.5 當作實盤預期。
- [ ] 最小下單金額：每格 = 帳戶 × 95% × (1 − 核心比例) ÷ 格數，約為帳戶的 BTC 3.2%、ETH 5.7%、SOL 11%。每格要高於交易所最小下單額（以交易所公告為準；Binance 現貨目前多為 5 USDT 名目），並留餘裕給精度捨入——帳戶至少約 BTC 300、ETH 200、SOL 100 USDT。
- [ ] 金鑰無提幣權限、IP 白名單、帳戶 2FA。
- [ ] 知道怎麼緊急停止：`freqtrade` 的 `/stopentry`（停止開新輪）、`/forceexit all`（全部平倉）、或直接停程式後在交易所手動平倉。

## 4. 例行監控（每週）

| 檢查 | 怎麼看 | 動作 |
|---|---|---|
| 模型還有預測力嗎 | 用最新資料重跑回測後 `prediction_quality.py`：波動 IC 應 > 天真預測 IC | 連續 2 個月輸給天真預測 → 停新輪，回到研發 |
| 網格是否正常來回 | FreqUI / DB：`grid_sell` 次數、每格毛利 | 長時間 0 次成交 → 檢查最小下單量、價格精度 |
| 回撤 | 帳戶權益峰值回落 | 超過回測最大回撤 → `/stopentry`，檢查原因 |
| 核心倉與網格的貢獻 | `grid_report.py` 的 grid buys/sells 與 session 出場原因 | 只靠核心倉賺錢、網格長期虧 → 檢查格距（`step_mult`）與手續費等級 |

## 5. 已知限制

- Freqtrade 一筆交易同時只能有一張掛單，所以只掛「最近的一張」網格單（逾時 10 分鐘重掛）；行情急跳時可能錯過一格，回測已用同樣的機制模擬。
- `grid_break` 之後的冷卻時間存在記憶體，**程式重啟會清掉冷卻**（網格帳本本身存在資料庫，不受影響）。重啟後若不想立刻開新輪，先 `/stopentry`。
- 網格帳本每次都會與實際持倉對帳（現貨手續費以幣扣、部分成交後取消），差額先算進核心倉。
- 回測的方向傾向（FreqAI 漂移）在樣本外 IC ≈ 0；它是三個策略最大的不確定性。

## 6. 與本倉庫其他部分的關係

本 skill 是獨立的 Freqtrade 專案（`skills/freqai-grid-trading/`），不使用 MCP 伺服器、不經過執行部的瀏覽器下單流程，也不受 `company/risk_caps.json` 的程式約束（那些上限是給 Trader 的人工下單流程）。若要讓 Trader 使用，建議沿用同樣精神：只跑通過樣本外檢驗的版本、1x 逐倉、永不提幣。
