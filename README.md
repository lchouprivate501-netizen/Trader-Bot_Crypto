# pionex-macd

Freqtrade MACD(12,26,9) 三角洲交叉策略（USDT 永續、15m、OKX 資料）加上開源技能入場閘門，以及 MCP 伺服器 `pionex-trading-skills`（並附官方 `graphify` MCP）。

- 預設 `dry_run=true`，freqtrade 只出訊號。
- 閘門規則對齊已克隆技能的原文門檻（見 `docs/GATE_RULES.md`）。
- 安裝：`git clone https://github.com/lchouprivate501-netizen/pionex-macd` 後執行 `./bootstrap.sh`。細節見 [INSTALL.md](INSTALL.md)。

本倉庫不含交易所金鑰，也不內嵌第三方技能原始碼；`bootstrap.sh` 會從官方來源取得 Docker 映像、兩個 GitHub 技能倉庫，以及 PyPI 上的 `graphifyy`。
