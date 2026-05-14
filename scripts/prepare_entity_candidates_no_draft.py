"""
Phase A: エンティティリンキング候補生成スクリプト

L2 クラスタラベル（64件）と takeaway に対して:
  1. LLM がエンティティ候補メンションを識別
  2. Wikidata Search API で候補QIDを取得
  3. LLM が最適QIDを選択
  4. 人手修正用 candidates.json を出力

入力:
    data/hierarchical_result.json

出力:
    data/data.json

使い方:
    python scripts/prepare_entity_candidates_no_draft.py
    python scripts/prepare_entity_candidates_no_draft.py --model gpt-5.4-mini
    python scripts/prepare_entity_candidates_no_draft.py --resume
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULT_JSON = ROOT / "data/hierarchical_result.json"
DEFAULT_OUTPUT_JSON = ROOT / "data/data.json"

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_CACHE: dict[str, list[dict]] = {}

STAGE1_SYSTEM = """\
エネルギー政策のパブリックコメント分析に使用するカテゴリラベルと takeaway から、
Wikidata にエンティティとして存在しそうな語句を特定してください。

カテゴリラベルはクラスタの短い代表表現です。takeaway は同じクラスタの要点を
文章で要約した補助文脈です。ラベルに現れていない具体的な技術名、制度名、
施策名、事象名が takeaway に含まれている場合は、それも抽出対象にしてください。

対象:
  - 具体的な技術・エネルギー種別（再生可能エネルギー、地熱発電、水素エネルギー等）
  - 具体的な出来事・事象（原発事故等）
  - 組織・制度名
  - 固有の概念（核廃棄物、脱炭素等）

対象外（リンク不要）:
  - 「推進」「強化」「実現」「構築」「確保」等の抽象動名詞
  - 「重要性」「必要性」「懸念」等の抽象名詞
  - 「持続可能な」「透明性のある」等の形容表現

出力形式（JSONのみ、余分なテキスト不要）:
{
  "label_id": "2_49",
  "mentions": [
    {"surface": "核廃棄物", "search_ja": "核廃棄物", "search_en": "nuclear waste"},
    {"surface": "原発", "search_ja": "原子力発電 OR 原子力発電所", "search_en": "nuclear power plant"}
  ]
}
"""

STAGE2_SYSTEM = """\
ラベルテキストと takeaway の文脈を見て、
Wikidata の候補エンティティから最適なものを選び、
ラベルテキストを [[QID|表層]] 形式で注釈してください。

ルール:
  - 候補が明確に適切ならそのQIDを選ぶ（confidence: high）
  - やや適切な場合は confidence: medium / low
  - 適切な候補がなければ qid: NONE, confidence: none
  - 同程度に適切な候補が複数ある場合は qid: AMBIGUOUS, confidence: low, noteに候補を列挙
  - 抽象動名詞・形容表現はリンクしない

出力形式（JSONのみ）:
{
  "annotated": "[[Q12705|再生可能エネルギー]]と[[Q503486|蓄電池]]による...",
  "links": [
    {"surface": "再生可能エネルギー", "qid": "Q12705", "wikidata_label": "再生可能エネルギー",
     "wikidata_desc": "...", "confidence": "high", "note": ""},
    {"surface": "原発", "qid": "AMBIGUOUS", "wikidata_label": "",
     "wikidata_desc": "", "confidence": "low",
     "note": "also_candidate:Q134447(原子力発電所) or Q17232373(原子力発電)"}
  ]
}
"""


def wikidata_search(query: str, limit: int = 5) -> list[dict]:
    """Wikidata Search API（キャッシュ + 429 バックオフ付き）"""
    cache_key = f"{query}:{limit}"
    if cache_key in WIKIDATA_CACHE:
        return WIKIDATA_CACHE[cache_key]

    params = {
        "action": "wbsearchentities",
        "search": query,
        "language": "ja",
        "uselang": "ja",
        "format": "json",
        "limit": str(limit),
        "type": "item",
    }
    url = WIKIDATA_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "dhtool2025/1.0 (energy policy research)"},
    )

    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            time.sleep(1.0)
            results = [
                {
                    "qid": item["id"],
                    "label": item.get("label", ""),
                    "desc": item.get("description", "")[:80],
                }
                for item in data.get("search", [])
            ]
            WIKIDATA_CACHE[cache_key] = results
            return results
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = e.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 60 * (attempt + 1)
                print(
                    f"  [Wikidata 429] '{query}' — Retry-After: {retry_after or '不明'}, "
                    f"{wait}秒待機してリトライ ({attempt+1}/3)…",
                    file=sys.stderr,
                )
                time.sleep(wait)
            else:
                print(f"  [Wikidata ERROR] {query}: {e}", file=sys.stderr)
                break
        except Exception as e:
            print(f"  [Wikidata ERROR] {query}: {e}", file=sys.stderr)
            break

    WIKIDATA_CACHE[cache_key] = []
    return []


def fetch_candidates_for_mentions(mentions: list[dict]) -> list[dict]:
    """各メンションの Wikidata 候補を取得して mentions に注入して返す"""
    enriched = []
    for m in mentions:
        candidates = wikidata_search(m["search_ja"], limit=4)
        if m.get("search_en"):
            for c in wikidata_search(m["search_en"], limit=3):
                if not any(x["qid"] == c["qid"] for x in candidates):
                    candidates.append(c)
        enriched.append({**m, "candidates": candidates})
    return enriched


def cluster_takeaway(cluster: dict) -> str:
    """広聴AIの hierarchical_result.json からクラスタ takeaway を取り出す。"""
    value = cluster.get("takeaway", "")
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(v).strip() for v in value if str(v).strip())
    return str(value).strip() if value is not None else ""


def format_cluster_context(label_id: str, label_text: str, takeaway: str) -> str:
    lines = [
        f'label_id: "{label_id}"',
        f'ラベル: "{label_text}"',
    ]
    if takeaway:
        lines.append(f'takeaway: """{takeaway}"""')
    return "\n".join(lines)


def llm_identify_mentions(
    client: OpenAI,
    label_id: str,
    label_text: str,
    takeaway: str,
    model: str,
    retries: int = 3,
) -> list[dict]:
    """Stage 1: LLM でメンション識別"""
    user_msg = format_cluster_context(label_id, label_text, takeaway)
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": STAGE1_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            data = json.loads(resp.choices[0].message.content)
            return data.get("mentions", [])
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [LLM Stage1 ERROR] {label_id}: {e}", file=sys.stderr)
                return []


def llm_select_qids(
    client: OpenAI,
    label_id: str,
    label_text: str,
    takeaway: str,
    enriched_mentions: list[dict],
    model: str,
    retries: int = 3,
) -> dict:
    """Stage 2: LLM で最適QIDを選択 + ラベルを [[]] 注釈"""
    mention_block = ""
    for i, m in enumerate(enriched_mentions, 1):
        cands_text = ""
        for c in m["candidates"]:
            cands_text += f"    - {c['qid']}: {c['label']} / {c['desc']}\n"
        if not cands_text:
            cands_text = "    （候補なし）\n"
        mention_block += (
            f"{i}. surface: \"{m['surface']}\"\n"
            f"   candidates:\n{cands_text}"
        )

    user_msg = (
        f'label_id: "{label_id}"\n'
        f'ラベル原文: "{label_text}"\n\n'
        f'takeaway: """{takeaway}"""\n\n'
        f"メンションと候補:\n{mention_block}"
    )
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": STAGE2_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  [LLM Stage2 ERROR] {label_id}: {e}", file=sys.stderr)
                return {"annotated": label_text, "links": []}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-5.4-mini")
    parser.add_argument(
        "--result-json",
        type=Path,
        default=DEFAULT_RESULT_JSON,
        help="Path to hierarchical_result.json",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Output JSON path",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="output-json が既にあれば処理済み item_id をスキップ",
    )
    cli = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    with open(cli.result_json) as f:
        data = json.load(f)
    clusters = [d for d in data["clusters"] if d["level"] == 2]
    print(f"L2クラスタ数: {len(clusters)}")
    print(f"モデル: {cli.model}\n")

    cli.output_json.parent.mkdir(parents=True, exist_ok=True)

    if cli.output_json.exists() and not cli.resume:
        print(f"⚠️  {cli.output_json} が既に存在します。")
        print("   手作業で編集した内容がある場合は el/_local/ へバックアップしてください。")
        ans = input("上書きしますか？ [y/N] ").strip().lower()
        if ans != "y":
            print("中止しました。")
            sys.exit(0)

    done_ids: set[str] = set()
    existing_rows: list[dict] = []
    if cli.resume and cli.output_json.exists():
        existing = json.loads(cli.output_json.read_text())
        existing_rows = existing.get("mentions", existing)
        done_ids = {row["label_id"] for row in existing_rows}
        print(f"resume: {len(done_ids)} label をスキップ\n")

    json_rows: list[dict] = list(existing_rows)

    for i, cl in enumerate(clusters):
        label_id = cl["id"]
        label_text = cl["label"]
        takeaway = cluster_takeaway(cl)
        l1 = cl["parent"]

        if label_id in done_ids:
            print(f"[{i+1:02d}/{len(clusters)}] {label_id} — skip (resume)")
            continue

        print(f"[{i+1:02d}/{len(clusters)}] {label_id} ({l1}): {label_text[:40]}…")

        mentions = llm_identify_mentions(
            client, label_id, label_text, takeaway, cli.model
        )
        if not mentions:
            print("  → メンションなし")
            continue

        enriched = fetch_candidates_for_mentions(mentions)
        result = llm_select_qids(
            client, label_id, label_text, takeaway, enriched, cli.model
        )
        links = result.get("links", [])

        print(f"  → {len(links)} メンション")

        for lk in links:
            json_rows.append(
                {
                    "label_id": label_id,
                    "mention": lk.get("surface", ""),
                    "qid": lk.get("qid", "NONE"),
                    "controlled_label": lk.get("wikidata_label", ""),
                    "wikidata_desc": lk.get("wikidata_desc", ""),
                    "confidence": lk.get("confidence", ""),
                    "note": lk.get("note", ""),
                }
            )

    t_counter = 1
    entities: dict[str, dict] = {}
    final_rows: list[dict] = []
    for row in json_rows:
        qid = row.get("qid", "NONE")
        if qid == "NONE":
            t_id = f"T{t_counter}"
            t_counter += 1
            entities[t_id] = {
                "label": row.get("controlled_label", "") or row.get("mention", ""),
                "desc": row.get("wikidata_desc", ""),
            }
            row_id = t_id
        elif qid == "AMBIGUOUS":
            row_id = "AMBIGUOUS"
        else:
            if qid not in entities:
                entities[qid] = {
                    "label": row.get("controlled_label", ""),
                    "desc": row.get("wikidata_desc", ""),
                }
            row_id = qid

        final_rows.append(
            {
                "item_id": row["label_id"],
                "mention": row["mention"],
                "entity_id": row_id,
                "confidence": row.get("confidence", ""),
                "note": row.get("note", ""),
            }
        )

    combined = {
        "mentions": final_rows,
        "entities": entities,
        "items": [
            {
                "id": cl["id"],
                "label": cl["label"],
                "description": cluster_takeaway(cl),
            }
            for cl in clusters
        ],
    }
    cli.output_json.write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n完了:")
    print(f"  {cli.output_json}  ({len(json_rows)} 行)")
    print("\n次のステップ:")
    print("  1. keyword-curation で entity_id を確認・修正")
    print(f"  2. python scripts/discover_property_paths.py --data-json {cli.output_json}")
    print(f"  3. python scripts/build_entity_graph.py --data-json {cli.output_json}")
    print(f"  4. python scripts/extract_entity_opinions.py --data-json {cli.output_json}")


if __name__ == "__main__":
    main()
