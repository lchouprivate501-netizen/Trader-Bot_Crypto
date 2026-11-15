"""策略庫。新增策略：在此目錄放一個模組（實作 base 介面）即可，自動被發現，不需登記。"""
from importlib import import_module
from pathlib import Path

_DIR = Path(__file__).parent
_SKIP = {"__init__", "base"}


def names() -> list[str]:
    """每次呼叫都重新掃描目錄，長駐行程（MCP、排程器）不必重啟就看得到新策略。"""
    return sorted(p.stem for p in _DIR.glob("*.py") if p.stem not in _SKIP and not p.stem.startswith("_"))


def __getattr__(attr):  # `from rnd.strategies import ALL` 每次都拿到最新清單
    if attr == "ALL":
        return names()
    raise AttributeError(attr)


def get(name: str):
    known = names()
    if name not in known:
        raise KeyError(f"unknown strategy {name}; known: {known}")
    return import_module(f"rnd.strategies.{name}")
