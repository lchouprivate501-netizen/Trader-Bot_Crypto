#!/usr/bin/env python3
"""EA 交易台的 MCP 伺服器（stdio，JSON-RPC 2.0）。只用 Python 標準函式庫，不需要安裝 mcp 套件。

任何支援 stdio MCP 的 AI 都能用：Claude Code / Claude Desktop、Grok（stdio MCP 連接器）、Cursor 等。
    command: python3
    args:    <本倉庫>/skills/freqai-ea-trading/desk/mcp_server.py
    env:     EA_HOME=~/.freqai-ea（可省略）

本伺服器不持有交易所金鑰、不下單、不能開實盤或解除暫停；下單由 AI 在使用者的交易所進行。
"""
from __future__ import annotations

import io
import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ea_desk  # noqa: E402

VERSION = "1.0.0"
PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "BTC/ETH/SOL 趨勢跟隨 EA 的交易台（ETH、SOL：USDT 永續合約多空、逐倉；BTC：現貨只做多）。"
    "每一輪：ea_signals → 依每個幣的 action 執行（OPEN 前先 ea_risk_check）→ ea_record。第一次使用先讀 ea_guide。"
    "不要向使用者要交易所金鑰；只用指令給的槓桿與逐倉；不能自己開實盤或解除 HALT；不確定就 ea_halt。"
)
S, N, B = {"type": "string"}, {"type": "number"}, {"type": "boolean"}


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


TOOLS = {
    "ea_guide": ("AI 作業手冊（AGENTS.md）：每輪流程、各 action 怎麼做、絕對不可以做的事、上線檢查表。第一次使用必讀。",
                 _obj({}), lambda: {"guide": ea_desk.guide()}),
    "ea_status": ("總覽：模式（PAPER/LIVE/HALT）、每個幣用合約或現貨 EA、三個引擎是否正常、目前部位（方向、槓桿、停損）、"
                  "已實現損益、守衛判定、使用者才能做的事。",
                  _obj({}), ea_desk.status),
    "ea_signals": ("每個幣（BTC、ETH、SOL）一條指令：action = OPEN / HOLD / MOVE_STOP / CLOSE / CLOSE_NOW / MISSED / WAIT / SHADOW / "
                   "BLOCKED / ENGINE_DOWN / ERROR，附 market（perp/spot）、side（long/short）、槓桿、數量、停損價、追價界線、原因。"
                   "每輪呼叫一次；todo 列出需要動作的幣。",
                   _obj({}), lambda: ea_desk.signals()),
    "ea_risk_check": ("開倉前風控：在交易所頁面看到價格後、按下開倉前呼叫。回傳 approved、方向 side、槓桿、最大數量 sizing.qty、"
                      "保證金、停損價與原因。approved=false 就不開倉，並 ea_record SKIP。",
                      _obj({"coin": {**S, "description": "btc / eth / sol"},
                            "price": {**N, "description": "交易所頁面上的價格；省略時用公開參考價"},
                            "qty": {**N, "description": "打算開倉的數量；省略時回傳上限"}}, ["coin"]),
                      lambda coin, price=None, qty=None: ea_desk.check(coin, price, qty)),
    "ea_record": ("記錄已發生的事：OPEN（開倉成交）、CLOSE（平倉成交，含停損被觸發）、STOP（交易所止損單已移動）、SKIP（放棄指令與原因）。"
                  "實際成交一定要記，帳本才會和交易所一致。PAPER 模式用參考價記錄、不下單。",
                  _obj({"event": {"type": "string", "enum": ["OPEN", "CLOSE", "STOP", "SKIP"]},
                        "coin": S, "position_id": {**S, "description": "照 ea_signals 給的填"},
                        "side": {"type": "string", "enum": ["long", "short"], "description": "OPEN：方向（省略時用引擎的方向）"},
                        "leverage": {**N, "description": "OPEN（合約）：實際使用的槓桿"},
                        "qty": {**N, "description": "實際成交數量（幣的數量）"},
                        "price": {**N, "description": "實際成交均價"}, "fee_usdt": N,
                        "funding_usdt": {**N, "description": "CLOSE（合約）：這筆部位期間的資金費合計，收到為正、付出為負"},
                        "stop_price": {**N, "description": "交易所止損單觸發價（OPEN、STOP）"},
                        "reason": S, "note": S}, ["event"]),
                  lambda event, **kw: ea_desk.record(event, **kw)),
    "ea_halt": ("緊急停止所有新進場（例如：交易所頁面異常、帳本與交易所對不上、不確定怎麼做）。既有部位照停損與出場指令管理。"
                "只有使用者能解除。",
                _obj({"reason": S}, ["reason"]), lambda reason: ea_desk.halt(reason, by="mcp")),
}


def _reply(id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    msg.update({"error": error} if error else {"result": result})
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _call(name: str, args: dict) -> dict:
    if name not in TOOLS:
        return {"content": [{"type": "text", "text": f"未知工具 {name}"}], "isError": True}
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):  # stdout belongs to JSON-RPC
            out = TOOLS[name][2](**(args or {}))
        err = isinstance(out, dict) and out.get("ok") is False
        text = out["guide"] if name == "ea_guide" else json.dumps(out, ensure_ascii=False, indent=2, default=str)
        return {"content": [{"type": "text", "text": text}], "isError": bool(err)}
    except Exception as e:  # noqa: BLE001 - a tool error must never kill the server
        sys.stderr.write(traceback.format_exc())
        return {"content": [{"type": "text", "text": f"{e.__class__.__name__}: {e}"}], "isError": True}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            _reply(None, error={"code": -32700, "message": "parse error"})
            continue
        id_, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if id_ is None:  # notification (e.g. notifications/initialized)
            continue
        if method == "initialize":
            want = params.get("protocolVersion")
            _reply(id_, {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": {"name": "freqai-ea-desk", "version": VERSION}, "instructions": INSTRUCTIONS})
        elif method == "ping":
            _reply(id_, {})
        elif method == "tools/list":
            _reply(id_, {"tools": [{"name": k, "description": v[0], "inputSchema": v[1]} for k, v in TOOLS.items()]})
        elif method == "tools/call":
            _reply(id_, _call(params.get("name", ""), params.get("arguments") or {}))
        elif method in ("resources/list", "prompts/list"):
            _reply(id_, {method.split("/")[0]: []})
        else:
            _reply(id_, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
