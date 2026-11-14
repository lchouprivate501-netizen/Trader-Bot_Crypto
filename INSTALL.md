# pionex-macd 第一次安裝

這套範本在 freqtrade 上跑 MACD(12,26,9) 三角洲交叉策略，只出訊號、預設模擬盤（`dry_run=true`）。實單若要下，由獨立的 Pionex 瀏覽器機器人執行，本堆疊不會用 API 下單。市場資料使用 OKX USDT 永續（部分環境 Binance／Bybit 可能被封鎖）。

## 1. 下載並執行安裝腳本

建議放在 `~/crypto-trading/pionex-macd`（技能倉庫與 MCP 虛擬環境會裝在上一層 `~/crypto-trading/`）：

```bash
mkdir -p ~/crypto-trading
git clone https://github.com/lchouprivate501-netizen/pionex-macd ~/crypto-trading/pionex-macd
cd ~/crypto-trading/pionex-macd
./bootstrap.sh
```

腳本可重複執行，而且：

- 若尚未安裝，從 Docker 官方 apt（`download.docker.com`）安裝 Docker Engine 與 Compose plugin（不會用 `curl | bash`）
- 把目前使用者加入 `docker` 群組；沒有 systemd 時會以 `dockerd -G docker` 啟動／重啟 daemon，讓 `docker ps` 不必用 root
- 浅克隆 `tradermonty/claude-trading-skills` 與 `agiprolabs/claude-trading-skills`
- 拉取 `freqtradeorg/freqtrade:stable_freqai`
- 建立 Python 虛擬環境，安裝本倉庫的 MCP 套件與 PyPI 上的 `graphifyy`
- 若缺少 `state/mode`，會建立為 `PAPER`，並寫入空白的 `state/ledger.csv` 表頭
- 在不需 LLM 金鑰的模式下產生 `graphify-out/graph.json`
- 寫入本機 `VERSIONS.md`，並印出 `pionex-trading-skills` 與 `graphify` 兩份 MCP 註冊設定

## 2. 註冊 MCP

把 `bootstrap.sh` 印出的設定貼到你的 Grok Bot／Cursor／Claude MCP 清單。請同時加入：

- `pionex-trading-skills`：交易技能、閘門作業與 graphify 查詢（passthrough）
- `graphify`：官方 `graphify-mcp`，讀取本倉庫的 `graphify-out/graph.json`

印出的 `command`／路徑會依你的安裝位置展開，不是寫死的單一使用者家目錄。若加入 docker 群組後目前 shell 仍無法使用 `docker`，請重新登入或執行 `sg docker -c 'docker ps'`。

## 3. 填寫機密（不要在聊天室貼上）

複製後的 `.env` 權限是 600。請在本機自行填：

- 交易所 Key／Secret／Password（僅 freqtrade 使用；目前維持模擬盤可不填）
- Telegram（未填則保持停用）
- freqtrade API 帳密與 JWT（啟動模擬容器前請換成強隨機值）

請把設定檔裡的 `CHANGE_ME_*` 佔位字串換成你自己的值，不要把密鑰貼到聊天。

## 4. 下載資料並回測（建議先做完再談實盤）

波動閘需要較長的**日線**歷史（約 400 日 1d）。只靠 1200 根 15m（約 12.5 日）時，百分位會是 NaN，閘門會擋下進場。在專案目錄執行：

```bash
docker run --rm -v "$PWD/user_data:/freqtrade/user_data" \
  freqtradeorg/freqtrade:stable_freqai \
  download-data --config /freqtrade/user_data/config.macd.futures.json \
  --trading-mode futures --timeframes 15m 1h 1d --days 400

docker run --rm -v "$PWD/user_data:/freqtrade/user_data" \
  freqtradeorg/freqtrade:stable_freqai \
  backtesting --config /freqtrade/user_data/config.macd.futures.json \
  --strategy MacdGatedFutures --fee 0.001
```

沒有 systemd 時，若 `docker info` 失敗，`bootstrap.sh` 會自行用 `dockerd -G docker` 重啟。手動啟動可用：

```bash
sudo sh -c 'dockerd -G docker --log-level=info >> /var/log/dockerd.log 2>&1' &
```

通過樣本外／walk-forward 條件前，請維持 `dry_run=true`。未親口確認切換實盤前不要改這個開關。

## 5. 選擇性：啟動模擬交易容器

填好 API 帳密與 JWT 後（`.env` 權限 600）：

```bash
docker compose up -d
```

埠只綁 `127.0.0.1:8080`。可用 `curl http://127.0.0.1:8080/api/v1/ping` 檢查（不必用 root）。此容器必須保持 `dry_run=true`。

若容器內連不上交易所（例如主機的出口代理 `198.18.0.x` 從 Docker bridge 連不到），在 Linux 上改用：

```bash
docker compose -f docker-compose.hostnet.yml up -d
```

這個檔案使用 `network_mode: host`，API 仍聽在 `127.0.0.1:8080`。

## 6. graphify 知識圖

`bootstrap.sh` 會試著產生圖；若要手動更新（不需要 LLM 金鑰）：

```bash
# 虛擬環境在倉庫上一層的 venvs/（若你依建議 clone 到 ~/crypto-trading/pionex-macd）
GRAPHIFY_BACKEND=none "$HOME/crypto-trading/venvs/pionex-trading-skills/bin/graphify" update .
```

圖檔預設為 `graphify-out/graph.json`。Markdown 筆記若要進圖，才需要另外的 LLM 金鑰；本範本預設不安裝付費服務。

外部閘門排程示例（本機時區或 UTC 請自行決定）：

```cron
*/5 * * * * cd "$HOME/crypto-trading/pionex-macd" && ../venvs/pionex-trading-skills/bin/pionex-gatekeeper circuit_breaker
0 */6 * * * cd "$HOME/crypto-trading/pionex-macd" && ../venvs/pionex-trading-skills/bin/pionex-gatekeeper event_risk
30 0 * * * cd "$HOME/crypto-trading/pionex-macd" && ../venvs/pionex-trading-skills/bin/pionex-gatekeeper crypto_regime
```

在 `macd_gates` 把 `event_risk`／`circuit_breaker`／`crypto_regime` 改成 `true` 之前，請先確認對應 JSON 已連續更新且格式正確（狀態檔有問題會 fail-closed，不開新倉）。
