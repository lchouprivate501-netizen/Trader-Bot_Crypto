# EA 自動交易部署

> 驗證結果：BTCTrendEA、SOLMomentumEA 通過；**ETHRiskOnEA 未通過（交易筆數不足）**，只建議 dry-run 累積紀錄，不要直接實盤。

## 1. 準備

- 一台 24 小時開機、能連到交易所 API 的機器（VPS 或家用主機），Docker + Docker Compose。
- 交易所：設定檔為 Binance 現貨。換成其他 Freqtrade 支援的現貨交易所（OKX、Bybit、Kraken…）只改 `exchange.name` 與交易對；Pionex 不在 Freqtrade 支援名單。
- API 金鑰：只開「現貨交易」，**關閉提幣**，綁 IP 白名單。金鑰只寫在 `deploy/ea.env`（已在 `.gitignore`），不要寫進設定檔或 commit。
- 資金：每個 EA 一個子帳戶最單純；共用帳戶時每個服務設 `FREQTRADE__AVAILABLE_CAPITAL`，否則三個 EA 會互搶同一筆餘額。
- 最小金額：單筆部位約為權益的 15%–95%（依波動而定），Binance 現貨最小下單約 5 USDT；建議每個 EA 至少 300 USDT。

## 2. 啟動（預設 dry-run）

```bash
cd skills/freqai-ea-trading
cp deploy/ea.env.example deploy/ea.env        # 填入金鑰；保持 FREQTRADE__DRY_RUN=true
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f btc-ea
```

- 第一次啟動 FreqAI 會下載約 180 天資料並訓練模型（幾分鐘），之後每 24 小時重訓；模型超過 48 小時未更新就不再發出進場訊號。
- 每根 1 小時 K 線收盤後評估；進場後立刻在交易所掛停損單（`stoploss_on_exchange`），每 60 秒依吊燈停損上移。機器斷線時交易所上的停損仍有效。
- 不使用 Docker 時：`freqtrade trade -c user_data/configs/config_btc_ea.json --strategy-path user_data/strategies --freqaimodel-path user_data/freqaimodels`（金鑰用 `FREQTRADE__EXCHANGE__KEY/SECRET` 環境變數）。

## 3. 轉實盤檢查表

全部完成才把 `FREQTRADE__DRY_RUN=false`：

- [ ] dry-run ≥ 30 天；這段期間的進出場與同期回測（`ea_lab.py backtest --timerange <同期>`）一致。
- [ ] 理解這是趨勢跟隨：每年約 4–5 筆、勝率 30–50%、大部分時間空手；牛市會跑輸買入持有。
- [ ] 能承受回測最大回撤 ×1.5（BTC 約 45%、SOL 約 40% 的權益回撤）。
- [ ] 金鑰無提幣權限、IP 白名單、帳戶 2FA。
- [ ] 知道怎麼停：Telegram `/stopentry`（不再開新倉，既有部位照停損管理）、`/forceexit all`（全部平倉）、`docker compose down`（停程式；交易所停損單仍在）。

## 4. 監控

| 每週檢查 | 動作 |
|---|---|
| 容器在跑、FreqAI 模型日期在 48 小時內 | 否則查 `logs/<coin>-ea.log` |
| 交易所上有對應持倉的停損單 | 沒有 → 手動補，查日誌 |
| 權益回撤超過回測最大回撤 | `/stopentry`，回到研發期重新檢查 |
| FreqAI 預測力：`prediction_quality.py` 的波動 IC 高於天真預測 | 連續兩個月更差 → 改 `ea_params.ai_vol=false` 需視為新版本重新驗證 |

## 5. 已知限制

- 只做多、現貨：熊市只能空手，不會賺錢（V2 期間 BTC +0.7%、SOL +1.4%）。
- 交易次數少，統計信心有限；ETH 就是因此未通過驗證。
- 回測以 15 分鐘 K 線模擬停損，跳空或流動性差時實際成交可能更差。
