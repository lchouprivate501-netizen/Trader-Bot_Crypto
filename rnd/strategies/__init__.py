"""策略庫。新增策略：在此目錄放一個模組並加入 ALL。"""
from importlib import import_module

ALL = ["vwap_pullback", "sweep_ob", "vol_breakout"]


def get(name: str):
    if name not in ALL:
        raise KeyError(f"unknown strategy {name}; known: {ALL}")
    return import_module(f"rnd.strategies.{name}")
