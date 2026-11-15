"""輕量排程器（使用者層級，不需 root/cron）：每根 5m K 收盤後 +20 秒跑一輪執行週期，並寫心跳。"""
from __future__ import annotations
import json, os, signal, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PIONEX_MACD_HOME", str(ROOT))
from company.paths import LOGS, write_json  # noqa: E402
from exec import cycle  # noqa: E402

OFFSET = 20
CYCLE_DEADLINE = 240  # 一輪最多 4 分鐘，卡住的網路呼叫會被中斷，不會拖到下一輪


def _deadline(signum, frame):
    raise TimeoutError(f"cycle exceeded {CYCLE_DEADLINE}s")


def next_run(now: float) -> float:
    return (int(now) // 300 + 1) * 300 + OFFSET


def main():
    once = "--once" in sys.argv
    while True:
        if not once:
            target = next_run(time.time())
            while time.time() < target:  # short naps vs wall clock (robust to VM pauses / clock jumps)
                time.sleep(min(5.0, max(0.0, target - time.time())))
        t = time.time()
        signal.signal(signal.SIGALRM, _deadline)
        signal.alarm(CYCLE_DEADLINE)
        try:
            res = cycle.run()
            status = "ok" if not any("error" in v for v in res["steps"].values()) else "partial"
        except Exception:
            res, status = {"trace": traceback.format_exc()[-1500:]}, "error"
        finally:
            signal.alarm(0)
        hb = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "status": status, "secs": round(time.time() - t, 1),
              "next_run_utc": datetime.fromtimestamp(next_run(time.time()), timezone.utc).isoformat(), "pid": os.getpid()}
        write_json(LOGS / "scheduler_heartbeat.json", hb)
        print(json.dumps({**hb, "steps": res.get("steps", res)}, ensure_ascii=False, default=str), flush=True)
        if once:
            break


if __name__ == "__main__":
    main()
