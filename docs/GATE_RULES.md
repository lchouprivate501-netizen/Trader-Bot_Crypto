# 閘門與技能原文的對照

| 閘門 | 來源 | 本策略作法 | 刻意差異 |
|---|---|---|---|
| regime | agiprolabs regime-detection | ADX<20 不進場；ADX>25 視為趨勢 | ADX 20–25 為 transitional，**允許**進場並記錄 `transitional_allowed`。技能並未把此帶寫成禁交易，只在「象限轉換」時建議減倉。 |
| volatility | volatility-modeling | 用 5/25/75/95 分位與 5/10/20/60/120 日錐；主閘門看 5 日實現波動。低於第 25 分位（壓縮）不進場；高於第 75 分位減倉，第 95 分位再減。日波動以磁碟上的 1d 歷史（加上 informative 1d／已收盤的 15m 日線）計算，只取「已收盤的前一日」再填到 15m（避免當日收盤前視）。live／dry-run 不依賴 15m 的 1200 根暖機窗 | **沒有**自創第 97 分位。 |
| pressure | market-microstructure | 收盤位置作為主動買量代理：做多 >60%、做空 <40%；成交量 >3 倍近 96 根均量視為異常並阻擋該根進場 | 技能原文是 Solana DEX 真實買賣成交，不是 CEX K 線代理。3 倍量能在技能中是異常指標，這裡用於入場阻擋並在日誌標明。 |
| structure | 概念取自 BOS/CHoCH | 右側確認擺盪後才用，多單需漲破前高或更高低點 | **不安裝** joshyattridge/smartmoneyconcepts（前視偏差）。 |
| btc_trend | 本策略規則 | BTC 1h 收盤相對 EMA50 且均線斜率：明確反向才擋 | 中性（0）放行。 |
| discipline | pre-trade-discipline-gate | 同一交易對虧損平倉後 24 小時內不進場（`--revenge-window-hours` 預設 24） | 技能還有書面計畫／停損檢查，那些是人工清單，不在自動訊號路徑強制。 |
| risk_limits | risk-management 保守檔 | 日虧 -3% 停開；回撤 15% 停；7 連虧暫停 24h；3 連虧半倉；5 連虧最小倉（0.25x）；回撤 5–10% 減 25–50%；10–15% 最小倉；單一幣 10%；總曝險 ≤80% | 與技能保守檔一致。單一幣用藍籌 10%，不是板塊 30%。 |
| event_risk／circuit_breaker／crypto_regime | tradermonty 腳本 + 狀態檔 | 預設關閉。開啟後讀 `user_data/gates/`，缺檔／過期／格式錯誤則 fail-closed | crypto_regime 的 RISK_OFF 不開多、RISK_ON 不開空是本系統政策；技能聲明自己不做交易授權。event_risk 的公布前 30／後 60 分鐘是本系統政策。 |
| ml_filter | signal-classification + FreqAI | `MacdGatedML`，遠期報酬標籤，LightGBM。門檻預設 0.65，**必須**用樣本外 profit factor 再優化，禁止當成 0.5 | 預設關閉，本次驗證未訓練 FreqAI。 |
