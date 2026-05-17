"""
Phase C-2: エンティティグラフ構築

candidates.tsv と property_paths.tsv からエンティティ中心のグラフ JSON を生成し、
TSV を修正すべき問題点をレポートする。

ノード:
  - type=wikidata : QID エンティティ
  - type=local    : NONE（独自アイテム）

エッジ種別:
  - co_mention        : 同一ラベル内で共起
  - wikidata_property : Wikidata P31/P279/P361/P527 等

入力:
    work/kouchou-ai/el/candidates.json
    work/kouchou-ai/el/property_paths.tsv
    work/kouchou-ai/el/entity_props_cache.json

出力:
    work/kouchou-ai/el/entity_graph.json

使い方:
    python scripts/build_entity_graph.py
"""

import csv
import json
import argparse
from collections import defaultdict
from itertools import combinations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from settings import DEFAULT_DATA_DIR  # noqa: E402


def node_id(qid: str, mention: str) -> str:
    """NONE の場合は LOCAL:mention をノード ID にする"""
    return qid  # T-IDs are already unique stable identifiers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--data-json", type=Path, default=None, help="Input data.json path")
    parser.add_argument("--property-paths", type=Path, default=None, help="Input property_paths.tsv path")
    parser.add_argument("--cache-json", type=Path, default=None, help="Input entity_props_cache.json path")
    parser.add_argument("--output-json", type=Path, default=None, help="Output entity_graph.json path")
    cli = parser.parse_args()
    cli.data_dir = cli.data_dir or DEFAULT_DATA_DIR
    cli.data_json = cli.data_json or cli.data_dir / "data.json"
    cli.property_paths = cli.property_paths or cli.data_dir / "property_paths.tsv"
    cli.cache_json = cli.cache_json or cli.data_dir / "entity_props_cache.json"
    cli.output_json = cli.output_json or cli.data_dir / "entity_graph.json"

    data = json.loads(cli.data_json.read_text())
    entities = data.get("entities", {})
    item_text = {item["id"]: item["label"] for item in data.get("items", [])}

    # ── data.json → ノード + item→entity マップ ──────────────────────────
    node_data: dict[str, dict] = {}
    item_entities: dict[str, list[str]] = defaultdict(list)
    item_entity_surfaces: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    issues: list[str] = []

    for row in data.get("mentions", []):
        entity_id = row.get("entity_id", "").strip()
        mention = row.get("mention", "").strip()
        item_id = row["item_id"]
        nid = node_id(entity_id, mention)
        ent = entities.get(entity_id, {})

        if nid not in node_data:
            node_data[nid] = {
                "id": nid,
                "type": "wikidata" if entity_id.startswith("Q") else "local",
                "qid": entity_id if entity_id.startswith("Q") else None,
                "controlled_label": ent.get("label", mention),
                "wikidata_desc": ent.get("desc", ""),
                "confidence": row.get("confidence", ""),
                "item_ids": [],
                "surfaces": [],
            }

        nd = node_data[nid]
        if item_id not in nd["item_ids"]:
            nd["item_ids"].append(item_id)
        if mention not in nd["surfaces"]:
            nd["surfaces"].append(mention)

        item_entity_surfaces[item_id][nid].append(mention)
        if nid not in item_entities[item_id]:
            item_entities[item_id].append(nid)

    # ── 問題1: 同一 item 内で同一 QID に複数 surface ────────────────────
    for lid, nid_list in item_entities.items():
        for nid in nid_list:
            surfs = item_entity_surfaces[lid][nid]
            if len(surfs) > 1:
                issues.append(
                    f"[DUPLICATE_QID] {lid}: ノード {nid} に対して"
                    f" {len(surfs)} surface → {surfs}"
                    f"  item: 「{item_text.get(lid,'')[:40]}」"
                )

    # ── co_mention エッジ構築 ────────────────────────────────────────────
    co_edges: dict[tuple, dict] = {}
    for lid, nid_list in item_entities.items():
        unique_nids = list(dict.fromkeys(nid_list))  # 順序保持重複除去
        for a, b in combinations(unique_nids, 2):
            key = (min(a, b), max(a, b))
            if key not in co_edges:
                co_edges[key] = {"label_ids": [], "weight": 0}
            co_edges[key]["label_ids"].append(lid)
            co_edges[key]["weight"] += 1

    # ── wikidata_property エッジ構築 ─────────────────────────────────────
    wp_edges: list[dict] = []
    if cli.property_paths.exists():
        with open(cli.property_paths) as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row["relation_type"] == "none":
                    continue
                nid_a = node_id(row["qid_a"], row["surface_a"])
                nid_b = node_id(row["qid_b"], row["surface_b"])
                if nid_a == nid_b:
                    continue  # 同一QIDの自己ループをスキップ
                wp_edges.append({
                    "source":         nid_a,
                    "target":         nid_b,
                    "type":           "wikidata_property",
                    "relation_type":  row["relation_type"],
                    "property_id":    row["property_id"],
                    "property_label": row["property_label"],
                    "direction":      row["direction"],
                    "via_qid":        row["via_qid"],
                    "via_label":      row["via_label"],
                    "item_id":        row["item_id"],
                })

    # ── co_mention エッジをリスト化 ───────────────────────────────────────
    co_edge_list = [
        {
            "source":    a,
            "target":    b,
            "type":      "co_mention",
            "weight":    e["weight"],
            "item_ids":  e["label_ids"],
        }
        for (a, b), e in co_edges.items()
    ]

    # ── エンティティキャッシュから wikidata_desc 補完 ────────────────────
    cache = {}
    if cli.cache_json.exists():
        cache = json.loads(cli.cache_json.read_text())
    for nid, nd in node_data.items():
        if nd["qid"] and nd["qid"] in cache:
            if not nd["controlled_label"]:
                nd["controlled_label"] = cache[nd["qid"]].get("label", "")
            if not nd["wikidata_desc"]:
                nd["wikidata_desc"] = cache[nd["qid"]].get("desc", "")

    # ── 問題2: 孤立ノード（co_mention エッジなし）───────────────────────
    connected = set()
    for e in co_edge_list:
        connected.add(e["source"])
        connected.add(e["target"])
    for nid in node_data:
        if nid not in connected:
            nd = node_data[nid]
            issues.append(
                f"[ISOLATED] {nid} ({nd['controlled_label']}) —"
                f" item {nd['item_ids']} にのみ出現、他エンティティとの共起なし"
            )

    # ── 問題3: hub エンティティ（3ラベル以上） ──────────────────────────
    for nid, nd in node_data.items():
        if len(nd["item_ids"]) >= 3:
            issues.append(
                f"[HUB] {nid} ({nd['controlled_label']}) —"
                f" {len(nd['item_ids'])} item に出現: {nd['item_ids']}"
            )

    # ── グラフ JSON 組み立て ─────────────────────────────────────────────
    nodes = list(node_data.values())
    edges = co_edge_list + wp_edges

    graph = {
        "meta": {
            "node_count":          len(nodes),
            "wikidata_node_count": sum(1 for n in nodes if n["type"] == "wikidata"),
            "local_node_count":    sum(1 for n in nodes if n["type"] == "local"),
            "co_mention_edges":    len(co_edge_list),
            "wikidata_edges":      len(wp_edges),
        },
        "nodes": nodes,
        "edges": edges,
    }

    cli.output_json.parent.mkdir(parents=True, exist_ok=True)
    cli.output_json.write_text(json.dumps(graph, ensure_ascii=False, indent=2))

    # ── レポート出力 ─────────────────────────────────────────────────────
    m = graph["meta"]
    print("=" * 60)
    print("エンティティグラフ構造レポート")
    print("=" * 60)
    print(f"ノード数:          {m['node_count']}"
          f"  (Wikidata: {m['wikidata_node_count']}, LOCAL: {m['local_node_count']})")
    print(f"co_mention エッジ: {m['co_mention_edges']}")
    print(f"wikidata エッジ:   {m['wikidata_edges']}")
    print()

    # 問題をカテゴリ別に表示
    for category in ["DUPLICATE_QID", "ISOLATED", "HUB"]:
        cat_issues = [i for i in issues if i.startswith(f"[{category}]")]
        if cat_issues:
            labels_map = {
                "DUPLICATE_QID": "同一ラベル内の QID 重複（TSV修正候補）",
                "ISOLATED":      "孤立ノード（他エンティティと共起なし）",
                "HUB":           "Hub エンティティ（3ラベル以上に出現）",
            }
            print(f"▼ {labels_map[category]}  ({len(cat_issues)}件)")
            for iss in cat_issues:
                print(f"  {iss}")
            print()

    print(f"→ {cli.output_json}")


if __name__ == "__main__":
    main()
