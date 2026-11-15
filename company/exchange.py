"""Active exchange profile. Orders are always placed in the browser; this module never stores API keys."""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

from company.paths import COMPANY, load_json, write_json

EXCHANGES = COMPANY / "exchanges"
POINTER = COMPANY / "exchange.json"
TEMPLATE = "_template"
SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
# Fail-closed: any field name that looks like a credential is rejected.
SECRET_KEY = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?key|private[_-]?key"
    r"|passphrase|(^|_)password($|_|(?=[A-Z]))|(^|_)passwd($|_)"
    r"|(^|_)secret($|_|(?=[A-Z\-]))|(^|_)token($|_|(?=[A-Z\-]))|bearer)"
)
REQUIRED = (
    "name",
    "web_login_url",
    "contract_naming",
    "whitelist",
    "maker_fee",
    "taker_fee",
    "supports_isolated",
    "supports_usdt_margined_perps",
    "max_leverage",
)


def _secret_keys(obj, prefix="") -> list[str]:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if SECRET_KEY.search(str(k)):
                found.append(path)
            found.extend(_secret_keys(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found.extend(_secret_keys(v, f"{prefix}[{i}]"))
    return found


def _norm_symbol(s: str) -> str:
    s = str(s).upper().replace("-", "").replace("/", "").strip()
    if s.endswith("USDT") and len(s) > 4:
        s = s[:-4]
    return s


def available() -> list[str]:
    if not EXCHANGES.is_dir():
        return []
    names = []
    for p in sorted(EXCHANGES.glob("*.json")):
        if p.stem.startswith("_"):
            continue
        names.append(p.stem)
    return names


def active_name() -> str | None:
    ptr = load_json(POINTER, {}) or {}
    name = (ptr.get("active") or "").strip()
    return name or None


def path_for(name: str) -> Path:
    return EXCHANGES / f"{name}.json"


def load_profile(name: str) -> dict:
    data = load_json(path_for(name))
    if not data:
        raise FileNotFoundError(f"exchange profile not found: {name}")
    return data


def validate(raw: dict) -> tuple[list[str], dict]:
    """Return (errors, cleaned). cleaned is usable only when errors is empty."""
    errs = []
    if not isinstance(raw, dict):
        return (["profile must be a JSON object"], {})
    secrets = _secret_keys(raw)
    if secrets:
        return ([f"rejected secret field(s): {', '.join(secrets)} — never store API keys"], {})
    missing = [k for k in REQUIRED if k not in raw]
    if missing:
        errs.append(f"missing fields: {', '.join(missing)}")
    name = str(raw.get("name") or "").strip().lower()
    if not SLUG.fullmatch(name) or name.startswith("_") or name == TEMPLATE:
        errs.append("name must be a slug like 'pionex' or 'binance' (lowercase, no leading _)")
    url = str(raw.get("web_login_url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        errs.append("web_login_url must be an https URL with no username or password")
    naming = str(raw.get("contract_naming") or "").strip()
    if not naming:
        errs.append("contract_naming is required (e.g. '{base}USDT perp')")
    wl_in = raw.get("whitelist")
    if not isinstance(wl_in, list) or not wl_in:
        errs.append("whitelist must be a non-empty list of base symbols")
        wl = []
    else:
        wl, bad = [], []
        for x in wl_in:
            s = _norm_symbol(x)
            if not re.fullmatch(r"[A-Z0-9]{2,20}", s):
                bad.append(str(x))
            elif s not in wl:
                wl.append(s)
        if bad:
            errs.append(f"invalid whitelist symbols: {bad}")
        if not wl:
            errs.append("whitelist has no valid symbols")
    try:
        maker = float(raw["maker_fee"])
        taker = float(raw["taker_fee"])
        if maker < 0 or taker < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        maker = taker = None
        errs.append("maker_fee and taker_fee must be numbers ≥ 0 (e.g. 0.0002 / 0.0005)")
    if raw.get("supports_isolated") is not True:
        errs.append("supports_isolated must be true (company trades isolated margin only)")
    if raw.get("supports_usdt_margined_perps") is not True:
        errs.append("supports_usdt_margined_perps must be true")
    try:
        max_lev = float(raw["max_leverage"])
        if max_lev < 2:
            errs.append(f"max_leverage must be ≥ 2 (got {max_lev})")
    except (KeyError, TypeError, ValueError):
        max_lev = None
        errs.append("max_leverage must be a number ≥ 2")
    if errs:
        return (errs, {})
    cleaned = {
        "name": name,
        "display_name": str(raw.get("display_name") or name).strip() or name,
        "web_login_url": url,
        "contract_naming": naming,
        "whitelist": wl,
        "maker_fee": maker,
        "taker_fee": taker,
        "supports_isolated": True,
        "supports_usdt_margined_perps": True,
        "max_leverage": int(max_lev) if float(max_lev) == int(max_lev) else max_lev,
    }
    if raw.get("notes"):
        cleaned["notes"] = str(raw["notes"])
    return ([], cleaned)


def profile(name: str | None = None) -> dict:
    n = name or active_name()
    if not n:
        raise FileNotFoundError("no active exchange profile (company/exchange.json)")
    errs, cleaned = validate(load_profile(n))
    if errs:
        raise ValueError(f"invalid exchange profile {n}: {'; '.join(errs)}")
    return cleaned


def whitelist() -> list[str]:
    return list(profile()["whitelist"])


def taker_fee() -> float:
    return float(profile()["taker_fee"])


def maker_fee() -> float:
    return float(profile()["maker_fee"])


def contract_symbol(base: str) -> str:
    p = profile()
    return str(p["contract_naming"]).replace("{base}", _norm_symbol(base))


def snapshot() -> dict:
    """Safe public view of the active profile plus available names. Never includes keys."""
    names = available()
    try:
        p = profile()
        return {
            "ok": True,
            "active": p["name"],
            "profile": p,
            "available": names,
            "default": "pionex",
            "orders": "browser only — never API keys",
            "prompt": "首次執行請確認是否沿用預設 Pionex，或要用 exchange_set 新增/更換交易所（瀏覽器登入，不要提供 API 金鑰）。",
        }
    except Exception as e:
        return {
            "ok": False,
            "active": active_name(),
            "available": names,
            "error": f"{e.__class__.__name__}: {e}",
            "prompt": "請先設定交易所：複製 company/exchanges/_template.json 或呼叫 exchange_set，預設可用 pionex。",
        }


def _live_open_positions() -> tuple[str, list]:
    from exec import ledger, mode
    return mode.get(), ledger.open_positions()


def _refresh_scan() -> dict:
    try:
        from exec import scanner
        out = scanner.scan()
        return {"ok": True, "n": len(out.get("universe") or [])}
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}


def set_profile(spec: str) -> dict:
    """Activate an existing profile name, or write+activate a JSON object / JSON string.

    Refused when mode is LIVE and there are open positions. Never accepts API keys.
    """
    if spec is None or str(spec).strip() == "":
        return {"ok": False, "error": "pass an existing profile name or a JSON object"}
    text = str(spec).strip()
    raw = None
    if text[:1] in "{[":
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"invalid JSON: {e}"}
    elif SLUG.fullmatch(text.lower()) and text.lower() not in (TEMPLATE,) and not text.startswith("_"):
        name = text.lower()
        if not path_for(name).exists():
            return {"ok": False, "error": f"unknown profile '{name}'; available: {available()}"}
        current = active_name()
        if current == name:
            p = profile(name)
            return {"ok": True, "unchanged": True, "active": name, "profile": p, "available": available()}
        mode, opens = _live_open_positions()
        if mode == "LIVE" and opens:
            return {
                "ok": False,
                "error": "拒絕：LIVE 模式下仍有未平倉位，不能更換交易所（fail-closed）",
                "mode": mode,
                "open_positions": len(opens),
            }
        write_json(POINTER, {"active": name})
        p = profile(name)
        scan = _refresh_scan()
        return {"ok": True, "active": name, "profile": p, "available": available(), "scan": scan}

    if raw is None:
        return {"ok": False, "error": "pass an existing profile name or a JSON object"}
    errs, cleaned = validate(raw)
    if errs:
        return {"ok": False, "error": "; ".join(errs)}
    name = cleaned["name"]
    current = active_name()
    changing = current != name or (path_for(name).exists() and load_json(path_for(name)) != cleaned)
    if changing:
        mode, opens = _live_open_positions()
        if mode == "LIVE" and opens:
            return {
                "ok": False,
                "error": "拒絕：LIVE 模式下仍有未平倉位，不能更換或改寫啟用中的交易所（fail-closed）",
                "mode": mode,
                "open_positions": len(opens),
            }
    write_json(path_for(name), cleaned)
    write_json(POINTER, {"active": name})
    scan = _refresh_scan()
    return {"ok": True, "active": name, "profile": cleaned, "available": available(), "scan": scan}
