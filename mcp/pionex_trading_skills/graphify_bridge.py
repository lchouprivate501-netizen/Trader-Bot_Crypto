"""Passthrough to graphify's library against a configurable graph.json."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pionex_trading_skills.paths import graph_path


def _missing(path: Path) -> str:
    return (
        f"graphify 圖檔不存在或尚未建置：{path}\n"
        "請在知識目錄執行 `graphify update .`（無需 LLM 金鑰，僅重建程式圖）。"
    )


def _load(path: Path | None = None):
    path = Path(path or graph_path())
    if not path.exists():
        raise FileNotFoundError(_missing(path))
    from graphify.serve import _communities_from_graph, _load_graph

    G = _load_graph(str(path))
    communities = _communities_from_graph(G)
    return path, G, communities


def query_graph(question: str, mode: str = "bfs", depth: int = 3, token_budget: int = 2000) -> str:
    try:
        path, G, _communities = _load()
    except FileNotFoundError as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001
        return f"graphify query_graph 失敗：{exc}"
    try:
        from graphify.serve import _query_graph_text

        return _query_graph_text(G, question, mode=mode, depth=depth, token_budget=token_budget)
    except TypeError:
        # Signature may differ across graphify versions; try a looser call.
        try:
            from graphify.serve import _query_graph_text

            return _query_graph_text(G, question)
        except Exception as exc:  # noqa: BLE001
            return f"graphify query_graph 呼叫失敗：{exc}"
    except Exception as exc:  # noqa: BLE001
        return f"graphify query_graph 失敗：{exc}"


def get_node(label: str) -> str:
    try:
        path, G, _ = _load()
    except FileNotFoundError as exc:
        return str(exc)
    try:
        from graphify.serve import _resolve_single_node, sanitize_label
        import json
        from graphify import serve as gs

        nid, err = _resolve_single_node(G, label)
        if err:
            return err
        d = G.nodes[nid]
        attrs = d.get("attributes")
        extra = ""
        if isinstance(attrs, dict) and attrs:
            extra = "\n  Attributes: " + json.dumps(attrs, sort_keys=True)[:1000]
        return (
            f"Node: {sanitize_label(d.get('label', nid))}\n"
            f"  ID: {sanitize_label(nid)}\n"
            f"  Source: {d.get('source_file', '')}\n"
            f"  Type: {d.get('file_type', '')}\n"
            f"  Degree: {G.degree(nid)}"
            f"{extra}"
        )
    except Exception as exc:  # noqa: BLE001
        return f"graphify get_node 失敗：{exc}"


def get_neighbors(label: str, relation_filter: str = "", token_budget: int = 2000) -> str:
    try:
        _path, G, _ = _load()
    except FileNotFoundError as exc:
        return str(exc)
    try:
        from graphify.serve import _resolve_single_node, _neighbor_lines, _cut_lines_to_budget, sanitize_label

        nid, err = _resolve_single_node(G, label)
        if err:
            return err
        lines = [f"Neighbors of {sanitize_label(G.nodes[nid].get('label', nid))}:"]
        lines.extend(_neighbor_lines(G, nid, (relation_filter or "").lower()))
        return _cut_lines_to_budget(lines, int(token_budget), "Narrow with relation_filter")
    except Exception as exc:  # noqa: BLE001
        return f"graphify get_neighbors 失敗：{exc}"


def graph_stats() -> str:
    try:
        path, G, communities = _load()
    except FileNotFoundError as exc:
        return str(exc)
    try:
        confs = [d.get("confidence", "EXTRACTED") for _, _, d in G.edges(data=True)]
        total = len(confs) or 1
        return (
            f"Graph: {path}\n"
            f"Nodes: {G.number_of_nodes()}\n"
            f"Edges: {G.number_of_edges()}\n"
            f"Communities: {len(communities)}\n"
            f"EXTRACTED: {round(confs.count('EXTRACTED') / total * 100)}%\n"
            f"INFERRED: {round(confs.count('INFERRED') / total * 100)}%\n"
            f"AMBIGUOUS: {round(confs.count('AMBIGUOUS') / total * 100)}%\n"
        )
    except Exception as exc:  # noqa: BLE001
        return f"graphify graph_stats 失敗：{exc}"
