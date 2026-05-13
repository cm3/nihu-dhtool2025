"""
Phase D: エンティティごとの意見抽出

各エンティティが登場するクラスタの argument に対応するコメント（compressed版）から、
そのエンティティへの立場・意見・他エンティティとの関係を LLM で抽出する。

入力:
    data/data.json
    data/cluster_comment_index.csv
    data/comment_texts.json
    data/argument_microclusters_t0.7.csv

出力:
    data/entity_opinions.json

使い方:
    python scripts/extract_entity_opinions.py
    python scripts/extract_entity_opinions.py --resume
    python scripts/extract_entity_opinions.py --model gpt-5.4-mini --max-comments 40
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = ROOT.parents[1]
DEFAULT_DATA_JSON = ROOT / "data/data.json"
DEFAULT_INDEX_CSV = ROOT / "data/cluster_comment_index.csv"
DEFAULT_COMMENT_TEXTS_JSON = ROOT / "data/comment_texts.json"
DEFAULT_CLUSTERS_CSV = ROOT / "data/argument_microclusters_t0.7.csv"
DEFAULT_OUTPUT_JSON = ROOT / "data/entity_opinions.json"
DEFAULT_EXAMPLE_EMBEDDING_MODEL = "text-embedding-3-small"

RELATION_TYPES = [
    "promotes",      # A は B を促進・支援する
    "opposes",       # A は B に反対・競合する
    "requires",      # A には B が必要
    "replaces",      # A は B の代替になりうる
    "risk_of",       # A は B のリスク・問題
    "compared_with", # A と B が対比・比較される
    "causes",        # A が B を引き起こす
    "solution_for",  # A は B への解決策
]

SYSTEM_PROMPT = """\
あなたはエネルギー政策のパブリックコメントを分析するアシスタントです。
注目エンティティについて、関連するコメントを分析し JSON で回答してください。

【関係タイプ定義】
  promotes     : A が B を促進・支援する（例:再エネ推進がエネルギー安全保障を強化）
  opposes      : A が B に反対・競合する（例:原発反対、再エネとの対比）
  requires     : A には B が必要（例:再エネには蓄電池が必要）
  replaces     : A が B の代替になりうる（例:再エネが原発を代替）
  risk_of      : A が B のリスク・問題点（例:原発事故が健康リスクを生む）
  compared_with: A と B が対比・比較される（例:原発 vs 再エネのコスト比較）
  causes       : A が B を引き起こす（例:化石燃料が温室効果ガスを排出）
  solution_for : A が B への解決策（例:再エネが気候変動対策に）

【方向】
  a_to_b  : 上記の関係が 注目エンティティ→候補 の方向
  b_to_a  : 候補→注目エンティティ の方向
  symmetric: 双方向・対称

出力は必ず以下の JSON のみ（余分なテキスト不要）:
{
  "sentiment": "positive|negative|mixed|neutral",
  "sentiment_reason": "20字以内の理由",
  "opinion_points": ["主な意見1", "主な意見2", "主な意見3"],
  "relations": [
    {
      "target_id": "Q12705",
      "target_label": "再生可能エネルギー",
      "relation_type": "promotes|opposes|...",
      "direction": "a_to_b|b_to_a|symmetric",
      "evidence": "根拠となるキーフレーズ（30字以内）"
    }
  ]
}

注意:
- relations は証拠が明確なものだけ（確信が低ければ含めない）
- 候補リストにないエンティティは relations に含めない
"""


def build_user_message(entity_label: str, entity_desc: str,
                       arguments: list[str], entity_list: list[dict]) -> str:
    entity_list_text = "\n".join(
        f"  - {e['id']}: {e['label']}" for e in entity_list
    )
    comments_text = "\n\n".join(f"[{i+1}] {a}" for i, a in enumerate(arguments))
    desc_part = f"（{entity_desc}）" if entity_desc else ""
    return (
        f"【注目エンティティ】{entity_label}{desc_part}\n\n"
        f"【エンティティ候補リスト】\n{entity_list_text}\n\n"
        f"【関連コメント（{len(arguments)}件）】\n{comments_text}"
    )


def call_llm(client: OpenAI, entity_label: str, entity_desc: str,
             arguments: list[str], entity_list: list[dict],
             model: str, retries: int = 3) -> dict:
    msg = build_user_message(entity_label, entity_desc, arguments, entity_list)
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


def normalize_matrix(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


def embed_text_map(
    client: OpenAI,
    text_map: dict[str, str],
    model: str,
    batch_size: int = 64,
) -> dict[str, np.ndarray]:
    if not text_map:
        return {}

    items = [(key, value) for key, value in text_map.items() if value.strip()]
    result: dict[str, np.ndarray] = {}
    for start in range(0, len(items), batch_size):
        batch = items[start:start + batch_size]
        resp = client.embeddings.create(
            model=model,
            input=[text for _, text in batch],
        )
        mat = normalize_matrix(np.array([row.embedding for row in resp.data], dtype=np.float32))
        for (key, _), vec in zip(batch, mat):
            result[key] = vec
    return result


def build_example_query_text(label: str, entity_desc: str, surfaces: list[str]) -> str:
    parts = [f"用語: {label}"]
    if entity_desc:
        parts.append(f"説明: {entity_desc}")
    surface_text = [s for s in surfaces if s and s != label]
    if surface_text:
        parts.append("別表記候補: " + " / ".join(surface_text[:5]))
    return "\n".join(parts)


def build_search_terms(label: str, surfaces: list[str]) -> list[str]:
    terms: list[str] = []
    for term in [label, *surfaces]:
        cleaned = (term or "").strip()
        if cleaned and cleaned not in terms:
            terms.append(cleaned)
    return sorted(terms, key=len, reverse=True)


def normalize_for_excerpt(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\u3000", " ")).strip()


def find_best_match(text: str, terms: list[str]) -> tuple[int, str] | None:
    hay = normalize_for_excerpt(text)
    best: tuple[int, str] | None = None
    for term in terms:
        idx = hay.find(term)
        if idx == -1:
            continue
        if best is None or idx < best[0]:
            best = (idx, term)
    return best


def excerpt_around_match(text: str, terms: list[str], radius: int = 80, fallback: int = 140) -> tuple[str, bool]:
    flat = normalize_for_excerpt(text)
    if not flat:
        return "", False

    match = find_best_match(flat, terms)
    if match is None:
        snippet = flat[:fallback].strip()
        if len(flat) > len(snippet):
            snippet += "..."
        return snippet, False

    idx, term = match
    start = max(0, idx - radius)
    end = min(len(flat), idx + len(term) + radius)
    snippet = flat[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(flat):
        snippet = snippet + "..."
    return snippet, True


INTRO_MARKERS = [
    "と申します",
    "在住です",
    "している者です",
    "として活動しております",
    "として活動しています",
    "医療従事者の立場",
    "会社員です",
    "学生です",
    "農家です",
]


def strip_personal_intro(snippet: str) -> str:
    text = normalize_for_excerpt(snippet)
    text = re.sub(r"^(?:\.\.\.\s*)+", "", text)

    for _ in range(2):
        sentence_end = re.search(r"^.*?(?:。|！|!|？|\?)", text)
        if sentence_end:
            first_sentence = sentence_end.group(0)
            rest = text[sentence_end.end():].lstrip()
            if any(marker in first_sentence for marker in INTRO_MARKERS):
                text = rest
                continue
        else:
            head = text[:40]
            if any(marker in head for marker in INTRO_MARKERS):
                text = re.sub(r"^.*?(?:です|しております|しています)\s*", "", text, count=1)
        break

    return text.strip()


def build_example_args(
    all_comments: list[dict],
    comment_body: dict[str, str],
    label: str,
    entity_desc: str,
    surfaces: list[str],
    query_vec: np.ndarray | None,
    comment_vecs: dict[str, np.ndarray] | None,
    max_examples: int = 3,
) -> list[str]:
    terms = build_search_terms(label, surfaces)
    candidates = sorted(all_comments, key=lambda c: (not c["centroid"], c["comment_id"]))

    matched: list[str] = []
    fallback_meta: list[dict] = []
    seen: set[str] = set()

    for comment in candidates:
        comment_id = comment["comment_id"]
        text = comment_body.get(comment_id, "")
        if not text:
            continue
        snippet, has_match = excerpt_around_match(text, terms)
        snippet = strip_personal_intro(snippet)
        if not snippet or snippet in seen:
            continue
        seen.add(snippet)
        if has_match:
            matched.append(snippet)
        else:
            fallback_meta.append({
                "comment_id": comment_id,
                "snippet": snippet,
                "centroid": comment["centroid"],
            })

    semantic: list[str] = []
    if len(matched) < max_examples and query_vec is not None and comment_vecs:
        ranked: list[tuple[float, int, str]] = []
        for row in fallback_meta:
            vec = comment_vecs.get(row["comment_id"])
            if vec is None:
                continue
            score = float(np.dot(query_vec, vec))
            ranked.append((score, 0 if row["centroid"] else 1, row["snippet"]))
        ranked.sort(key=lambda x: (-x[0], x[1], x[2]))
        for _, _, snippet in ranked:
            if snippet not in semantic:
                semantic.append(snippet)
            if len(matched) + len(semantic) >= max_examples:
                break

    fallback = [row["snippet"] for row in fallback_meta if row["snippet"] not in semantic]
    return (matched + semantic + fallback)[:max_examples]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-json", type=Path, default=DEFAULT_DATA_JSON,
                        help="Input data.json path")
    parser.add_argument("--index-csv", type=Path, default=DEFAULT_INDEX_CSV,
                        help="Input cluster_comment_index.csv path")
    parser.add_argument("--comment-texts-json", type=Path, default=DEFAULT_COMMENT_TEXTS_JSON,
                        help="Input comment_texts.json path")
    parser.add_argument("--clusters-csv", type=Path, default=DEFAULT_CLUSTERS_CSV,
                        help="Input argument microcluster CSV path")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON,
                        help="Output entity_opinions.json path")
    parser.add_argument("--model",    default="gpt-5.4-mini")
    parser.add_argument("--example-embedding-model", default=DEFAULT_EXAMPLE_EMBEDDING_MODEL)
    parser.add_argument("--max-comments", type=int, default=40,
                        help="エンティティあたりの最大コメント数")
    parser.add_argument("--resume",   action="store_true")
    parser.add_argument("--seed",     type=int, default=42)
    cli = parser.parse_args()
    random.seed(cli.seed)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    # ── エンティティ読み込み ─────────────────────────────────────────────
    # entity_id → {controlled_label, wikidata_desc, qid, type, item_ids, surfaces}
    entities: dict[str, dict] = {}
    data = json.loads(cli.data_json.read_text())
    entity_meta = data.get("entities", {})
    for row in data.get("mentions", []):
            eid = row.get("entity_id", "").strip()
            mention = row.get("mention", "").strip()
            item_id = row["item_id"]
            meta = entity_meta.get(eid, {})

            if eid not in entities:
                entities[eid] = {
                    "id":               eid,
                    "qid":              eid if eid.startswith("Q") else None,
                    "controlled_label": meta.get("label", mention),
                    "wikidata_desc":    meta.get("desc", ""),
                    "type":             "wikidata" if eid.startswith("Q") else "local",
                    "item_ids":         [],
                    "surfaces":         [],
                }
            nd = entities[eid]
            if item_id not in nd["item_ids"]:
                nd["item_ids"].append(item_id)
            if mention not in nd["surfaces"]:
                nd["surfaces"].append(mention)

    comment_body, cluster_comments = load_cluster_comments(
        index_csv=cli.index_csv,
        comment_texts_json=cli.comment_texts_json,
        clusters_csv=cli.clusters_csv,
    )

    print(f"example_args 用コメント embedding を作成中... ({len(comment_body)} comments)")
    comment_vecs = embed_text_map(
        client=client,
        text_map=comment_body,
        model=cli.example_embedding_model,
    )

    entity_query_texts = {
        eid: build_example_query_text(
            label=nd["controlled_label"],
            entity_desc=nd["wikidata_desc"],
            surfaces=nd["surfaces"],
        )
        for eid, nd in entities.items()
    }
    print(f"example_args 用 query embedding を作成中... ({len(entity_query_texts)} entities)")
    entity_query_vecs = embed_text_map(
        client=client,
        text_map=entity_query_texts,
        model=cli.example_embedding_model,
    )

    # ── エンティティリスト（LLM に渡す候補） ─────────────────────────────
    entity_list_for_llm = [
        {"id": eid, "label": nd["controlled_label"]}
        for eid, nd in entities.items()
    ]

    # ── resume ───────────────────────────────────────────────────────────
    done: dict[str, dict] = {}
    if cli.resume and cli.output_json.exists():
        existing = json.loads(cli.output_json.read_text())
        done = {e["id"]: e for e in existing.get("entities", [])}
        print(f"resume: {len(done)} エンティティをスキップ\n")

    # ── メインループ ─────────────────────────────────────────────────────
    results: list[dict] = list(done.values())
    entity_items = list(entities.items())
    n = len(entity_items)

    for i, (eid, nd) in enumerate(entity_items):
        label = nd["controlled_label"]
        if eid in done:
            print(f"[{i+1:02d}/{n}] {label} — skip")
            continue

        # 関連コメントを収集（cluster_l2 = label_id）
        all_comments: list[dict] = []
        seen_cids: set[str] = set()
        for lid in nd["item_ids"]:
            for c in cluster_comments.get(lid, []):
                if c["comment_id"] not in seen_cids:
                    seen_cids.add(c["comment_id"])
                    all_comments.append(c)

        if not all_comments:
            print(f"[{i+1:02d}/{n}] {label} — コメントなし、スキップ")
            results.append({**nd, "sentiment": "neutral", "sentiment_reason": "コメントなし",
                            "opinion_points": [], "relations": [], "comment_count": 0,
                            "example_args": []})
            continue

        # centroid 優先でサンプリング
        centroids = [c for c in all_comments if c["centroid"]]
        others    = [c for c in all_comments if not c["centroid"]]
        random.shuffle(others)
        sampled = (centroids + others)[:cli.max_comments]
        comment_texts = [comment_body[c["comment_id"]]
                         for c in sampled if c["comment_id"] in comment_body]

        print(f"[{i+1:02d}/{n}] {label}  ({len(all_comments)} comments → {len(comment_texts)} 使用)")

        # LLM 呼び出し
        out = call_llm(client, label, nd["wikidata_desc"], comment_texts,
                       entity_list_for_llm, cli.model)

        # 例示コメントは entity 周辺の抜粋を優先して出す
        example_args = build_example_args(
            all_comments=all_comments,
            comment_body=comment_body,
            label=label,
            entity_desc=nd["wikidata_desc"],
            surfaces=nd["surfaces"],
            query_vec=entity_query_vecs.get(eid),
            comment_vecs=comment_vecs,
        )

        result_entry = {
            **nd,
            "comment_count":  len(all_comments),
            "sentiment":      out.get("sentiment", "neutral"),
            "sentiment_reason": out.get("sentiment_reason", ""),
            "opinion_points": out.get("opinion_points", []),
            "relations":      out.get("relations", []),
            "example_args":   example_args,
        }
        results.append(result_entry)

        # 途中保存
        cli.output_json.parent.mkdir(parents=True, exist_ok=True)
        cli.output_json.write_text(
            json.dumps({"entities": results}, ensure_ascii=False, indent=2))

    # ── 最終保存 ─────────────────────────────────────────────────────────
    cli.output_json.write_text(
        json.dumps({"entities": results}, ensure_ascii=False, indent=2))

    sentiments = [r.get("sentiment","") for r in results]
    rel_count  = sum(len(r.get("relations",[])) for r in results)
    print(f"\n完了: {cli.output_json}")
    print(f"  エンティティ数: {len(results)}")
    print(f"  sentiment 内訳: " + ", ".join(
        f"{s}={sentiments.count(s)}" for s in ["positive","negative","mixed","neutral"]))
    print(f"  抽出関係数:     {rel_count}")


if __name__ == "__main__":
    main()
