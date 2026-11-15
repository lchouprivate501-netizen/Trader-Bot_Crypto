# 安裝 Trader Bot（全新範本使用者）

需求：Linux x86_64、約 2 GB 可用磁碟、可連到 github.com / pypi.org / www.okx.com。不需要 Docker、root、GPU、任何 API 金鑰或 LLM。

```bash
mkdir -p ~/crypto-trading
git clone https://github.com/lchouprivate501-netizen/Trader-Bot_Crypto ~/crypto-trading/pionex-macd
cd ~/crypto-trading/pionex-macd
bash bootstrap.sh          # 可重複執行；DAYS=180 bash bootstrap.sh 可縮短資料天數
```

本機目錄請保持 `~/crypto-trading/pionex-macd`（這是現有排程器與環境變數 `PIONEX_MACD_HOME` 的相容路徑）。

`bootstrap.sh` 依序：

1. 若沒有 `uv`，從 astral-sh/uv 官方 GitHub release 下載並驗證 sha256（不使用 `curl | bash`）。
2. 建立 Python 3.13 虛擬環境 `~/crypto-trading/venvs/pionex-trading-skills`，以 `uv pip install -e mcp` 安裝 nautilus_trader 1.231.0、optuna、mcp 等（版本鎖在 `mcp/pyproject.toml`）。venv 路徑與模組名 `pionex_trading_skills` 請不要改，這是現有 MCP 連接器的相容入口。
3. 在 `~/trading/venvs/graphify` 安裝 graphifyy 0.9.108（可重複執行、版本鎖定；獨立 venv，不使用 `curl | bash`）。
4. 從 OKX 公開 API 下載 `company/universe.json` 標的的 5m K 線（15m/1h 由 5m 重採樣；可中斷，重跑會續傳）。
5. 以 stdio JSON-RPC 跑 `scripts/mcp_smoke.py`（tools/list + 每個工具 tools/call）。
6. 啟動 5 分鐘排程器 `scripts/scheduler.sh start`（nohup + pidfile，不需 cron/systemd）。

安裝後，Trader 首次執行應呼叫 `setup_check`（缺什麼就照回傳的 `install` 指令補），再呼叫 `exchange_get`，詢問使用者是否沿用預設 Pionex，或要新增/更換交易所。更換方式見 [README.md](README.md#更換或新增交易所)。也可以不經 MCP，直接執行：

```bash
~/crypto-trading/venvs/pionex-trading-skills/bin/python -m company.setup
```

## 連接 Grok Bot

新增 stdio MCP 連接器（往後範本也請用這組指令，這是相容入口）：

| 欄位 | 值 |
|---|---|
| command | `~/crypto-trading/venvs/pionex-trading-skills/bin/python`（請展開成絕對路徑） |
| args | `-m pionex_trading_skills` |
| env | `PIONEX_MACD_HOME=~/crypto-trading/pionex-macd`、`CRYPTO_TRADING_HOME=~/crypto-trading` |

（可選）graphify 連接器：`command` 為 `~/trading/venvs/graphify/bin/graphify-mcp`，工作目錄為倉庫根目錄。

不需要也不要放任何交易所金鑰。

## 常用指令

```bash
PY=~/crypto-trading/venvs/pionex-trading-skills/bin/python
$PY -m company.setup                            # 安裝檢查
$PY -m rnd.pipeline vwap_pullback --trials 60   # 研發流水線（優化前 70% → nautilus 回測 → 報表 → 登記簿）
$PY -m rnd.data --days 365 --tf 5m              # 增量更新資料
bash scripts/scheduler.sh status|start|stop|once     # 排程器
$PY scripts/mcp_smoke.py                        # MCP 自測
$PY scripts/test_exchange_set.py                # 交易所設定檔測試（用暫存複本，不改目前啟用的交易所）
```

## 新增策略

1. 複製 `rnd/strategies/vwap_pullback.py`，改 `NAME/DESCRIPTION/DEFAULTS/SPACE/signals()/near()`。
2. 把名稱加進 `rnd/strategies/__init__.py` 的 `ALL`。
3. `rnd_run_backtest("<name>")`；結果會寫進 `rnd/strategies/registry.json` 與 `rnd/reports/<name>/`。
