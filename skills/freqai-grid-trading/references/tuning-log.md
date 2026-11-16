# 樣本內調參完整紀錄（多重檢定揭露）

全部只用樣本內 2021-06-01 → 2024-12-12（5 分鐘細節 K 線、FreqAI 快取預測、手續費現貨 0.10% / 永續 0.05%）。
每列是一組參數的完整樣本內回測；`calmar` = CAGR ÷ 盯市最大回撤。本檔共 195 組。選參原則：挑「高原」中心而不是單一最高格；
BTC 的選擇在相鄰格都穩定，ETH/SOL 的永續多空版本相鄰格大起大落 → 判定為雜訊並否決該結構。
試了這麼多組，樣本內最佳值一定偏樂觀；請以 `backtest-results.md` 的樣本外數字為準。

## BTC r1 — 結構與參數（v2 引擎，掛單成交）

固定：max_lots 12、break 3、enter_z −0.25、add_z −1、exit_z −0.5、vr_max 0.35

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"step_mult": 1.5, "core_frac": 0.6, "ema_band": 0.0, "trend_ema": 2400}` | 210.9 | 37.9 | 25.0 | 1.52 | 1.26 | 116/100 |
| `{"step_mult": 3.5, "core_frac": 0.6, "ema_band": 0.03, "trend_ema": 2400}` | 224.1 | 39.5 | 26.9 | 1.47 | 1.26 | 38/35 |
| `{"step_mult": 2.5, "core_frac": 0.6, "ema_band": 0.03, "trend_ema": 2400}` | 203.8 | 36.9 | 25.4 | 1.45 | 1.23 | 82/85 |
| `{"step_mult": 3.5, "core_frac": 0.6, "ema_band": 0.0, "trend_ema": 2400}` | 206.6 | 37.3 | 26.3 | 1.42 | 1.27 | 63/58 |
| `{"step_mult": 2.5, "core_frac": 0.6, "ema_band": 0.0, "trend_ema": 2400}` | 208.7 | 37.6 | 27.1 | 1.39 | 1.26 | 96/86 |
| `{"step_mult": 1.5, "core_frac": 0.6, "ema_band": 0.03, "trend_ema": 2400}` | 205.6 | 37.2 | 27.0 | 1.38 | 1.21 | 90/89 |
| `{"step_mult": 3.5, "core_frac": 0.3, "ema_band": 0.0, "trend_ema": 2400}` | 107.6 | 23.0 | 16.9 | 1.36 | 1.28 | 63/61 |
| `{"step_mult": 3.5, "core_frac": 0.3, "ema_band": 0.03, "trend_ema": 2400}` | 120.8 | 25.1 | 21.9 | 1.15 | 1.21 | 39/35 |
| `{"step_mult": 2.5, "core_frac": 0.3, "ema_band": 0.0, "trend_ema": 2400}` | 95.4 | 20.9 | 18.4 | 1.13 | 1.11 | 105/101 |
| `{"step_mult": 2.5, "core_frac": 0.3, "ema_band": 0.03, "trend_ema": 2400}` | 138.2 | 27.8 | 24.7 | 1.13 | 1.16 | 77/78 |
| `{"step_mult": 3.5, "core_frac": 0.3, "ema_band": 0.0, "trend_ema": 1200}` | 92.3 | 20.3 | 20.2 | 1.01 | 1.10 | 172/138 |
| `{"step_mult": 1.5, "core_frac": 0.3, "ema_band": 0.0, "trend_ema": 2400}` | 80.7 | 18.2 | 18.5 | 0.98 | 1.03 | 149/136 |
| `{"step_mult": 1.5, "core_frac": 0.3, "ema_band": 0.03, "trend_ema": 2400}` | 102.0 | 22.0 | 26.0 | 0.85 | 1.00 | 117/116 |
| `{"step_mult": 1.5, "core_frac": 0.6, "ema_band": 0.0, "trend_ema": 1200}` | 125.2 | 25.8 | 30.7 | 0.84 | 0.99 | 337/293 |
| `{"step_mult": 3.5, "core_frac": 0.6, "ema_band": 0.0, "trend_ema": 1200}` | 127.4 | 26.2 | 33.8 | 0.77 | 0.97 | 158/120 |
| `{"step_mult": 3.5, "core_frac": 0.6, "ema_band": 0.03, "trend_ema": 1200}` | 121.0 | 25.2 | 33.1 | 0.76 | 0.92 | 138/115 |
| `{"step_mult": 2.5, "core_frac": 0.6, "ema_band": 0.03, "trend_ema": 1200}` | 125.6 | 25.9 | 35.7 | 0.72 | 0.92 | 172/132 |
| `{"step_mult": 2.5, "core_frac": 0.3, "ema_band": 0.03, "trend_ema": 1200}` | 75.2 | 17.2 | 29.2 | 0.59 | 0.85 | 208/170 |
| `{"step_mult": 1.5, "core_frac": 0.6, "ema_band": 0.03, "trend_ema": 1200}` | 110.9 | 23.5 | 40.7 | 0.58 | 0.87 | 221/180 |
| `{"step_mult": 2.5, "core_frac": 0.6, "ema_band": 0.0, "trend_ema": 1200}` | 103.2 | 22.2 | 38.9 | 0.57 | 0.88 | 254/206 |
| `{"step_mult": 1.5, "core_frac": 0.3, "ema_band": 0.03, "trend_ema": 1200}` | 73.7 | 16.9 | 32.2 | 0.53 | 0.80 | 280/221 |
| `{"step_mult": 3.5, "core_frac": 0.3, "ema_band": 0.03, "trend_ema": 1200}` | 51.7 | 12.5 | 26.2 | 0.48 | 0.74 | 136/110 |
| `{"step_mult": 2.5, "core_frac": 0.3, "ema_band": 0.0, "trend_ema": 1200}` | 42.2 | 10.5 | 26.0 | 0.4 | 0.66 | 236/195 |
| `{"step_mult": 1.5, "core_frac": 0.3, "ema_band": 0.0, "trend_ema": 1200}` | 31.7 | 8.1 | 23.7 | 0.34 | 0.57 | 330/277 |

## BTC r2 — 趨勢 EMA × 波動目標

固定：core 0.6、step 2.5、ema_band 0.03

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"trend_ema": 2400, "vol_target": 0.0}` | 203.8 | 36.9 | 25.4 | 1.45 | 1.23 | 82/85 |
| `{"trend_ema": 2400, "vol_target": 0.03}` | 227.6 | 39.9 | 27.5 | 1.45 | 1.31 | 66/56 |
| `{"trend_ema": 1800, "vol_target": 0.0}` | 230.6 | 40.3 | 29.9 | 1.35 | 1.23 | 95/73 |
| `{"trend_ema": 2400, "vol_target": 0.02}` | 200.9 | 36.6 | 27.5 | 1.33 | 1.31 | 67/68 |
| `{"trend_ema": 3600, "vol_target": 0.03}` | 177.6 | 33.5 | 26.3 | 1.27 | 1.15 | 99/92 |
| `{"trend_ema": 1800, "vol_target": 0.03}` | 177.2 | 33.4 | 27.6 | 1.21 | 1.14 | 98/89 |
| `{"trend_ema": 1800, "vol_target": 0.02}` | 183.8 | 34.3 | 28.7 | 1.2 | 1.21 | 103/98 |
| `{"trend_ema": 3600, "vol_target": 0.02}` | 178.4 | 33.6 | 28.7 | 1.17 | 1.16 | 87/81 |
| `{"trend_ema": 3600, "vol_target": 0.0}` | 190.3 | 35.2 | 31.4 | 1.12 | 1.12 | 100/92 |

## BTC 消融 — FreqAI 波動 / 漂移開關（最終參數）

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"ai_vol": false, "ai_drift": true}` | 219.0 | 38.9 | 25.5 | 1.53 | 1.27 | 82/77 |
| `{"ai_vol": true, "ai_drift": true}` | 203.8 | 36.9 | 25.4 | 1.45 | 1.23 | 82/85 |
| `{"ai_vol": true, "ai_drift": false}` | 153.2 | 30.1 | 28.3 | 1.06 | 1.11 | 76/64 |
| `{"ai_vol": false, "ai_drift": false}` | 139.1 | 28.0 | 27.5 | 1.02 | 1.07 | 114/105 |

## ETH r1 — 永續多空網格（已否決）

ETH/USDT:USDT，fee 0.05%，含資金費率

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"step_mult": 1.5, "trend_ema": 2400, "ema_band": 0.0, "max_lots": 10}` | 69.2 | 16.0 | 26.0 | 0.62 | 0.70 | 854/744 |
| `{"step_mult": 2.5, "trend_ema": 1200, "ema_band": 0.03, "max_lots": 6}` | 52.8 | 12.7 | 37.7 | 0.34 | 0.61 | 857/746 |
| `{"step_mult": 1.5, "trend_ema": 1200, "ema_band": 0.03, "max_lots": 6}` | 45.8 | 11.3 | 36.9 | 0.31 | 0.53 | 1083/933 |
| `{"step_mult": 2.5, "trend_ema": 1200, "ema_band": 0.03, "max_lots": 10}` | 38.0 | 9.5 | 30.5 | 0.31 | 0.57 | 551/479 |
| `{"step_mult": 2.5, "trend_ema": 2400, "ema_band": 0.0, "max_lots": 6}` | 37.2 | 9.4 | 33.7 | 0.28 | 0.47 | 597/510 |
| `{"step_mult": 1.5, "trend_ema": 2400, "ema_band": 0.0, "max_lots": 6}` | 39.8 | 9.9 | 38.4 | 0.26 | 0.46 | 1653/1471 |
| `{"step_mult": 2.5, "trend_ema": 2400, "ema_band": 0.0, "max_lots": 10}` | 22.1 | 5.8 | 23.4 | 0.25 | 0.40 | 656/555 |
| `{"step_mult": 3.5, "trend_ema": 1200, "ema_band": 0.03, "max_lots": 6}` | 29.1 | 7.5 | 38.3 | 0.2 | 0.39 | 655/583 |
| `{"step_mult": 1.5, "trend_ema": 1200, "ema_band": 0.0, "max_lots": 6}` | 23.7 | 6.2 | 35.1 | 0.18 | 0.35 | 1551/1343 |
| `{"step_mult": 3.5, "trend_ema": 1200, "ema_band": 0.03, "max_lots": 10}` | 22.3 | 5.9 | 35.6 | 0.16 | 0.38 | 441/384 |
| `{"step_mult": 1.5, "trend_ema": 2400, "ema_band": 0.03, "max_lots": 6}` | 16.8 | 4.5 | 39.0 | 0.11 | 0.29 | 988/865 |
| `{"step_mult": 1.5, "trend_ema": 1200, "ema_band": 0.03, "max_lots": 10}` | 8.0 | 2.2 | 32.8 | 0.07 | 0.21 | 756/667 |
| `{"step_mult": 2.5, "trend_ema": 2400, "ema_band": 0.03, "max_lots": 10}` | 6.5 | 1.8 | 42.1 | 0.04 | 0.19 | 511/422 |
| `{"step_mult": 3.5, "trend_ema": 2400, "ema_band": 0.0, "max_lots": 6}` | 4.8 | 1.3 | 35.3 | 0.04 | 0.16 | 373/282 |
| `{"step_mult": 2.5, "trend_ema": 1200, "ema_band": 0.0, "max_lots": 6}` | 2.8 | 0.8 | 38.7 | 0.02 | 0.14 | 784/627 |
| `{"step_mult": 2.5, "trend_ema": 2400, "ema_band": 0.03, "max_lots": 6}` | 2.3 | 0.6 | 38.4 | 0.02 | 0.14 | 523/447 |
| `{"step_mult": 3.5, "trend_ema": 1200, "ema_band": 0.0, "max_lots": 10}` | -2.6 | -0.7 | 35.5 | -0.02 | 0.04 | 614/480 |
| `{"step_mult": 3.5, "trend_ema": 1200, "ema_band": 0.0, "max_lots": 6}` | -6.0 | -1.7 | 42.3 | -0.04 | 0.04 | 549/386 |
| `{"step_mult": 1.5, "trend_ema": 2400, "ema_band": 0.03, "max_lots": 10}` | -11.2 | -3.3 | 36.9 | -0.09 | -0.11 | 1008/911 |
| `{"step_mult": 3.5, "trend_ema": 2400, "ema_band": 0.03, "max_lots": 6}` | -16.3 | -4.9 | 50.0 | -0.1 | -0.09 | 359/285 |
| `{"step_mult": 3.5, "trend_ema": 2400, "ema_band": 0.03, "max_lots": 10}` | -16.9 | -5.1 | 49.9 | -0.1 | -0.12 | 478/401 |
| `{"step_mult": 1.5, "trend_ema": 1200, "ema_band": 0.0, "max_lots": 10}` | -18.0 | -5.5 | 45.1 | -0.12 | -0.19 | 1240/1077 |
| `{"step_mult": 2.5, "trend_ema": 1200, "ema_band": 0.0, "max_lots": 10}` | -21.2 | -6.5 | 41.9 | -0.16 | -0.29 | 943/797 |
| `{"step_mult": 3.5, "trend_ema": 2400, "ema_band": 0.0, "max_lots": 10}` | -15.6 | -4.7 | 28.0 | -0.17 | -0.15 | 436/362 |

## ETH r2 — 永續多空 + ETH/BTC 濾網 + 波動目標（已否決）

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"trend_ema": 1200, "rel_ema": 1200, "step_mult": 2.5, "vol_target": 0.03}` | 60.2 | 14.3 | 27.1 | 0.53 | 0.81 | 689/578 |
| `{"trend_ema": 1200, "rel_ema": 1200, "step_mult": 1.5, "vol_target": 0.03}` | 45.4 | 11.2 | 27.8 | 0.4 | 0.62 | 1316/1224 |
| `{"trend_ema": 1200, "rel_ema": 1200, "step_mult": 1.5, "vol_target": 0.0}` | 41.3 | 10.3 | 27.9 | 0.37 | 0.52 | 927/780 |
| `{"trend_ema": 1200, "rel_ema": 1200, "step_mult": 2.5, "vol_target": 0.0}` | 20.7 | 5.5 | 28.2 | 0.19 | 0.37 | 769/652 |
| `{"trend_ema": 2400, "rel_ema": 1200, "step_mult": 1.5, "vol_target": 0.0}` | 10.6 | 2.9 | 38.5 | 0.08 | 0.24 | 631/492 |
| `{"trend_ema": 1200, "rel_ema": 2400, "step_mult": 1.5, "vol_target": 0.03}` | -4.5 | -1.3 | 25.4 | -0.05 | 0.01 | 1237/1180 |
| `{"trend_ema": 2400, "rel_ema": 1200, "step_mult": 2.5, "vol_target": 0.0}` | -5.3 | -1.5 | 27.9 | -0.05 | 0.02 | 650/567 |
| `{"trend_ema": 1200, "rel_ema": 2400, "step_mult": 1.5, "vol_target": 0.0}` | -6.2 | -1.8 | 32.3 | -0.06 | -0.03 | 829/712 |
| `{"trend_ema": 1200, "rel_ema": 2400, "step_mult": 2.5, "vol_target": 0.03}` | -8.6 | -2.5 | 33.8 | -0.07 | -0.07 | 843/725 |
| `{"trend_ema": 2400, "rel_ema": 1200, "step_mult": 2.5, "vol_target": 0.03}` | -9.9 | -2.9 | 35.0 | -0.08 | -0.07 | 895/822 |
| `{"trend_ema": 2400, "rel_ema": 2400, "step_mult": 2.5, "vol_target": 0.03}` | -11.4 | -3.4 | 36.7 | -0.09 | -0.11 | 893/816 |
| `{"trend_ema": 2400, "rel_ema": 1200, "step_mult": 1.5, "vol_target": 0.03}` | -11.8 | -3.5 | 30.0 | -0.12 | -0.12 | 1359/1328 |
| `{"trend_ema": 2400, "rel_ema": 2400, "step_mult": 2.5, "vol_target": 0.0}` | -16.7 | -5.0 | 38.8 | -0.13 | -0.12 | 609/504 |
| `{"trend_ema": 1200, "rel_ema": 2400, "step_mult": 2.5, "vol_target": 0.0}` | -22.0 | -6.8 | 44.7 | -0.15 | -0.22 | 852/698 |
| `{"trend_ema": 2400, "rel_ema": 2400, "step_mult": 1.5, "vol_target": 0.0}` | -25.3 | -7.9 | 45.4 | -0.17 | -0.34 | 883/802 |
| `{"trend_ema": 2400, "rel_ema": 2400, "step_mult": 1.5, "vol_target": 0.03}` | -15.5 | -4.7 | 27.6 | -0.17 | -0.35 | 1021/966 |

## ETH r3 — 永續：只做多 vs 多空 × 相對強弱 × 核心倉（rel_ema=0 時空單條件不成立 → 等同只做多）

固定：step 2.5、vol_target 0.03

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"allow_short": true, "core_frac": 0.4, "rel_ema": 0, "trend_ema": 2400}` | 36.9 | 9.3 | 26.8 | 0.35 | 0.51 | 190/173 |
| `{"allow_short": false, "core_frac": 0.4, "rel_ema": 0, "trend_ema": 2400}` | 36.9 | 9.3 | 26.8 | 0.35 | 0.51 | 190/173 |
| `{"allow_short": true, "core_frac": 0.0, "rel_ema": 0, "trend_ema": 2400}` | 23.4 | 6.1 | 23.7 | 0.26 | 0.47 | 501/459 |
| `{"allow_short": false, "core_frac": 0.0, "rel_ema": 0, "trend_ema": 2400}` | 23.4 | 6.1 | 23.7 | 0.26 | 0.47 | 501/459 |
| `{"allow_short": true, "core_frac": 0.4, "rel_ema": 0, "trend_ema": 1200}` | 31.4 | 8.0 | 32.7 | 0.25 | 0.44 | 294/257 |
| `{"allow_short": false, "core_frac": 0.4, "rel_ema": 0, "trend_ema": 1200}` | 31.4 | 8.0 | 32.7 | 0.25 | 0.44 | 294/257 |
| `{"allow_short": false, "core_frac": 0.4, "rel_ema": 2400, "trend_ema": 1200}` | 18.6 | 5.0 | 28.5 | 0.17 | 0.33 | 242/211 |
| `{"allow_short": true, "core_frac": 0.0, "rel_ema": 0, "trend_ema": 1200}` | 10.8 | 3.0 | 28.3 | 0.1 | 0.27 | 450/374 |
| `{"allow_short": false, "core_frac": 0.0, "rel_ema": 0, "trend_ema": 1200}` | 10.8 | 3.0 | 28.3 | 0.1 | 0.27 | 450/374 |
| `{"allow_short": false, "core_frac": 0.0, "rel_ema": 2400, "trend_ema": 2400}` | 7.2 | 2.0 | 28.4 | 0.07 | 0.20 | 435/413 |
| `{"allow_short": false, "core_frac": 0.0, "rel_ema": 2400, "trend_ema": 1200}` | -1.3 | -0.4 | 32.3 | -0.01 | 0.05 | 357/290 |
| `{"allow_short": true, "core_frac": 0.0, "rel_ema": 2400, "trend_ema": 1200}` | -8.6 | -2.5 | 33.8 | -0.07 | -0.07 | 843/725 |
| `{"allow_short": true, "core_frac": 0.0, "rel_ema": 2400, "trend_ema": 2400}` | -11.4 | -3.4 | 36.7 | -0.09 | -0.11 | 893/816 |
| `{"allow_short": true, "core_frac": 0.4, "rel_ema": 2400, "trend_ema": 2400}` | -14.4 | -4.3 | 35.0 | -0.12 | -0.09 | 436/424 |
| `{"allow_short": false, "core_frac": 0.4, "rel_ema": 2400, "trend_ema": 2400}` | -12.2 | -3.6 | 27.1 | -0.13 | -0.14 | 233/233 |
| `{"allow_short": true, "core_frac": 0.4, "rel_ema": 2400, "trend_ema": 1200}` | -0.6 | -0.2 | 37.8 | -0.0 | 0.11 | 492/456 |

## ETH r4 — 現貨只做多 × BTC risk-on 濾網（rel_ema 當時為 2400）

固定：step 2.5；最終版 rel_ema=0（r3 顯示相對強弱濾網有害）

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"core_frac": 0.4, "trend_ema": 1200, "ref_trend_ema": 2400, "vol_target": 0.0}` | 54.1 | 13.0 | 21.6 | 0.6 | 0.71 | 126/114 |
| `{"core_frac": 0.6, "trend_ema": 1200, "ref_trend_ema": 2400, "vol_target": 0.0}` | 53.5 | 12.9 | 23.4 | 0.55 | 0.66 | 142/149 |
| `{"core_frac": 0.2, "trend_ema": 1200, "ref_trend_ema": 2400, "vol_target": 0.0}` | 37.0 | 9.3 | 17.6 | 0.53 | 0.70 | 143/130 |
| `{"core_frac": 0.4, "trend_ema": 1200, "ref_trend_ema": 2400, "vol_target": 0.03}` | 41.2 | 10.2 | 20.8 | 0.49 | 0.66 | 120/119 |
| `{"core_frac": 0.4, "trend_ema": 2400, "ref_trend_ema": 2400, "vol_target": 0.0}` | 45.5 | 11.2 | 23.9 | 0.47 | 0.63 | 161/170 |
| `{"core_frac": 0.2, "trend_ema": 1200, "ref_trend_ema": 2400, "vol_target": 0.03}` | 32.7 | 8.3 | 18.3 | 0.46 | 0.64 | 112/99 |
| `{"core_frac": 0.6, "trend_ema": 2400, "ref_trend_ema": 2400, "vol_target": 0.0}` | 51.9 | 12.6 | 28.6 | 0.44 | 0.60 | 144/156 |
| `{"core_frac": 0.4, "trend_ema": 1200, "ref_trend_ema": 0, "vol_target": 0.0}` | 42.5 | 10.5 | 25.3 | 0.42 | 0.55 | 186/156 |
| `{"core_frac": 0.2, "trend_ema": 2400, "ref_trend_ema": 2400, "vol_target": 0.03}` | 32.0 | 8.2 | 20.5 | 0.4 | 0.59 | 140/131 |
| `{"core_frac": 0.4, "trend_ema": 2400, "ref_trend_ema": 2400, "vol_target": 0.03}` | 34.1 | 8.7 | 23.0 | 0.38 | 0.55 | 119/130 |
| `{"core_frac": 0.6, "trend_ema": 1200, "ref_trend_ema": 2400, "vol_target": 0.03}` | 36.6 | 9.2 | 24.6 | 0.37 | 0.58 | 139/158 |
| `{"core_frac": 0.6, "trend_ema": 2400, "ref_trend_ema": 2400, "vol_target": 0.03}` | 35.0 | 8.9 | 25.9 | 0.34 | 0.53 | 172/199 |
| `{"core_frac": 0.2, "trend_ema": 2400, "ref_trend_ema": 2400, "vol_target": 0.0}` | 30.4 | 7.8 | 25.4 | 0.31 | 0.49 | 158/140 |
| `{"core_frac": 0.4, "trend_ema": 1200, "ref_trend_ema": 0, "vol_target": 0.03}` | 26.3 | 6.8 | 26.0 | 0.26 | 0.45 | 264/235 |
| `{"core_frac": 0.2, "trend_ema": 1200, "ref_trend_ema": 0, "vol_target": 0.03}` | 18.3 | 4.9 | 23.4 | 0.21 | 0.41 | 278/267 |
| `{"core_frac": 0.2, "trend_ema": 1200, "ref_trend_ema": 0, "vol_target": 0.0}` | 17.4 | 4.7 | 23.2 | 0.2 | 0.36 | 216/188 |
| `{"core_frac": 0.6, "trend_ema": 1200, "ref_trend_ema": 0, "vol_target": 0.0}` | 25.3 | 6.6 | 32.9 | 0.2 | 0.37 | 204/182 |
| `{"core_frac": 0.6, "trend_ema": 1200, "ref_trend_ema": 0, "vol_target": 0.03}` | 13.2 | 3.6 | 26.7 | 0.13 | 0.27 | 264/268 |
| `{"core_frac": 0.2, "trend_ema": 2400, "ref_trend_ema": 0, "vol_target": 0.0}` | -2.9 | -0.8 | 25.3 | -0.03 | 0.03 | 238/209 |
| `{"core_frac": 0.2, "trend_ema": 2400, "ref_trend_ema": 0, "vol_target": 0.03}` | -6.2 | -1.8 | 26.8 | -0.07 | -0.05 | 331/311 |
| `{"core_frac": 0.4, "trend_ema": 2400, "ref_trend_ema": 0, "vol_target": 0.03}` | -10.9 | -3.2 | 29.7 | -0.11 | -0.10 | 321/312 |
| `{"core_frac": 0.6, "trend_ema": 2400, "ref_trend_ema": 0, "vol_target": 0.03}` | -12.6 | -3.7 | 33.4 | -0.11 | -0.06 | 229/217 |
| `{"core_frac": 0.4, "trend_ema": 2400, "ref_trend_ema": 0, "vol_target": 0.0}` | -16.4 | -4.9 | 33.9 | -0.15 | -0.15 | 243/223 |
| `{"core_frac": 0.6, "trend_ema": 2400, "ref_trend_ema": 0, "vol_target": 0.0}` | -19.7 | -6.0 | 40.8 | -0.15 | -0.09 | 321/314 |

## ETH 消融 — 最終參數

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"ai_vol": false, "ai_drift": true}` | 65.7 | 15.4 | 22.0 | 0.7 | 0.82 | 275/240 |
| `{"ai_vol": true, "ai_drift": true}` | 68.3 | 15.9 | 25.7 | 0.62 | 0.78 | 203/169 |
| `{"ai_vol": true, "ai_drift": false}` | 35.0 | 8.9 | 22.4 | 0.39 | 0.56 | 160/146 |
| `{"ai_vol": false, "ai_drift": false}` | 30.4 | 7.8 | 26.1 | 0.3 | 0.49 | 341/326 |

## SOL r1 — 永續多空趨勢網格（已否決）

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"trend_ema": 1200, "trail_steps": 2, "break_steps": 3, "enter_z": 0.25}` | 286.5 | 46.6 | 46.6 | 1.0 | 1.04 | 892/778 |
| `{"trend_ema": 1200, "trail_steps": 6, "break_steps": 3, "enter_z": 0.25}` | 293.1 | 47.3 | 49.5 | 0.96 | 0.99 | 935/805 |
| `{"trend_ema": 1200, "trail_steps": 6, "break_steps": 3, "enter_z": 0.75}` | 183.4 | 34.3 | 48.5 | 0.71 | 0.87 | 695/606 |
| `{"trend_ema": 1200, "trail_steps": 4, "break_steps": 3, "enter_z": 0.25}` | 229.2 | 40.1 | 58.6 | 0.68 | 0.91 | 955/799 |
| `{"trend_ema": 1200, "trail_steps": 4, "break_steps": 2, "enter_z": 0.25}` | 162.1 | 31.4 | 54.1 | 0.58 | 0.82 | 812/685 |
| `{"trend_ema": 1200, "trail_steps": 2, "break_steps": 2, "enter_z": 0.25}` | 135.9 | 27.5 | 48.3 | 0.57 | 0.77 | 815/697 |
| `{"trend_ema": 1200, "trail_steps": 4, "break_steps": 3, "enter_z": 0.75}` | 133.9 | 27.2 | 58.0 | 0.47 | 0.76 | 677/572 |
| `{"trend_ema": 1200, "trail_steps": 6, "break_steps": 2, "enter_z": 0.25}` | 112.4 | 23.8 | 55.3 | 0.43 | 0.68 | 798/683 |
| `{"trend_ema": 2400, "trail_steps": 6, "break_steps": 3, "enter_z": 0.75}` | 97.1 | 21.2 | 50.7 | 0.42 | 0.64 | 757/661 |
| `{"trend_ema": 2400, "trail_steps": 4, "break_steps": 2, "enter_z": 0.25}` | 112.8 | 23.8 | 68.8 | 0.35 | 0.70 | 816/694 |
| `{"trend_ema": 2400, "trail_steps": 4, "break_steps": 2, "enter_z": 0.75}` | 89.5 | 19.8 | 57.6 | 0.34 | 0.65 | 614/521 |
| `{"trend_ema": 2400, "trail_steps": 6, "break_steps": 3, "enter_z": 0.25}` | 99.4 | 21.6 | 65.6 | 0.33 | 0.64 | 955/824 |
| `{"trend_ema": 2400, "trail_steps": 4, "break_steps": 3, "enter_z": 0.25}` | 88.6 | 19.7 | 62.5 | 0.31 | 0.61 | 974/817 |
| `{"trend_ema": 1200, "trail_steps": 4, "break_steps": 2, "enter_z": 0.75}` | 64.6 | 15.2 | 58.1 | 0.26 | 0.54 | 570/478 |
| `{"trend_ema": 2400, "trail_steps": 2, "break_steps": 3, "enter_z": 0.25}` | 58.8 | 14.0 | 56.8 | 0.25 | 0.52 | 906/790 |
| `{"trend_ema": 2400, "trail_steps": 4, "break_steps": 3, "enter_z": 0.75}` | 63.2 | 14.9 | 58.8 | 0.25 | 0.54 | 721/610 |
| `{"trend_ema": 2400, "trail_steps": 2, "break_steps": 2, "enter_z": 0.25}` | 62.2 | 14.7 | 60.5 | 0.24 | 0.54 | 833/708 |
| `{"trend_ema": 2400, "trail_steps": 6, "break_steps": 2, "enter_z": 0.25}` | 72.9 | 16.8 | 69.2 | 0.24 | 0.57 | 810/699 |
| `{"trend_ema": 2400, "trail_steps": 6, "break_steps": 2, "enter_z": 0.75}` | 45.6 | 11.2 | 64.2 | 0.17 | 0.47 | 621/532 |
| `{"trend_ema": 1200, "trail_steps": 6, "break_steps": 2, "enter_z": 0.75}` | 40.6 | 10.1 | 63.1 | 0.16 | 0.42 | 582/495 |
| `{"trend_ema": 2400, "trail_steps": 2, "break_steps": 2, "enter_z": 0.75}` | 29.3 | 7.5 | 47.7 | 0.16 | 0.39 | 467/410 |
| `{"trend_ema": 1200, "trail_steps": 2, "break_steps": 3, "enter_z": 0.75}` | -4.8 | -1.4 | 60.1 | -0.02 | 0.12 | 467/402 |
| `{"trend_ema": 1200, "trail_steps": 2, "break_steps": 2, "enter_z": 0.75}` | -15.3 | -4.6 | 56.9 | -0.08 | -0.00 | 440/377 |
| `{"trend_ema": 2400, "trail_steps": 2, "break_steps": 3, "enter_z": 0.75}` | -34.4 | -11.2 | 63.0 | -0.18 | -0.11 | 503/438 |

## SOL r2 — 永續多空 × 波動目標 × 核心倉（已否決）

固定：trend_ema 1200、break 3、enter_z 0.25

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"trail_steps": 2, "vol_target": 0.0, "core_frac": 0.4}` | 286.5 | 46.6 | 46.6 | 1.0 | 1.04 | 892/778 |
| `{"trail_steps": 6, "vol_target": 0.0, "core_frac": 0.4}` | 293.1 | 47.3 | 49.5 | 0.96 | 0.99 | 935/805 |
| `{"trail_steps": 2, "vol_target": 0.06, "core_frac": 0.4}` | 223.6 | 39.4 | 46.7 | 0.84 | 0.98 | 892/778 |
| `{"trail_steps": 4, "vol_target": 0.0, "core_frac": 0.4}` | 229.2 | 40.1 | 58.6 | 0.68 | 0.91 | 955/799 |
| `{"trail_steps": 4, "vol_target": 0.0, "core_frac": 0.2}` | 167.4 | 32.1 | 47.8 | 0.67 | 0.88 | 964/803 |
| `{"trail_steps": 6, "vol_target": 0.06, "core_frac": 0.4}` | 172.5 | 32.8 | 49.1 | 0.67 | 0.83 | 935/805 |
| `{"trail_steps": 4, "vol_target": 0.06, "core_frac": 0.4}` | 182.8 | 34.2 | 58.4 | 0.59 | 0.86 | 955/799 |
| `{"trail_steps": 2, "vol_target": 0.0, "core_frac": 0.2}` | 123.0 | 25.5 | 45.7 | 0.56 | 0.80 | 879/734 |
| `{"trail_steps": 6, "vol_target": 0.04, "core_frac": 0.4}` | 129.3 | 26.5 | 47.3 | 0.56 | 0.78 | 935/805 |
| `{"trail_steps": 2, "vol_target": 0.04, "core_frac": 0.4}` | 119.1 | 24.9 | 46.3 | 0.54 | 0.78 | 892/778 |
| `{"trail_steps": 4, "vol_target": 0.06, "core_frac": 0.2}` | 126.8 | 26.1 | 48.0 | 0.54 | 0.80 | 964/803 |
| `{"trail_steps": 6, "vol_target": 0.0, "core_frac": 0.2}` | 102.6 | 22.1 | 42.9 | 0.52 | 0.67 | 949/801 |
| `{"trail_steps": 2, "vol_target": 0.06, "core_frac": 0.2}` | 89.9 | 19.9 | 45.8 | 0.43 | 0.70 | 879/734 |
| `{"trail_steps": 4, "vol_target": 0.04, "core_frac": 0.4}` | 115.7 | 24.3 | 57.4 | 0.42 | 0.74 | 955/799 |
| `{"trail_steps": 4, "vol_target": 0.04, "core_frac": 0.2}` | 77.7 | 17.7 | 48.5 | 0.36 | 0.66 | 964/803 |
| `{"trail_steps": 6, "vol_target": 0.06, "core_frac": 0.2}` | 65.5 | 15.3 | 44.5 | 0.34 | 0.55 | 949/801 |
| `{"trail_steps": 6, "vol_target": 0.04, "core_frac": 0.2}` | 38.8 | 9.7 | 40.5 | 0.24 | 0.44 | 949/801 |
| `{"trail_steps": 2, "vol_target": 0.04, "core_frac": 0.2}` | 40.6 | 10.1 | 44.4 | 0.23 | 0.47 | 879/734 |

## SOL r3 — 永續：只做多 vs 多空 × 相對強弱（rel_ema=0 → 等同只做多）

固定：trail 4、break 3、enter_z 0.25

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"allow_short": true, "rel_ema": 0, "trend_ema": 1200, "core_frac": 0.2}` | 276.5 | 45.5 | 39.3 | 1.16 | 1.40 | 521/448 |
| `{"allow_short": false, "rel_ema": 0, "trend_ema": 1200, "core_frac": 0.2}` | 276.5 | 45.5 | 39.3 | 1.16 | 1.40 | 521/448 |
| `{"allow_short": true, "rel_ema": 0, "trend_ema": 1200, "core_frac": 0.4}` | 297.5 | 47.8 | 50.8 | 0.94 | 1.22 | 517/436 |
| `{"allow_short": false, "rel_ema": 0, "trend_ema": 1200, "core_frac": 0.4}` | 297.5 | 47.8 | 50.8 | 0.94 | 1.22 | 517/436 |
| `{"allow_short": true, "rel_ema": 0, "trend_ema": 2400, "core_frac": 0.2}` | 178.2 | 33.6 | 39.2 | 0.86 | 1.11 | 521/449 |
| `{"allow_short": false, "rel_ema": 0, "trend_ema": 2400, "core_frac": 0.2}` | 178.2 | 33.6 | 39.2 | 0.86 | 1.11 | 521/449 |
| `{"allow_short": false, "rel_ema": 2400, "trend_ema": 1200, "core_frac": 0.2}` | 181.6 | 34.0 | 41.0 | 0.83 | 1.17 | 466/398 |
| `{"allow_short": true, "rel_ema": 0, "trend_ema": 2400, "core_frac": 0.4}` | 195.7 | 35.9 | 44.8 | 0.8 | 1.00 | 518/439 |
| `{"allow_short": false, "rel_ema": 0, "trend_ema": 2400, "core_frac": 0.4}` | 195.7 | 35.9 | 44.8 | 0.8 | 1.00 | 518/439 |
| `{"allow_short": false, "rel_ema": 2400, "trend_ema": 2400, "core_frac": 0.2}` | 140.5 | 28.2 | 39.2 | 0.72 | 0.99 | 489/420 |
| `{"allow_short": false, "rel_ema": 2400, "trend_ema": 2400, "core_frac": 0.4}` | 175.3 | 33.2 | 46.5 | 0.71 | 0.96 | 488/412 |
| `{"allow_short": false, "rel_ema": 2400, "trend_ema": 1200, "core_frac": 0.4}` | 202.4 | 36.8 | 52.7 | 0.7 | 1.06 | 468/392 |
| `{"allow_short": true, "rel_ema": 2400, "trend_ema": 1200, "core_frac": 0.2}` | 92.4 | 20.4 | 48.3 | 0.42 | 0.67 | 879/727 |
| `{"allow_short": true, "rel_ema": 2400, "trend_ema": 1200, "core_frac": 0.4}` | 112.5 | 23.8 | 60.6 | 0.39 | 0.69 | 874/726 |
| `{"allow_short": true, "rel_ema": 2400, "trend_ema": 2400, "core_frac": 0.2}` | 49.7 | 12.1 | 54.9 | 0.22 | 0.49 | 922/771 |
| `{"allow_short": true, "rel_ema": 2400, "trend_ema": 2400, "core_frac": 0.4}` | 50.3 | 12.2 | 60.1 | 0.2 | 0.48 | 919/767 |

## SOL r4 — 現貨只做多

固定：trend_ema 1200、break 3、enter_z 0.25

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"core_frac": 0.3, "trail_steps": 6, "step_mult": 2}` | 146.8 | 29.1 | 37.5 | 0.78 | 0.94 | 794/713 |
| `{"core_frac": 0.3, "trail_steps": 2, "step_mult": 2}` | 100.2 | 21.7 | 35.3 | 0.61 | 0.83 | 797/659 |
| `{"core_frac": 0.2, "trail_steps": 2, "step_mult": 2}` | 93.1 | 20.5 | 34.0 | 0.6 | 0.87 | 806/660 |
| `{"core_frac": 0.2, "trail_steps": 4, "step_mult": 3}` | 110.0 | 23.4 | 39.5 | 0.59 | 0.89 | 507/426 |
| `{"core_frac": 0.2, "trail_steps": 6, "step_mult": 2}` | 95.2 | 20.8 | 35.6 | 0.59 | 0.80 | 790/709 |
| `{"core_frac": 0.3, "trail_steps": 4, "step_mult": 2}` | 89.7 | 19.9 | 41.7 | 0.48 | 0.73 | 829/700 |
| `{"core_frac": 0.3, "trail_steps": 4, "step_mult": 3}` | 88.2 | 19.6 | 44.1 | 0.44 | 0.73 | 510/422 |
| `{"core_frac": 0.3, "trail_steps": 6, "step_mult": 3}` | 78.4 | 17.8 | 41.0 | 0.43 | 0.64 | 487/414 |
| `{"core_frac": 0.2, "trail_steps": 2, "step_mult": 3}` | 64.2 | 15.1 | 37.4 | 0.4 | 0.67 | 473/386 |
| `{"core_frac": 0.3, "trail_steps": 2, "step_mult": 3}` | 67.6 | 15.7 | 40.2 | 0.39 | 0.64 | 477/401 |
| `{"core_frac": 0.2, "trail_steps": 6, "step_mult": 3}` | 51.7 | 12.5 | 38.4 | 0.33 | 0.53 | 488/415 |
| `{"core_frac": 0.2, "trail_steps": 4, "step_mult": 2}` | 27.1 | 7.0 | 40.6 | 0.17 | 0.39 | 824/695 |

## SOL 消融 — 最終參數

| 參數 | 報酬% | CAGR% | 最大回撤% | Calmar | Sharpe | 網格買/賣 |
|---|---|---|---|---|---|---|
| `{"ai_vol": true, "ai_drift": false}` | 260.3 | 43.7 | 53.6 | 0.82 | 1.14 | 1601/1352 |
| `{"ai_vol": true, "ai_drift": true}` | 146.8 | 29.1 | 37.5 | 0.78 | 0.94 | 794/713 |
| `{"ai_vol": false, "ai_drift": false}` | 162.4 | 31.4 | 52.2 | 0.6 | 0.92 | 1549/1261 |
| `{"ai_vol": false, "ai_drift": true}` | 39.2 | 9.8 | 39.6 | 0.25 | 0.46 | 823/707 |

