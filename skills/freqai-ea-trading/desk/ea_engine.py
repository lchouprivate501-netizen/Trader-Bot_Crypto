#!/usr/bin/env python3
"""EA 引擎：在本機背景執行三個「無金鑰」的 Freqtrade dry-run 機器人（BTC / ETH / SOL EA）與 EA 守衛。

引擎只產生訊號，不碰任何交易所帳戶：設定強制 dry_run=true、清空金鑰欄位、移除所有 FREQTRADE__* 環境變數，
REST API 只聽 127.0.0.1，帳密隨機產生並存在 $EA_HOME/api.json（權限 600）。

用法（使用者在終端機執行；只用 Python 標準函式庫）：
    python3 desk/ea_engine.py start [--coins btc,sol]   # 啟動引擎 + 守衛（已在跑的會略過）
    python3 desk/ea_engine.py status                     # 每個引擎是否在跑、API 是否回應
    python3 desk/ea_engine.py logs btc [-n 50]
    python3 desk/ea_engine.py stop

需要 Freqtrade + FreqAI 的 venv：bash skills/freqai-ea-trading/scripts/setup_env.sh（或設定 FT_VENV）。
第一次啟動 FreqAI 會下載約 180 天資料並訓練模型，需要幾分鐘到十幾分鐘，之後每 24 小時重訓。
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ea_desk  # noqa: E402

SKILL = ea_desk.SKILL
HOME = ea_desk.HOME
FT_VENV = Path(os.environ.get("FT_VENV") or Path.home() / "crypto-trading" / "venvs" / "freqai-ea")
FREQTRADE = FT_VENV / "bin" / "freqtrade"
FT_PY = FT_VENV / "bin" / "python"
GUARD_DIR = HOME / "guard"
# The EAs need 2400 1h candles at startup; Freqtrade allows at most 5 history calls per pair.
TOO_FEW_CANDLES = {"okx": "每次 100 根", "bitget": "歷史每次 200 根", "kraken": "不提供歷史 K 線"}


def _alive(pidfile: Path) -> int | None:
    try:
        pid = int(pidfile.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def _secret_write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    os.chmod(path, 0o600)


def credentials() -> dict:
    p = ea_desk.FILES["api"]
    c = ea_desk._load(p, {}) or {}
    if not (c.get("username") and c.get("password") and len(c.get("jwt_secret_key", "")) >= 32):
        c = {"username": "ea-desk", "password": secrets.token_urlsafe(24), "jwt_secret_key": secrets.token_hex(32),
             "ws_token": secrets.token_urlsafe(24)}
        _secret_write(p, c)
    return c


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("FREQTRADE__")}
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _dirs(coin: str) -> dict:
    base = HOME / "engine" / coin
    return {"base": base, "userdir": base / "user_data", "override": base / "override.json", "pid": base / "pid",
            "log": HOME / "logs" / f"{coin}-engine.log", "db": base / "dryrun.sqlite"}


def start_engine(coin: str, d: dict, cred: dict) -> str:
    cfg, p = d["coins"][coin], _dirs(coin)
    if pid := _alive(p["pid"]):
        return f"{coin}: 已在執行（pid {pid}）"
    p["userdir"].mkdir(parents=True, exist_ok=True)
    p["log"].parent.mkdir(parents=True, exist_ok=True)
    override = {
        "bot_name": f"{coin}-ea-engine", "dry_run": True, "initial_state": "running",
        "exchange": {"key": "", "secret": "", "password": "", "uid": ""},
        "telegram": {"enabled": False, "token": "", "chat_id": ""},
        "api_server": {"enabled": True, "listen_ip_address": "127.0.0.1", "listen_port": int(cfg["port"]),
                       "verbosity": "error", "enable_openapi": False, "CORS_origins": [],
                       "username": cred["username"], "password": cred["password"],
                       "jwt_secret_key": cred["jwt_secret_key"], "ws_token": cred["ws_token"]},
    }
    if d.get("engine_exchange", "binance") != "binance":
        override["exchange"]["name"] = d["engine_exchange"]
    _secret_write(p["override"], override)
    ud = SKILL / "user_data"
    cmd = [str(FREQTRADE), "trade", "-c", str(ud / "configs" / f"config_{coin}_ea.json"), "-c", str(p["override"]),
           "--userdir", str(p["userdir"]), "--strategy-path", str(ud / "strategies"),
           "--freqaimodel-path", str(ud / "freqaimodels"), "--db-url", f"sqlite:///{p['db']}", "--logfile", str(p["log"])]
    with (p["base"] / "stdout.log").open("ab") as out:
        proc = subprocess.Popen(cmd, cwd=p["base"], env=_clean_env(), stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    p["pid"].write_text(str(proc.pid))
    return f"{coin}: 啟動 {cfg['strategy']}（pid {proc.pid}，API 127.0.0.1:{cfg['port']}，日誌 {p['log']}）"


def start_guard(d: dict, cred: dict, coins: list[str]) -> str:
    pidf = GUARD_DIR / "pid"
    if pid := _alive(pidf):
        return f"guard: 已在執行（pid {pid}）"
    GUARD_DIR.mkdir(parents=True, exist_ok=True)
    env = _clean_env()
    env.update({"EA_GUARD_BOTS": ",".join(f"{c}=http://127.0.0.1:{d['coins'][c]['port']}" for c in coins),
                "EA_GUARD_API_USER": cred["username"], "EA_GUARD_API_PASSWORD": cred["password"],
                "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
    cmd = [str(FT_PY), str(SKILL / "maintenance" / "ea_guard.py"), "live", "--act", "--loop", "900",
           "--state", str(GUARD_DIR / "state.json"), "--json", str(GUARD_DIR / "latest.json"),
           "--md", str(GUARD_DIR / "latest.md")]
    with (GUARD_DIR / "guard.log").open("ab") as out:
        proc = subprocess.Popen(cmd, cwd=GUARD_DIR, env=env, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    pidf.write_text(str(proc.pid))
    return f"guard: 啟動（pid {proc.pid}；每 15 分鐘檢查，HALT 時對引擎送 /stopentry；報告 {GUARD_DIR / 'latest.md'}）"


def _stop(pidfile: Path, name: str) -> str:
    pid = _alive(pidfile)
    if not pid:
        pidfile.unlink(missing_ok=True)
        return f"{name}: 沒有在執行"
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not _alive(pidfile):
            break
        time.sleep(0.5)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
    pidfile.unlink(missing_ok=True)
    return f"{name}: 已停止（pid {pid}）"


def status(d: dict) -> dict:
    out = {"ft_venv": str(FT_VENV), "freqtrade_installed": FREQTRADE.exists(), "home": str(HOME), "engines": {}}
    for coin in d["coins"]:
        p = _dirs(coin)
        e = ea_desk.engine(coin, d, timeout=4)
        out["engines"][coin] = {"pid": _alive(p["pid"]), "api": e.get("ok"), "usable": ea_desk.usable(e),
                                "problems": e.get("problems"), "error": e.get("error"), "state": e.get("state"),
                                "last_process_age_min": e.get("last_process_age_min"),
                                "in_trade": bool(e.get("trade")), "log": str(p["log"])}
    out["guard"] = {"pid": _alive(GUARD_DIR / "pid"), **ea_desk.guard()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="EA 引擎（無金鑰 Freqtrade dry-run）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--coins", default="", help="例如 btc,sol；預設全部（ETH 只做影子紀錄，也建議一起跑）")
    s.add_argument("--no-guard", action="store_true")
    sub.add_parser("stop")
    sub.add_parser("status")
    lg = sub.add_parser("logs")
    lg.add_argument("coin")
    lg.add_argument("-n", type=int, default=40)
    a = ap.parse_args()
    d = ea_desk.config()
    coins = [c.strip().lower() for c in a.coins.split(",") if c.strip()] if a.cmd == "start" and a.coins else list(d["coins"])
    if a.cmd == "start":
        if not FREQTRADE.exists():
            print(f"找不到 {FREQTRADE}。先安裝：bash {SKILL / 'scripts' / 'setup_env.sh'}（或設定 FT_VENV）")
            return 2
        unknown = [c for c in coins if c not in d["coins"]]
        if unknown:
            print(f"未知幣種 {unknown}，可用 {list(d['coins'])}")
            return 2
        ex = str(d.get("engine_exchange", "binance")).lower()
        if ex in TOO_FEW_CANDLES:
            print(f"engine_exchange={ex} 不能用（{TOO_FEW_CANDLES[ex]}；EA 啟動需要 2400 根 1 小時 K 線）。改成 binance、bybit 或 gate。")
            return 2
        cred = credentials()
        for c in coins:
            print(start_engine(c, d, cred))
        if not a.no_guard:
            print(start_guard(d, cred, coins))
        print("第一次啟動要下載資料與訓練 FreqAI 模型（幾分鐘到十幾分鐘）；用 status 查看，所有引擎 usable=true 後 AI 才會收到指令。")
        return 0
    if a.cmd == "stop":
        print(_stop(GUARD_DIR / "pid", "guard"))
        for c in d["coins"]:
            print(_stop(_dirs(c)["pid"], c))
        print("引擎只產生訊號：停止後 AI 不會再開新倉；已在交易所的部位與停損單不受影響。")
        return 0
    if a.cmd == "status":
        print(json.dumps(status(d), ensure_ascii=False, indent=2, default=str))
        return 0
    log = _dirs(a.coin.lower())["log"]
    if not log.exists():
        print(f"沒有日誌 {log}")
        return 1
    print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-a.n:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
