# AGENTS.md

Instructions for AI coding / trading agents (Codex, Cursor, Gemini CLI, Grok, Claude…) working in this repository.
Details are in Traditional Chinese.

## 這個倉庫有什麼

| 路徑 | 內容 | AI 先讀 |
|---|---|---|
| `skills/freqai-ea-trading/` | BTC / ETH / SOL 趨勢跟隨 EA（Freqtrade + FreqAI，事前登記驗證）＋ **EA 交易台**：AI 依 EA 指令在使用者的交易所下單 | [`skills/freqai-ea-trading/AGENTS.md`](skills/freqai-ea-trading/AGENTS.md)、安裝：[`references/ai-agents.md`](skills/freqai-ea-trading/references/ai-agents.md) |
| `skills/freqai-grid-trading/` | BTC / ETH / SOL FreqAI 網格策略、回測與研究工具 | [`skills/freqai-grid-trading/SKILL.md`](skills/freqai-grid-trading/SKILL.md) |
| `agents/ea-maintainer.md` | EA 維護 Agent（每週健康檢查、診斷、改版流程） | 該檔 |
| 其餘（`company/`、`rnd/`、`exec/`、`mcp/`） | Grok Bot「Trader」交易公司（Pionex 永續，MCP `pionex_trading_skills`） | [`docs/TRADER_PLAYBOOK.md`](docs/TRADER_PLAYBOOK.md) |

使用者要你「依 EA 交易」「執行 EA」「跑一輪交易台」時：讀 `skills/freqai-ea-trading/AGENTS.md`，用 MCP 伺服器 `freqai-ea-desk` 或 `python3 skills/freqai-ea-trading/desk/ea_desk.py` 指令。

## 對所有 AI 都適用的規則

1. 永遠不要向使用者要交易所 API 金鑰、密碼或 2FA，也不要把它們寫進檔案、設定或 commit。
2. 永遠不要提幣、轉帳、借貸，或改用槓桿。
3. 不放寬任何風控設定（`company/risk_caps.json`、`skills/freqai-ea-trading/desk/config.json`、使用者的 `~/.freqai-ea/config.json`）；只有使用者能改。
4. 不自己開實盤、不解除 HALT：這些需要使用者在終端機互動確認。
5. 不修改已驗證 EA 的參數或策略邏輯；改版只能走 `skills/freqai-ea-trading/maintenance/maintenance-protocol.md` 的候選版本流程。
6. 回報要誠實：虧損、錯誤、對不上的帳都要說。

## 測試

```bash
python3 skills/freqai-ea-trading/desk/test_desk.py      # EA 交易台 + MCP 伺服器（不需網路或套件）
```
