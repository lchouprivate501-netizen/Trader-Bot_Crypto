# AGENTS.md

Instructions for AI agents (Claude, Grok, Codex, Cursor, Gemini CLI…) working in this repository.
This repository is one project: the BTC / ETH / SOL trend-following EAs in `skills/freqai-ea-trading/`.
Details are in Traditional Chinese.

## 這個倉庫有什麼

| 路徑 | 內容 | AI 先讀 |
|---|---|---|
| `skills/freqai-ea-trading/` | 三個 EA（Freqtrade + FreqAI，事前登記驗證）、EA 交易台與 MCP 伺服器、研發/回測/圖表工具、維護引擎、Docker 部署 | [`AGENTS.md`](skills/freqai-ea-trading/AGENTS.md)（交易）、[`SKILL.md`](skills/freqai-ea-trading/SKILL.md)（全部功能） |
| `agents/ea-maintainer.md` | EA 維護 Agent（每週健康檢查、診斷、改版流程） | 該檔 |
| `.claude-plugin/` | Claude Code 外掛 `freqai-crypto-trading` 與外掛市集清單 | — |

- 使用者要你「依 EA 交易」「執行 EA」「跑一輪交易台」：讀 `skills/freqai-ea-trading/AGENTS.md`，用 MCP 伺服器 `freqai-ea-desk` 或 `python3 skills/freqai-ea-trading/desk/ea_desk.py` 指令。
- 使用者問 EA 還有沒有效：照 `agents/ea-maintainer.md` 做例行檢查。
- 安裝到各家 AI：[`references/ai-agents.md`](skills/freqai-ea-trading/references/ai-agents.md)。

## 對所有 AI 都適用的規則

1. 永遠不要向使用者要交易所 API 金鑰、密碼或 2FA，也不要把它們寫進檔案、設定或 commit。
2. 永遠不要提幣、轉帳、借貸，或改用槓桿 / 合約。
3. 不放寬任何風控設定（`skills/freqai-ea-trading/desk/config.json`、使用者的 `~/.freqai-ea/config.json`、`maintenance/baselines.json` 的門檻）；只有使用者能改。
4. 不自己開實盤、不解除 HALT：這些需要使用者在終端機互動確認。
5. 不修改已驗證 EA 的參數或策略邏輯；改版只能走 `skills/freqai-ea-trading/maintenance/maintenance-protocol.md` 的候選版本流程。
6. 回報要誠實：虧損、錯誤、對不上的帳都要說；回測結果一定附上最大回撤與同期買入持有。

## 測試

```bash
python3 skills/freqai-ea-trading/desk/test_desk.py                 # EA 交易台 + MCP 伺服器（不需網路或套件）
python3 skills/freqai-ea-trading/maintenance/test_guard_live.py    # 實盤守衛（Freqtrade venv）
```
