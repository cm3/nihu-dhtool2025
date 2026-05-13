"""
Phase D-2: ペアレベルのエンティティ関係抽出

entity_opinions.json と entity_graph.json からスコアの高いペアを選び、
両エンティティが共起するコメントを使って LLM で詳細な関係を抽出する。

スコア計算:
    score = opinion_count + (3 if bidirectional else 0) + co_mention_weight × 2
    閾値 >= 4 のペアを対象

ただし、閾値採用後にグラフが分断される場合は、
relation graph 上の高スコア辺を追加して全ノードが 1 つの連結成分になるまで救済する。
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_OPINIONS_JSON = ROOT / "data/entity_opinions.json"
DEFAULT_GRAPH_JSON = ROOT / "data/entity_graph.json"
DEFAULT_DATA_JSON = ROOT / "data/data.json"
DEFAULT_INDEX_CSV = ROOT / "data/cluster_comment_index.csv"
DEFAULT_COMMENT_TEXTS_JSON = ROOT / "data/comment_texts.json"
DEFAULT_CLUSTERS_CSV = ROOT / "data/argument_microclusters_t0.7.csv"
DEFAULT_OUTPUT_JSON = ROOT / "data/pair_relations.json"

SYSTEM_PROMPT = """\
あなたはエネルギー政策のパブリックコメントを分析するアシスタントです。
2つのエンティティについて、提示されたコメント群を分析し、
両者の関係を JSON で回答してください。

コメントに基づいて2つのエンティティがどのように語られているか、
具体的な内容を 3〜5 文で説明してください。
証拠はコメントからの引用フレーズ（20字以上）を1つ挙げてください。

出力は以下の JSON のみ（余分なテキスト不要）:
{
  "description": "AとBの関係を3〜5文で具体的に説明",
  "evidence": "コメントからの引用フレーズ（20字以上）"
}

注意:
- description は日本語で、コメントの内容を根拠に具体的に書くこと
- description では "A" "B" "両者" などの記号的な呼び方を使わず、
  必ず実際のエンティティ名をそのまま書くこと
- たとえば「AはBについて...」ではなく、
  「原子力安全は原子力発電所について...」のように書くこと
- 関係が見当たらない場合は description を空文字にする
"""


class UnionFind:
    def __init__(self, nodes: list[str]) -> None:
        self.parent = {node: node for node in nodes}
        self.rank = {node: 0 for node in nodes}

    def find(self, x: str) -> str:
        parent = self.parent[x]
        if parent != x:
            self.parent[x] = self.find(parent)
        return self.parent[x]

    def union(self, a: str, b: str) -> bool:
        ra = self.find(a)
        rb = self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        return True

    def component_count(self) -> int:
        return len({self.find(node) for node in self.parent})


def build_user_message(label_a: str, desc_a: str,
                       label_b: str, desc_b: str,
                       comments: list[str]) -> str:
    desc_a_part = f"（{desc_a}）" if desc_a else ""
    desc_b_part = f"（{desc_b}）" if desc_b else ""
    comments_text = "\n\n".join(f"[{i+1}] {c}" for i, c in enumerate(comments))
    return (
        f"【エンティティ1】{label_a}{desc_a_part}\n"
        f"【エンティティ2】{label_b}{desc_b_part}\n\n"
        f"【関連コメント（{len(comments)}件）】\n{comments_text}"
    )


def call_llm(client: OpenAI, label_a: str, desc_a: str,
             label_b: str, desc_b: str,
             comments: list[str],
             model: str, retries: int = 3) -> dict:
    msg = build_user_message(label_a, desc_a, label_b, desc_b, comments)
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": msg},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [LLM ERROR] {e}", file=sys.stderr)
                return {}
    return {}


def load_cluster_comments(index_csv: Path, comment_texts_json: Path, clusters_csv: Path) -> tuple[dict[str, str], dict[str, list[dict]]]:
    with open(index_csv) as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return {}, {}

    fieldnames = set(rows[0].keys())

    centroid_ids: set[str] = set()
    if "is_centroid" in fieldnames:
        centroid_ids = {row["arg_id"] for row in rows if row.get("is_centroid") == "true"}
    else:
        with open(clusters_csv) as f:
            for row in csv.DictReader(f):
                if row["is_centroid"] == "true":
                    centroid_ids.add(row["arg_id"])

    comment_body: dict[str, str] = {}
    if comment_texts_json.exists():
        comment_body = json.loads(comment_texts_json.read_text())

    cluster_comments: dict[str, list[dict]] = defaultdict(list)
    seen_in_cluster: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        cid = row["comment_id"]
        cluster = row["cluster_l2"]
        if cid not in seen_in_cluster[cluster]:
            seen_in_cluster[cluster].add(cid)
            cluster_comments[cluster].append({
                "comment_id": cid,
                "centroid": row["arg_id"] in centroid_ids,
            })

    return comment_body, cluster_comments


def augment_pairs_for_connectivity(entities: list[dict], candidate_pairs: list[dict], score_threshold: int) -> list[dict]:
    entity_ids = [e["id"] for e in entities]
    uf = UnionFind(entity_ids)

    selected: list[dict] = []
    rescue_candidates: list[dict] = []

    for pair in candidate_pairs:
        if pair["score"] >= score_threshold:
            pair["selection_reason"] = "threshold"
            selected.append(pair)
            uf.union(pair["id_a"], pair["id_b"])
        elif pair["score"] > 0:
            rescue_candidates.append(pair)

    if uf.component_count() <= 1:
        return selected

    added = 0
    for pair in rescue_candidates:
        if uf.union(pair["id_a"], pair["id_b"]):
            pair["selection_reason"] = "connectivity_rescue"
            selected.append(pair)
            added += 1
            if uf.component_count() <= 1:
                break

    print(f"連結性救済: +{added} ペア")
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--opinions-json", type=Path, default=DEFAULT_OPINIONS_JSON)
    parser.add_argument("--graph-json", type=Path, default=DEFAULT_GRAPH_JSON)
    parser.add_argument("--data-json", type=Path, default=DEFAULT_DATA_JSON)
    parser.add_argument("--index-csv", type=Path, default=DEFAULT_INDEX_CSV)
    parser.add_argument("--comment-texts-json", type=Path, default=DEFAULT_COMMENT_TEXTS_JSON)
    parser.add_argument("--clusters-csv", type=Path, default=DEFAULT_CLUSTERS_CSV)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--model",           default="gpt-5.4-mini")
    parser.add_argument("--score-threshold", type=int, default=4)
    parser.add_argument("--max-comments",    type=int, default=30,
                        help="ペアあたりの最大コメント数")
    parser.add_argument("--resume",          action="store_true")
    parser.add_argument("--seed",            type=int, default=42)
    cli = parser.parse_args()
    random.seed(cli.seed)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    # ── entity_opinions.json 読み込み ─────────────────────────────────────
    opinions_data = json.loads(cli.opinions_json.read_text())
    entities = opinions_data["entities"]

    id_to_entity  = {e["id"]: e for e in entities}

    # ── entity_graph.json: co_mention weight ─────────────────────────────
    graph = json.loads(cli.graph_json.read_text())
    co_weight: dict[tuple, int] = {}
    for edge in graph["edges"]:
        if edge["type"] == "co_mention":
            key = (min(edge["source"], edge["target"]),
                   max(edge["source"], edge["target"]))
            co_weight[key] = edge["weight"]

    # ── ペアスコア集計 ───────────────────────────────────────────────────
    pair_signals: dict[tuple, dict] = defaultdict(
        lambda: {"forward": [], "backward": []})

    for e in entities:
        src_id = e["id"]
        for r in e.get("relations", []):
            tgt_id = r.get("target_id", "")
            if not tgt_id or tgt_id == src_id:
                continue
            key = (min(src_id, tgt_id), max(src_id, tgt_id))
            if src_id <= tgt_id:
                pair_signals[key]["forward"].append(r["relation_type"])
            else:
                pair_signals[key]["backward"].append(r["relation_type"])

    candidate_pairs = []
    for key, sig in pair_signals.items():
        oc = len(sig["forward"]) + len(sig["backward"])
        bi = bool(sig["forward"]) and bool(sig["backward"])
        co_w = co_weight.get(key, 0)
        score = oc + (3 if bi else 0) + co_w * 2
        candidate_pairs.append({
            "id_a":    key[0],
            "id_b":    key[1],
            "score":   score,
            "forward": sig["forward"],
            "backward": sig["backward"],
        })

    candidate_pairs.sort(key=lambda x: (-x["score"], x["id_a"], x["id_b"]))
    scored_pairs = augment_pairs_for_connectivity(entities, candidate_pairs, cli.score_threshold)
    print(f"対象ペア数: {len(scored_pairs)}  (threshold={cli.score_threshold} + connectivity rescue)")

    # ── data.json: entity_id → item_ids ──────────────────────────────────
    entity_item_ids: dict[str, list[str]] = defaultdict(list)
    with open(cli.data_json) as f:
        for row in json.load(f).get("mentions", []):
            entity_id = row.get("entity_id", "").strip()
            item_id = row["item_id"]
            if entity_id and item_id not in entity_item_ids[entity_id]:
                entity_item_ids[entity_id].append(item_id)

    comment_body, cluster_comments = load_cluster_comments(
        index_csv=cli.index_csv,
        comment_texts_json=cli.comment_texts_json,
        clusters_csv=cli.clusters_csv,
    )

    # ── resume ───────────────────────────────────────────────────────────
    done: dict[str, dict] = {}
    if cli.resume and cli.output_json.exists():
        existing = json.loads(cli.output_json.read_text())
        done = {p["pair_key"]: p for p in existing.get("pairs", [])}
        print(f"resume: {len(done)} ペアをスキップ\n")

    # ── メインループ ─────────────────────────────────────────────────────
    results: list[dict] = list(done.values())
    n = len(scored_pairs)

    for i, pair in enumerate(scored_pairs):
        id_a, id_b = pair["id_a"], pair["id_b"]
        ea = id_to_entity.get(id_a, {})
        eb = id_to_entity.get(id_b, {})
        label_a = ea.get("controlled_label", id_a)
        label_b = eb.get("controlled_label", id_b)

        # controlled_label のアルファベット順で A/B を確定
        if label_a > label_b:
            id_a, id_b = id_b, id_a
            ea, eb = eb, ea
            label_a, label_b = label_b, label_a

        pair_key = f"{id_a}|{id_b}"

        if pair_key in done:
            print(f"[{i+1:03d}/{n}] {label_a} × {label_b} — skip")
            continue

        # 共通クラスタ優先、なければ union
        item_ids_a = set(entity_item_ids.get(id_a, []))
        item_ids_b = set(entity_item_ids.get(id_b, []))
        shared = item_ids_a & item_ids_b
        source_item_ids = shared if shared else item_ids_a | item_ids_b

        all_comments: list[dict] = []
        seen_cids: set[str] = set()
        for item_id in source_item_ids:
            for c in cluster_comments.get(item_id, []):
                if c["comment_id"] not in seen_cids:
                    seen_cids.add(c["comment_id"])
                    all_comments.append(c)

        # centroid 優先サンプリング
        centroids = [c for c in all_comments if c["centroid"]]
        others    = [c for c in all_comments if not c["centroid"]]
        random.shuffle(others)
        sampled = (centroids + others)[:cli.max_comments]
        texts = [comment_body[c["comment_id"]]
                 for c in sampled if c["comment_id"] in comment_body]

        source_desc = "共通" if shared else "union"
        print(f"[{i+1:03d}/{n}] score={pair['score']}  "
              f"{label_a} × {label_b}  "
              f"({len(texts)} comments, {source_desc}, {pair.get('selection_reason', 'threshold')})")

        if not texts:
            print("  → コメントなし、スキップ")
            result_entry = {
                "pair_key":        pair_key,
                "id_a":            id_a, "label_a": label_a,
                "id_b":            id_b, "label_b": label_b,
                "score":           pair["score"],
                "selection_reason": pair.get("selection_reason", "threshold"),
                "shared_clusters": len(shared),
                "comment_count":   0,
                "description":     "",
                "evidence":        "",
            }
            results.append(result_entry)
            continue

        out = call_llm(
            client,
            label_a, ea.get("wikidata_desc", ""),
            label_b, eb.get("wikidata_desc", ""),
            texts,
            cli.model,
        )

        result_entry = {
            "pair_key":        pair_key,
            "id_a":            id_a,
            "label_a":         label_a,
            "id_b":            id_b,
            "label_b":         label_b,
            "score":           pair["score"],
            "selection_reason": pair.get("selection_reason", "threshold"),
            "shared_clusters": len(shared),
            "comment_count":   len(texts),
            "description":     out.get("description", ""),
            "evidence":        out.get("evidence", ""),
        }

        results.append(result_entry)

        # 途中保存
        cli.output_json.parent.mkdir(parents=True, exist_ok=True)
        cli.output_json.write_text(
            json.dumps({"pairs": results}, ensure_ascii=False, indent=2))

    # ── 最終保存 ─────────────────────────────────────────────────────────
    cli.output_json.parent.mkdir(parents=True, exist_ok=True)
    cli.output_json.write_text(
        json.dumps({"pairs": results}, ensure_ascii=False, indent=2))

    filled = sum(1 for p in results if p.get("description"))
    print(f"\n完了: {cli.output_json}")
    print(f"  ペア数:         {len(results)}")
    print(f"  説明あり:       {filled}")


if __name__ == "__main__":
    main()
