# EA 自動交易部署

> 主要策略（依驗證結果）：**ETH、SOL 用合約 EA**（`ETHFuturesEA`、`SOLFuturesEA`，USDT 永續、逐倉、多空，見 [`futures-validation-results.md`](futures-validation-results.md)）；**BTC 用現貨 EA**（`BTCTrendEA`，只做多，見 [`validation-results.md`](validation-results.md)）。`BTCFuturesEA` 與現貨的 `ETHRiskOnEA` 未通過驗證，只建議 dry-run 累積紀錄；`SOLMomentumEA`（現貨）通過驗證，可作為不想用合約時的替代。

## 兩種執行方式

| | A. AI 交易台（`desk/`） | B. Freqtrade 直接交易（`deploy/`） |
|---|---|---|
| 誰下單 | 你的 AI（Claude、Grok…）照指令在交易所下單 | Freqtrade 用 API 金鑰自動下單 |
| 交易所 | ETH、SOL：有 USDT 永續（逐倉）與止損單的交易所；BTC：有現貨與停損單的交易所。包括 Freqtrade 不支援的，例如 Pionex | Freqtrade 支援的交易所 |
| 金鑰 | 不需要 | 需要（只開現貨與合約交易、關提幣） |
| 反應速度 | 取決於 AI 多久跑一輪（建議 5–15 分鐘；止損單一直在交易所上） | 即時 |
| 說明 | [`AGENTS.md`](../AGENTS.md)、[`ai-agents.md`](ai-agents.md) | 本文以下各節 |

兩種方式用同一份凍結參數的 EA；A 的引擎就是 B 的 dry-run 加上本機 REST API。不要同時用 A 和 B 交易同一個帳戶。

## 1. 準備

- 一台 24 小時開機、能連到交易所 API 的機器（VPS 或家用主機），Docker + Docker Compose。
- 交易所：設定檔為 Binance（ETH、SOL：USDT-M 永續；BTC：現貨）。換成其他 Freqtrade 支援的交易所（Bybit、Gate…）只改 `exchange.name` 與交易對。OKX、Kraken、Bitget 不能用：EA 啟動要 2400 根 1 小時 K 線，它們每次給的太少，Freqtrade 會拒絕啟動。Pionex 不在 Freqtrade 支援名單（要用 Pionex 請走 A. AI 交易台）。
- API 金鑰：只開「現貨交易」與「合約交易」，**關閉提幣**，綁 IP 白名單。金鑰只寫在 `deploy/ea.env`（已在 `.gitignore`），不要寫進設定檔或 commit。
- 合約 EA 用**逐倉**，槓桿由策略自己設定（1–3 倍，讓清算價距離 ≥ 2 倍停損距離），部位名目 ≤ 權益 95%。帳戶不要另外開全倉部位。
- 資金：每個 EA 一個子帳戶最單純；共用帳戶時每個服務設 `FREQTRADE__AVAILABLE_CAPITAL`，否則三個 EA 會互搶同一筆餘額。合約 EA 的保證金在合約帳戶、BTC 現貨 EA 的資金在現貨帳戶。
- 最小金額：單筆部位名目約為權益的 15%–95%（依波動而定）；建議每個 EA 至少 300 USDT。

## 2. 啟動（預設 dry-run）

```bash
cd skills/freqai-ea-trading
cp deploy/ea.env.example deploy/ea.env        # 填入金鑰；保持 FREQTRADE__DRY_RUN=true
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml logs -f eth-ea
```

- 第一次啟動 FreqAI 會下載約 180 天資料並訓練模型（幾分鐘），之後每 24 小時重訓；模型超過 48 小時未更新就不再發出進場訊號。
- 每根 1 小時 K 線收盤後評估；進場後立刻在交易所掛止損單（`stoploss_on_exchange`），每 60 秒依吊燈停損移動（多單往上、空單往下）。機器斷線時交易所上的止損仍有效。
- 不使用 Docker 時：`freqtrade trade -c user_data/configs/config_eth_perp.json --strategy-path user_data/strategies --freqaimodel-path user_data/freqaimodels`（BTC 用 `config_btc_ea.json`；金鑰用 `FREQTRADE__EXCHANGE__KEY/SECRET` 環境變數）。

## 3. 轉實盤檢查表

全部完成才把 `FREQTRADE__DRY_RUN=false`：

- [ ] dry-run ≥ 30 天；這段期間的進出場與同期回測（`ea_lab.py backtest --market perp --timerange <同期>`）一致。
- [ ] 理解這是趨勢跟隨：合約 EA 每年約 10–12 筆（多空合計）、勝率 35–55%；牛市會跑輸買入持有；多單要付資金費。
- [ ] 能承受回測最大回撤 ×1.5（ETH 合約約 40%、SOL 合約約 54%、BTC 現貨約 47% 的權益回撤）。
- [ ] 金鑰無提幣權限、IP 白名單、帳戶 2FA；合約帳戶為逐倉。
- [ ] 知道怎麼停：Telegram `/stopentry`（不再開新倉，既有部位照停損管理）、`/forceexit all`（全部平倉）、`docker compose down`（停程式；交易所止損單仍在）。

## 4. 監控（維護 Agent）

自動化的部分見 `maintenance/`：`ea-guard` 容器每 15 分鐘檢查機器人，HALT 時自動 `/stopentry`；GitHub Actions 每週一跑合約與現貨的前向健康檢查並在需要時開 issue；在 Claude Code 叫 `ea-maintainer` 子代理做例行檢查與診斷。合約 EA 出現任何一次強平都視為 ALERT（`maintenance-protocol.md` 第 8 節）。下表是人工每週也該看的項目。

| 每週檢查 | 動作 |
|---|---|
| 容器在跑、FreqAI 模型日期在 48 小時內 | 否則查 `logs/<coin>-ea.log` |
| 交易所上有對應持倉的止損單、合約為逐倉、槓桿與清算價合理 | 沒有 → 手動補，查日誌 |
| 權益回撤超過回測最大回撤 | `/stopentry`，回到研發期重新檢查 |
| 合約的資金費累計 | 長期牛市資金費偏高時，多單成本變大；記在維護紀錄 |
| FreqAI 預測力：`prediction_quality.py` 的波動 IC 高於天真預測 | 連續兩個月更差 → 改 `ea_params.ai_vol=false` 需視為新版本重新驗證 |

## 5. 已知限制

- 合約 EA 的回撤比現貨 EA 大（ETH 合約 26.6% vs 現貨 22.9%；SOL 合約連續回測 35.8%），換來熊市的空單獲利（V2：ETH +65.7%、SOL +7.4%，現貨 EA 為 +27.2%、+1.4%）。
- BTC 的空單在樣本外沒有貢獻（合約 EA 未通過），BTC 只能在熊市空手（V2 期間 BTC 現貨 EA +0.7%）。
- 資金費是合約多單的長期成本（ETH 2018–2021 約 −4,000 USDT / 10,000 起始資金）。
- 交易次數少，統計信心有限。回測以 15 分鐘 K 線模擬停損與清算，跳空或流動性差時實際成交可能更差。
