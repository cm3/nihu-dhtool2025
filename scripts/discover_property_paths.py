"""
Phase C: Wikidata property path discovery

同一ラベル内の QID ペアに対して Wikidata API でプロパティを取得し、
直接接続・共通上位クラスを発見する。

入力:
    work/kouchou-ai/el/candidates.json

出力:
    work/kouchou-ai/el/property_paths.tsv
      列: label_id, qid_a, label_a, qid_b, label_b,
          relation_type, property_id, property_label, direction, via_qid, via_label
    work/kouchou-ai/el/entity_props_cache.json  (再実行高速化用)

使い方:
    python scripts/discover_property_paths.py
    python scripts/discover_property_paths.py --no-cache
"""

import argparse
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from settings import DEFAULT_DATA_DIR  # noqa: E402

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# 取得・探索対象のプロパティ
FETCH_PROPS = {"P31", "P279", "P361", "P527", "P1269", "P460"}
PROP_LABELS = {
    "P31":   "instance of",
    "P279":  "subclass of",
    "P361":  "part of",
    "P527":  "has part",
    "P1269": "facet of",
    "P460":  "said to be the same as",
}


# ── Wikidata API ─────────────────────────────────────────────────────────────

def fetch_entities(qids: list[str], cache: dict) -> None:
    """wbgetentities で claims + labels を取得してキャッシュに書き込む（50件バッチ）"""
    to_fetch = [q for q in qids if q not in cache]
    if not to_fetch:
        return
    for i in range(0, len(to_fetch), 50):
        batch = to_fetch[i:i + 50]
        params = {
            "action":    "wbgetentities",
            "ids":       "|".join(batch),
            "props":     "claims|labels",
            "languages": "ja|en",
            "format":    "json",
        }
        url = WIKIDATA_API + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"User-Agent": "dhtool2025/1.0 (energy policy research)"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = int(e.headers.get("Retry-After", 60))
                    print(f"  [429] {wait}秒待機…", file=sys.stderr)
                    time.sleep(wait)
                else:
                    print(f"  [HTTP {e.code}] {e}", file=sys.stderr)
                    break
            except Exception as e:
                print(f"  [ERROR] {e}", file=sys.stderr)
                break

        for qid, ent in data.get("entities", {}).items():
            if ent.get("missing"):
                cache[qid] = {"label": qid, "claims": {}}
                continue
            label = (ent.get("labels", {}).get("ja", {}).get("value")
                     or ent.get("labels", {}).get("en", {}).get("value")
                     or qid)
            claims: dict[str, list[str]] = {}
            for prop, vals in ent.get("claims", {}).items():
                if prop not in FETCH_PROPS:
                    continue
                targets = []
                for v in vals:
                    snak = v.get("mainsnak", {})
                    if snak.get("snaktype") == "value":
                        val = snak.get("datavalue", {}).get("value", {})
                        if isinstance(val, dict) and "id" in val:
                            targets.append(val["id"])
                if targets:
                    claims[prop] = targets
            cache[qid] = {"label": label, "claims": claims}

        time.sleep(1.0)


# ── 関係探索 ─────────────────────────────────────────────────────────────────

def find_relations(qid_a: str, qid_b: str, cache: dict) -> list[dict]:
    """2 QID 間の直接接続・共通上位クラスを返す"""
    results = []
    claims_a = cache.get(qid_a, {}).get("claims", {})
    claims_b = cache.get(qid_b, {}).get("claims", {})

    # A → prop → B
    for prop, targets in claims_a.items():
        if qid_b in targets:
            results.append({
                "relation_type":  "direct",
                "property_id":    prop,
                "property_label": PROP_LABELS.get(prop, prop),
                "direction":      "a_to_b",
                "via_qid":        "",
                "via_label":      "",
            })

    # B → prop → A
    for prop, targets in claims_b.items():
        if qid_a in targets:
            results.append({
                "relation_type":  "direct",
                "property_id":    prop,
                "property_label": PROP_LABELS.get(prop, prop),
                "direction":      "b_to_a",
                "via_qid":        "",
                "via_label":      "",
            })

    # 共通 P31/P279 上位クラス（1ホップ）
    anc_a = set(claims_a.get("P279", [])) | set(claims_a.get("P31", []))
    anc_b = set(claims_b.get("P279", [])) | set(claims_b.get("P31", []))
    for anc in anc_a & anc_b:
        results.append({
            "relation_type":  "shared_ancestor",
            "property_id":    "P279/P31",
            "property_label": "共通上位クラス/インスタンス",
            "direction":      "symmetric",
            "via_qid":        anc,
            "via_label":      cache.get(anc, {}).get("label", anc),
        })

    return results


# ── メイン ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--data-json",
        type=Path,
        default=None,
        help="Input data.json path (default: --data-dir/data.json)",
    )
    parser.add_argument(
        "--output-tsv",
        type=Path,
        default=None,
        help="Output TSV path (default: --data-dir/property_paths.tsv)",
    )
    parser.add_argument(
        "--cache-json",
        type=Path,
        default=None,
        help="Wikidata cache JSON path (default: --data-dir/entity_props_cache.json)",
    )
    parser.add_argument("--no-cache", action="store_true", help="キャッシュを無視して再取得")
    cli = parser.parse_args()
    cli.data_dir = cli.data_dir or DEFAULT_DATA_DIR
    cli.data_json = cli.data_json or cli.data_dir / "data.json"
    cli.output_tsv = cli.output_tsv or cli.data_dir / "property_paths.tsv"
    cli.cache_json = cli.cache_json or cli.data_dir / "entity_props_cache.json"

    data = json.loads(cli.data_json.read_text())
    entities = data.get("entities", {})
    item_by_id = {item["id"]: item for item in data.get("items", [])}

    # data.json から item_id → [(qid, surface)] を構築
    item_qids: dict[str, list[dict]] = defaultdict(list)
    for row in data.get("mentions", []):
            qid = row.get("entity_id", "").strip()
            if not qid or qid == "AMBIGUOUS" or not qid.startswith("Q"):
                continue
            item_id = row["item_id"]
            item_qids[item_id].append({
                "qid":             qid,
                "surface":         row["mention"],
                "controlled_label": entities.get(qid, {}).get("label", row.get("mention", "")),
            })

    # ペアを持つ item のみ対象
    pairs_by_item = {
        lid: list(combinations(items, 2))
        for lid, items in item_qids.items()
        if len(items) >= 2
    }
    all_qids = list({item["qid"] for items in item_qids.values() for item in items})
    print(f"ユニーク QID 数: {len(all_qids)}")
    print(f"ペアを持つ item 数: {len(pairs_by_item)}")
    total_pairs = sum(len(v) for v in pairs_by_item.values())
    print(f"総ペア数: {total_pairs}")

    # キャッシュ読み込み
    cache: dict = {}
    if not cli.no_cache and cli.cache_json.exists():
        cache = json.loads(cli.cache_json.read_text())
        print(f"キャッシュ読み込み: {len(cache)} エンティティ")

    # エンティティデータ取得
    print("\nWikidata からエンティティデータ取得中…")
    fetch_entities(all_qids, cache)

    # 上位クラス QID も取得（via_qid のラベル解決）
    ancestor_qids = [
        q for ent in cache.values()
        for prop in ["P279", "P31"] for q in ent.get("claims", {}).get(prop, [])
    ]
    fetch_entities(list(set(ancestor_qids)), cache)

    # キャッシュ保存
    cli.cache_json.parent.mkdir(parents=True, exist_ok=True)
    cli.cache_json.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    print(f"キャッシュ保存: {len(cache)} エンティティ → {cli.cache_json}")

    # 関係探索 + TSV 出力
    fieldnames = [
        "item_id", "item_label",
        "qid_a", "label_a", "surface_a",
        "qid_b", "label_b", "surface_b",
        "relation_type", "property_id", "property_label", "direction",
        "via_qid", "via_label",
    ]
    rows_out = []
    for item_id, pairs in sorted(pairs_by_item.items()):
        item_label = item_by_id.get(item_id, {}).get("label", "")
        for item_a, item_b in pairs:
            relations = find_relations(item_a["qid"], item_b["qid"], cache)
            if not relations:
                # 関係なしも記録（no_relation）
                rows_out.append({
                    "item_id":        item_id,
                    "item_label":     item_label,
                    "qid_a":          item_a["qid"],
                    "label_a":        cache.get(item_a["qid"], {}).get("label", ""),
                    "surface_a":      item_a["surface"],
                    "qid_b":          item_b["qid"],
                    "label_b":        cache.get(item_b["qid"], {}).get("label", ""),
                    "surface_b":      item_b["surface"],
                    "relation_type":  "none",
                    "property_id":    "",
                    "property_label": "",
                    "direction":      "",
                    "via_qid":        "",
                    "via_label":      "",
                })
            else:
                for rel in relations:
                    rows_out.append({
                        "item_id":   item_id,
                        "item_label": item_label,
                        "qid_a":     item_a["qid"],
                        "label_a":   cache.get(item_a["qid"], {}).get("label", ""),
                        "surface_a": item_a["surface"],
                        "qid_b":     item_b["qid"],
                        "label_b":   cache.get(item_b["qid"], {}).get("label", ""),
                        "surface_b": item_b["surface"],
                        **rel,
                    })

    cli.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with open(cli.output_tsv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows_out)

    found    = sum(1 for r in rows_out if r["relation_type"] != "none")
    no_rel   = sum(1 for r in rows_out if r["relation_type"] == "none")
    direct   = sum(1 for r in rows_out if r["relation_type"] == "direct")
    shared   = sum(1 for r in rows_out if r["relation_type"] == "shared_ancestor")
    print(f"\n完了: {cli.output_tsv}")
    print(f"  総ペア:       {total_pairs}")
    print(f"  関係あり:     {found}  (直接接続: {direct}, 共通上位: {shared})")
    print(f"  関係なし:     {no_rel}")


if __name__ == "__main__":
    main()
