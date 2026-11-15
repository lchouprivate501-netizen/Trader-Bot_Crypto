"""長時間工作（回測/優化）以背景程序執行，MCP 呼叫立即返回 job_id，再用 job_status 輪詢。"""
from __future__ import annotations
import json, os, subprocess, sys, time, uuid
from pathlib import Path


def _root() -> Path:
    return Path(os.environ.get("PIONEX_MACD_HOME", Path(__file__).resolve().parents[2]))


def _dir() -> Path:
    d = _root() / "state" / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def start(kind: str, args: list[str]) -> dict:
    jid = f"{kind}-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    log = _dir() / f"{jid}.log"
    env = dict(os.environ, PYTHONPATH=str(_root()), PIONEX_MACD_HOME=str(_root()))
    with open(log, "w") as fh:
        p = subprocess.Popen([sys.executable, *args], cwd=_root(), stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             env=env, start_new_session=True)
    meta = {"job_id": jid, "kind": kind, "args": args, "pid": p.pid, "log": str(log), "started": time.time()}
    (_dir() / f"{jid}.json").write_text(json.dumps(meta))
    return {**meta, "status": "running"}


def status(job_id: str, tail: int = 30) -> dict:
    f = _dir() / f"{job_id}.json"
    if not f.exists():
        return {"error": f"unknown job {job_id}", "recent": sorted(p.stem for p in _dir().glob("*.json"))[-10:]}
    meta = json.loads(f.read_text())
    alive = Path(f"/proc/{meta['pid']}").exists()
    if alive:
        try:
            alive = "Z" not in Path(f"/proc/{meta['pid']}/stat").read_text().split()[2]
        except Exception:
            pass
    lines = Path(meta["log"]).read_text(errors="replace").splitlines() if Path(meta["log"]).exists() else []
    return {**meta, "status": "running" if alive else "finished", "elapsed_s": round(time.time() - meta["started"]), "log_tail": lines[-tail:]}
