"""First-run setup check: which components are present, and the exact install command for each."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from company.paths import DATA, LOGS, ROOT, STATE, universe

UV_VERSION = "0.13.8"
UV_SHA256 = "5acfd9177cfecf0bf87578f059728215ccc884388988f55f7a65041b57387d91"
NAUTILUS = "1.231.0"
OPTUNA = "5.0.0"
MCP_SDK = "2.3.0"
GRAPHIFY = "0.9.108"

CRYPTO = Path(os.environ.get("CRYPTO_TRADING_HOME") or ROOT.parent)
VENV = CRYPTO / "venvs" / "pionex-trading-skills"
GRAPHIFY_VENV = Path(os.environ.get("GRAPHIFY_VENV") or Path.home() / "trading" / "venvs" / "graphify")
PY = VENV / "bin" / "python"


def _run(cmd: list[str], timeout: int = 15) -> tuple[bool, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or p.stderr or "").strip()
        return p.returncode == 0, out
    except Exception as e:
        return False, f"{e.__class__.__name__}: {e}"


def _ver(mod: str) -> str | None:
    if not PY.exists():
        return None
    ok, out = _run([str(PY), "-c", f"import importlib.metadata as m; print(m.version('{mod}'))"])
    return out if ok else None


def _component(cid, title, installed, detail, install) -> dict:
    return {
        "id": cid,
        "title": title,
        "installed": bool(installed),
        "detail": detail,
        "install": install,
    }


def check(via_mcp: bool = False) -> dict:
    home = str(ROOT)
    crypto = str(CRYPTO)
    py = str(PY)
    gpy = str(GRAPHIFY_VENV / "bin" / "python")
    gmcp = str(GRAPHIFY_VENV / "bin" / "graphify-mcp")
    uv_tarball = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
    uv_install = (
        f"tmp=$(mktemp -d) && curl -fsSL -o \"$tmp/uv.tgz\" \"{uv_tarball}\" && "
        f"echo \"{UV_SHA256}  $tmp/uv.tgz\" | sha256sum -c - && "
        f"tar -xzf \"$tmp/uv.tgz\" -C \"$tmp\" && mkdir -p \"$HOME/.local/bin\" && "
        f"install -m 0755 \"$tmp\"/uv-x86_64-unknown-linux-gnu/uv \"$tmp\"/uv-x86_64-unknown-linux-gnu/uvx \"$HOME/.local/bin/\" && "
        f"export PATH=\"$HOME/.local/bin:$PATH\""
    )
    venv_install = (
        f"export CRYPTO_TRADING_HOME=\"{crypto}\" PIONEX_MACD_HOME=\"{home}\" && "
        f"mkdir -p \"{crypto}/venvs\" && uv venv --python 3.13 \"{VENV}\" && "
        f"VIRTUAL_ENV=\"{VENV}\" uv pip install -e \"{home}/mcp\""
    )
    data_install = f"PIONEX_MACD_HOME=\"{home}\" \"{py}\" -m rnd.data --days 365 --tf 5m"
    sched_install = f"cd \"{home}\" && bash scripts/scheduler.sh start"
    graphify_install = (
        f"mkdir -p \"{GRAPHIFY_VENV.parent}\" && "
        f"uv venv --python 3.13 \"{GRAPHIFY_VENV}\" && "
        f"VIRTUAL_ENV=\"{GRAPHIFY_VENV}\" uv pip install 'graphifyy=={GRAPHIFY}'"
    )
    mcp_install = (
        f"在 Grok Bot 新增 stdio MCP 連接器：command={py}  args=-m pionex_trading_skills  "
        f"env=PIONEX_MACD_HOME={home} CRYPTO_TRADING_HOME={crypto}。"
        f"（可選）graphify：command={gmcp}，工作目錄={home}。"
    )
    equity_install = (
        "在瀏覽器登入目前交易所（exchange_get 的 web_login_url），讀取 USDT 永續帳戶權益，"
        "然後 journal_write(\"equity\", {\"equity_usdt\": <數字>, \"source\": \"browser\"})。"
    )
    exch_install = (
        f"預設設定檔已在 {home}/company/exchanges/pionex.json；"
        f"確認 company/exchange.json 的 active 為 pionex，或呼叫 exchange_set(\"pionex\")。"
        f"要換交易所時複製 company/exchanges/_template.json，不要填入 API 金鑰。"
    )

    uv_bin = shutil.which("uv")
    uv_ok, uv_out = _run(["uv", "--version"]) if uv_bin else (False, "not on PATH")
    comps = [_component("uv", "uv (astral-sh/uv)", uv_ok, uv_out or str(uv_bin), uv_install)]

    naut, opt, mcpv = _ver("nautilus_trader"), _ver("optuna"), _ver("mcp")
    pins_ok = naut == NAUTILUS and (opt or "").startswith(OPTUNA) and mcpv == MCP_SDK
    venv_ok = PY.exists() and pins_ok
    comps.append(_component(
        "venv",
        f"Python venv + nautilus_trader {NAUTILUS} / optuna {OPTUNA} / mcp {MCP_SDK}",
        venv_ok,
        f"python={PY.exists()} nautilus_trader={naut} optuna={opt} mcp={mcpv}",
        venv_install,
    ))

    try:
        syms = list((universe() or {}).get("backtest_symbols") or [])
    except Exception:
        syms = []
    have = [s for s in syms if (DATA / f"{s}_5m.parquet").exists()]
    data_ok = bool(syms) and len(have) == len(syms)
    comps.append(_component(
        "okx_data",
        "OKX public 5m candles for the backtest universe",
        data_ok,
        f"{len(have)}/{len(syms)} symbols have {DATA}/*_5m.parquet" if syms else "universe.json missing",
        data_install,
    ))

    pid_ok, pid_detail = False, "no pidfile"
    try:
        pid = int((LOGS / "scheduler.pid").read_text().strip())
        pid_ok = Path(f"/proc/{pid}").exists()
        pid_detail = f"pid {pid} {'alive' if pid_ok else 'dead'}"
    except Exception as e:
        pid_detail = f"{e.__class__.__name__}"
    comps.append(_component("scheduler", "5m scheduler", pid_ok, pid_detail, sched_install))

    gver = None
    if (GRAPHIFY_VENV / "bin" / "python").exists():
        ok, out = _run([gpy, "-c", "import importlib.metadata as m; print(m.version('graphifyy'))"])
        gver = out if ok else None
    g_ok = gver == GRAPHIFY and Path(gmcp).exists()
    comps.append(_component(
        "graphify",
        f"graphify (Graphify-Labs/graphify) {GRAPHIFY} in {GRAPHIFY_VENV}",
        g_ok,
        f"version={gver} mcp={gmcp}",
        graphify_install,
    ))

    pkg_ok, pkg_out = (False, "venv python missing")
    if PY.exists():
        pkg_ok, pkg_out = _run([str(PY), "-c", "import pionex_trading_skills; print(pionex_trading_skills.__version__)"])
    mcp_ok = bool(via_mcp) or pkg_ok
    comps.append(_component(
        "mcp_connector",
        "MCP package pionex_trading_skills importable / connector reachable",
        mcp_ok,
        f"via_mcp={via_mcp}; import={pkg_out}",
        mcp_install,
    ))

    exch_ok, exch_detail = False, "not set"
    try:
        from company.exchange import profile
        p = profile()
        exch_ok, exch_detail = True, f"active={p['name']} web={p['web_login_url']} taker={p['taker_fee']}"
    except Exception as e:
        exch_detail = f"{e.__class__.__name__}: {e}"
    comps.append(_component("exchange", "Active exchange profile", exch_ok, exch_detail, exch_install))

    eq_ok, eq_detail = False, "state/equity.jsonl missing"
    eqf = STATE / "equity.jsonl"
    if eqf.exists():
        lines = [l for l in eqf.read_text(encoding="utf-8").splitlines() if l.strip()]
        last = lines[-1] if lines else ""
        try:
            import json
            rec = json.loads(last) if last else {}
            eq_ok = "equity_usdt" in rec
            eq_detail = f"records={len(lines)} last={rec.get('equity_usdt')} at {rec.get('at')}"
        except Exception as e:
            eq_detail = f"{e.__class__.__name__}: {e}"
    comps.append(_component("equity", "Account equity recorded", eq_ok, eq_detail, equity_install))

    missing = [c["id"] for c in comps if not c["installed"]]
    return {
        "ok": not missing,
        "ready": not missing,
        "missing": missing,
        "components": comps,
        "first_run": (
            "1) 呼叫 setup_check；2) 依每個 installed=false 的 install 欄位安裝；"
            "3) 呼叫 exchange_get，詢問使用者是否沿用預設 Pionex 或新增/更換交易所（瀏覽器登入，不要 API 金鑰）；"
            "4) 權益寫入後即可開始 PAPER 循環。"
        ),
        "or": f"bash {home}/bootstrap.sh  # idempotent installer for uv, venv, data, graphify, smoke, scheduler",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(check(), ensure_ascii=False, indent=2))
