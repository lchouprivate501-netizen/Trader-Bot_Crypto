# AGENTS.md

Instructions for AI agents (Claude, Grok, Codex, Cursor, Gemini CLI…) working in this repository.
This repository is one project: the BTC / ETH / SOL trend-following EAs in `skills/freqai-ea-trading/`
(primary: USDT-M futures EAs for ETH and SOL, the spot EA for BTC).
Details are in Traditional Chinese.

## 這個倉庫有什麼

| 路徑 | 內容 | AI 先讀 |
|---|---|---|
| `skills/freqai-ea-trading/` | 合約 EA（ETH、SOL 主要策略）與現貨 EA（BTC 主要策略），Freqtrade + FreqAI、事前登記驗證；EA 交易台與 MCP 伺服器、研發/回測/圖表工具、維護引擎、Docker 部署 | [`AGENTS.md`](skills/freqai-ea-trading/AGENTS.md)（交易）、[`SKILL.md`](skills/freqai-ea-trading/SKILL.md)（全部功能） |
| `skills/freqai-ea-trading/screener/` | 全網加密貨幣日內篩選器（Binance / Bybit / OKX USDT 永續）：流動性、波動、非加密排除、滑價、評分；事前登記驗證；新聞催化劑（未驗證）與排程 Prompt（`prompts/`） | [`intraday-screener.md`](skills/freqai-ea-trading/references/intraday-screener.md) |
| `agents/ea-maintainer.md` | EA 維護 Agent（每週健康檢查、診斷、改版流程） | 該檔 |
| `.claude-plugin/` | Claude Code 外掛 `freqai-crypto-trading` 與外掛市集清單 | — |

- 使用者要你「依 EA 交易」「執行 EA」「跑一輪交易台」：讀 `skills/freqai-ea-trading/AGENTS.md`，用 MCP 伺服器 `freqai-ea-desk` 或 `python3 skills/freqai-ea-trading/desk/ea_desk.py` 指令。
- 使用者問 EA 還有沒有效：照 `agents/ea-maintainer.md` 做例行檢查。
- 使用者要找「適合日內交易的幣」：`python3 skills/freqai-ea-trading/screener/intraday_screener.py scan`（連不到 Binance 用 `--exchange bybit`／`okx`／`archive`；加 `--news` 看新聞催化劑）。回報時說清楚：清單挑的是流動性夠、會動的幣，驗證顯示它**不能**預測哪個幣會盤整；「近4h」只是描述；新聞「焦點」尚未驗證（權重 0，前向驗證中）。
- 排程每天自動跑篩選與新聞：照 [`screener/prompts/README.md`](skills/freqai-ea-trading/screener/prompts/README.md)（每日清單、盤前更新、每週檢討）。排程跑的時候只做研究與報告，不下單、不改 `screener/config.json`。
- 使用者想「看」系統在做什麼：請他執行 `python3 skills/freqai-ea-trading/desk/console.py --open`（AI 交易辦公室）。
- 安裝到各家 AI：[`references/ai-agents.md`](skills/freqai-ea-trading/references/ai-agents.md)。

## 對所有 AI 都適用的規則

1. 永遠不要向使用者要交易所 API 金鑰、密碼或 2FA，也不要把它們寫進檔案、設定或 commit。
2. 永遠不要提幣、轉帳、借貸。合約只用逐倉與指令給的槓桿；不提高槓桿、不改全倉、不讓部位超過指令數量；BTC 只在現貨交易（它的合約 EA 未通過驗證）。
3. 不放寬任何風控設定（`skills/freqai-ea-trading/desk/config.json`、使用者的 `~/.freqai-ea/config.json`、`maintenance/baselines.json` 的門檻）；只有使用者能改。
4. 不自己開實盤、不解除 HALT：這些需要使用者在終端機互動確認。
5. 不修改已驗證 EA 的參數或策略邏輯；改版只能走 `skills/freqai-ea-trading/maintenance/maintenance-protocol.md` 的候選版本流程。
6. 回報要誠實：虧損、錯誤、對不上的帳都要說；回測結果一定附上最大回撤與同期買入持有。

## 測試

```bash
python3 skills/freqai-ea-trading/desk/test_desk.py                 # EA 交易台（現貨）+ MCP 伺服器（不需網路或套件）
python3 skills/freqai-ea-trading/desk/test_desk_perp.py            # EA 交易台（合約：做空、槓桿、資金費）
python3 skills/freqai-ea-trading/desk/test_console.py              # AI 交易辦公室（控制台）
python3 skills/freqai-ea-trading/screener/test_screener.py         # 日內篩選器（不需網路或套件）
python3 skills/freqai-ea-trading/maintenance/test_guard_live.py    # 實盤守衛（Freqtrade venv）
```
