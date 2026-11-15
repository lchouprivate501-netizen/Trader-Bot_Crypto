# 安裝（全新範本使用者）

需求：Linux x86_64、約 2 GB 可用磁碟、可連到 github.com / pypi.org / www.okx.com。不需要 Docker、root、GPU、任何 API 金鑰或 LLM。

```bash
mkdir -p ~/crypto-trading
git clone https://github.com/lchouprivate501-netizen/pionex-macd ~/crypto-trading/pionex-macd
cd ~/crypto-trading/pionex-macd
bash bootstrap.sh          # 可重複執行；DAYS=180 bash bootstrap.sh 可縮短資料天數
```

`bootstrap.sh` 依序：

1. 若沒有 `uv`，從 astral-sh/uv 官方 GitHub release 下載並驗證 sha256（不使用 `curl | bash`）。
2. 建立 Python 3.13 虛擬環境 `~/crypto-trading/venvs/pionex-trading-skills`，以 `uv pip install -e mcp` 安裝 nautilus_trader 1.231.0、optuna、mcp 等（版本鎖在 `mcp/pyproject.toml`）。
3. 從 OKX 公開 API 下載 `company/universe.json` 標的的 5m K 線（15m/1h 由 5m 重採樣；可中斷，重跑會續傳）。
4. 以 stdio JSON-RPC 跑 `scripts/mcp_smoke.py`（tools/list + 每個工具 tools/call）。
5. 啟動 5 分鐘排程器 `scripts/scheduler.sh start`（nohup + pidfile，不需 cron/systemd）。

## 連接 Grok Bot

新增 stdio MCP 連接器：

| 欄位 | 值 |
|---|---|
| command | `~/crypto-trading/venvs/pionex-trading-skills/bin/python`（請展開成絕對路徑） |
| args | `-m pionex_trading_skills` |
| env | `PIONEX_MACD_HOME=~/crypto-trading/pionex-macd`、`CRYPTO_TRADING_HOME=~/crypto-trading` |

不需要也不要放任何交易所金鑰。

## 常用指令

```bash
PY=~/crypto-trading/venvs/pionex-trading-skills/bin/python
$PY -m rnd.pipeline vwap_pullback --trials 60   # 研發流水線（優化前 70% → nautilus 回測 → 報表 → 登記簿）
$PY -m rnd.data --days 365 --tf 5m              # 增量更新資料
bash scripts/scheduler.sh status|start|stop|once     # 排程器
$PY scripts/mcp_smoke.py                        # MCP 自測
```

## 新增策略

1. 複製 `rnd/strategies/vwap_pullback.py`，改 `NAME/DESCRIPTION/DEFAULTS/SPACE/signals()/near()`。
2. 把名稱加進 `rnd/strategies/__init__.py` 的 `ALL`。
3. `rnd_run_backtest("<name>")`；結果會寫進 `rnd/strategies/registry.json` 與 `rnd/reports/<name>/`。
