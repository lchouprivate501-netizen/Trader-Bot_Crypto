"""研發部「優化」角色：optuna 只在前 70%（樣本內）上跑，少量參數，試驗數上限 300。
目標＝樣本內扣費後總 R（用 rnd/fastsim.py），交易太少時懲罰。"""
from __future__ import annotations
import optuna
import pandas as pd
from rnd import fastsim

optuna.logging.set_verbosity(optuna.logging.WARNING)


def objective_value(mod, frames: dict, params: dict, fee: float, min_trades: int) -> tuple[float, int, float]:
    trs = []
    for sym, df in frames.items():
        sig = mod.signals(df, params)
        trs.append(fastsim.simulate(df, sig, int(params.get("max_hold", mod.DEFAULTS.get("max_hold", 36))), fee))
    tr = pd.concat(trs) if trs else pd.DataFrame(columns=["r_net"])
    n = len(tr)
    total_r = float(tr.r_net.sum()) if n else -1e9
    gp, gl = tr.r_net[tr.r_net > 0].sum(), -tr.r_net[tr.r_net < 0].sum()
    pf = float(gp / gl) if gl > 0 else 0.0
    score = total_r if n >= min_trades else total_r - (min_trades - n)
    return score, n, pf


def optimize(mod, frames_is: dict, fee: float, trials: int, min_trades: int, seed: int = 42) -> dict:
    trials = min(int(trials), 300)

    def obj(trial):
        p = dict(mod.DEFAULTS)
        for k, (lo, hi, kind) in mod.SPACE.items():
            p[k] = trial.suggest_int(k, lo, hi) if kind == "int" else trial.suggest_float(k, lo, hi)
        score, n, pf = objective_value(mod, frames_is, p, fee, min_trades)
        trial.set_user_attr("trades", n); trial.set_user_attr("pf_r", pf)
        return score

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    study.enqueue_trial({k: mod.DEFAULTS[k] for k in mod.SPACE})
    study.optimize(obj, n_trials=trials)
    best = dict(mod.DEFAULTS); best.update(study.best_params)
    return {"params": best, "trials": len(study.trials), "is_score_R": round(study.best_value, 2),
            "is_trades_fastsim": study.best_trial.user_attrs["trades"], "is_pf_R_fastsim": round(study.best_trial.user_attrs["pf_r"], 3)}
