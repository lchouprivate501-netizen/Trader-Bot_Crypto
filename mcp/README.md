# pionex-trading-skills MCP（v2）

Trader 私人交易公司的單一 stdio MCP。工具清單與用法見上層 `docs/TRADER_PLAYBOOK.md`。
不持有交易所金鑰、不下單；長時間工作（回測/優化）以背景程序執行並用 `job_status` 輪詢。

啟動：`$CRYPTO_TRADING_HOME/venvs/pionex-trading-skills/bin/python -m pionex_trading_skills`（環境變數 `PIONEX_MACD_HOME` 指向本 repo）。
