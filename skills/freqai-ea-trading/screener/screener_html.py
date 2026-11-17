"""把 scan() 的結果畫成單一 HTML 頁（不需要網路、沒有外部資源）。"""
from __future__ import annotations

import html
import json

STATE = {"TREND_UP": ("單邊↑", "up"), "TREND_DOWN": ("單邊↓", "down"), "DRIFT_UP": ("偏多", "mild"),
         "DRIFT_DOWN": ("偏空", "mild"), "SQUEEZE": ("收斂", "squeeze"), "CHOP": ("來回洗", "chop")}

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e4e3de;--up:#1a7f4b;--down:#b3261e;
--chop:#8a6d00;--sq:#3559c7;--bar:#2f6fde}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;
--mute:#a09f99;--line:#33322e;--up:#5cc58c;--down:#f08a80;--chop:#e0c050;--sq:#8fa9ff;--bar:#6c9bf0}}
:root[data-theme=dark]{--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;--mute:#a09f99;--line:#33322e;--up:#5cc58c;
--down:#f08a80;--chop:#e0c050;--sq:#8fa9ff;--bar:#6c9bf0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 system-ui,-apple-system,"Noto Sans TC","PingFang TC",sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 48px}h1{font-size:20px;margin:0 0 4px}
.sub{color:var(--mute);margin-bottom:16px}.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);
border-radius:10px}table{border-collapse:collapse;width:100%;min-width:900px}th,td{padding:8px 10px;
border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th{font-weight:600;color:var(--mute);
font-size:12px;position:sticky;top:0;background:var(--card)}td.l,th.l{text-align:left}tr:last-child td{border-bottom:0}
.score{display:inline-block;min-width:34px;font-weight:700}.bar{display:inline-block;height:6px;border-radius:3px;
background:var(--bar);vertical-align:middle;margin-left:6px}.st{font-weight:600}.up{color:var(--up)}
.down{color:var(--down)}.chop{color:var(--chop)}.squeeze{color:var(--sq)}.mild{color:var(--mute)}
.warn{color:var(--chop);font-size:12px;white-space:normal;text-align:left;min-width:200px}
details{margin-top:18px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}
summary{cursor:pointer;font-weight:600}.note{color:var(--mute);font-size:13px;margin-top:14px}
"""


def _m(x):
    return f"{x / 1e9:.2f}B" if x >= 1e9 else f"{x / 1e6:.0f}M"


def render(res: dict, session: str = "") -> str:
    e = html.escape
    rows = []
    for i, r in enumerate(res["watchlist"], 1):
        m = r["metrics"]
        lab, cls = STATE.get((r.get("now") or {}).get("state"), ("", "mild"))
        imp = f"{r['impact_bps']:.1f}" if r.get("impact_bps") is not None else "–"
        fund = f"{r['funding'] * 100:.3f}%" if r.get("funding") is not None else "–"
        venues = "、".join(f"{k} {_m(v)}" for k, v in (r.get("venues") or {}).items())
        rows.append(
            f"<tr><td>{i}</td><td class=l><b>{e(r['coin'])}</b><br><small>{e(venues)}</small></td>"
            f"<td><span class=score>{r['score']:.0f}</span><span class=bar style='width:{r['score'] * 0.6:.0f}px'></span></td>"
            f"<td>{_m(r.get('qv_total_24h', m['qv_24h']))}</td><td>{m['range_pct']:.1f}%</td>"
            f"<td>{m['er4h']:.3f}</td><td>{m['chop_rate'] * 100:.0f}%</td><td>{m['vr4h']:.2f}</td>"
            f"<td>{m['rvol']:.2f}</td><td>{imp}</td><td>{fund}</td>"
            f"<td class='l st {cls}'>{lab}</td><td class=warn>{e('；'.join(r.get('warnings', [])))}</td></tr>")
    rej = "".join(f"<li><b>{e(x['coin'])}</b>：{e('；'.join(x['why']))}</li>" for x in res["rejected"][:300])
    bench = "、".join(f"{e(r['coin'])}（{r['score']:.0f}）" for r in res["bench"])
    errs = "".join(f"<p class=warn>{e(k)}：{e(v)}</p>" for k, v in res["errors"].items())
    return f"""<!doctype html><html lang=zh-Hant><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>日內篩選清單</title><style>{CSS}</style></head>
<body><main><h1>日內交易觀察清單</h1>
<div class=sub>{e(res['exchange'])}・資料到 {e(res['data_until_utc'] or '')} UTC・回看 {res['lookback_days']} 天・
宇宙 {res['universe']} 個合約 → 分析 {res['analysed']} → 合格 {res['passed']}</div>{errs}
<div class=wrap><table><thead><tr><th>#</th><th class=l>幣（各交易所 24h 額）</th><th>分數</th><th>24h 額</th><th>日振幅</th>
<th>4h ER</th><th>盤整率</th><th>VR</th><th>RVOL</th><th>滑價 bp</th><th>資金費</th><th class=l>近 4h</th><th class=l>提醒</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<p class=note>4h ER：4 小時區塊的淨移動 ÷ 價格走過的路（隨機漫步約 0.25）。盤整率：過去 14 天 ER 低於
{res['config']['chop_er']} 的 4 小時區塊比例。VR：4 小時變異數比（&gt;1 偏趨勢）。RVOL：最近 24h 成交額 ÷ 平常。
「近 4h」只描述剛剛 4 小時的盤勢，驗證顯示它不能預測下一個 4 小時。</p>
<p class=note><b>這份清單能做到與做不到的事</b>（Binance 全部 USDT 永續、保留期 2026-06 → 11 驗證）：門檻把加密貨幣隔天的盤整率
從 49% 降到 37%（排除死幣與極低流動性的幣）；前 10 名隔天每 4 小時淨移動比合格幣平均大約 29%；但前 10 名的盤整率沒有比其他
合格幣低。約 1/3 的 4 小時區段會盤整是短線加密貨幣的常態，選幣消不掉。{e(session)} 不是投資建議。</p>
<details><summary>候補（{len(res['bench'])}）</summary><p>{bench or '–'}</p></details>
<details><summary>不合格（{len(res['rejected'])}）</summary><ul>{rej}</ul></details>
<script type=application/json id=data>{e(json.dumps(res['watchlist'], ensure_ascii=False))}</script>
</main></body></html>"""
