"""
comment と cluster / centroid の対応関係をまとめた索引を生成する。

入力:
- data/final_result_with_comments.csv
- data/hierarchical_clusters.csv
- argument_microclusters_t*.csv

出力:
- cluster_comment_index.csv
  arg_id / comment_id / cluster_l1 / cluster_l2 / is_centroid などを含む索引 CSV
- comment_texts.json
  comment_id -> comment text の対応だけを持つローカル用 JSON
"""

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = ROOT / "data"
DEFAULT_MICROCLUSTERS_CSV = ROOT / "data/argument_microclusters_t0.7.csv"
DEFAULT_INDEX_CSV = ROOT / "data/cluster_comment_index.csv"
DEFAULT_TEXTS_JSON = ROOT / "data/comment_texts.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--final-result-csv",
        type=Path,
        default=DEFAULT_INPUT_DIR / "final_result_with_comments.csv",
        help="Path to final_result_with_comments.csv",
    )
    parser.add_argument(
        "--hierarchical-clusters-csv",
        type=Path,
        default=DEFAULT_INPUT_DIR / "hierarchical_clusters.csv",
        help="Path to hierarchical_clusters.csv",
    )
    parser.add_argument(
        "--microclusters-csv",
        type=Path,
        default=DEFAULT_MICROCLUSTERS_CSV,
        help="Path to argument microcluster CSV",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_INDEX_CSV,
        help="Output cluster/index CSV path",
    )
    parser.add_argument(
        "--comment-texts-json",
        type=Path,
        default=DEFAULT_TEXTS_JSON,
        help="Output JSON path for comment_id -> comment text",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    cluster_by_arg: dict[str, dict[str, str]] = {}
    with open(args.hierarchical_clusters_csv) as f:
        for row in csv.DictReader(f):
            cluster_by_arg[row["arg-id"]] = {
                "cluster_l1": row["cluster-level-1-id"],
                "cluster_l2": row["cluster-level-2-id"],
            }

    micro_by_arg: dict[str, dict[str, str]] = {}
    with open(args.microclusters_csv) as f:
        for row in csv.DictReader(f):
            micro_by_arg[row["arg_id"]] = row

    rows: list[dict[str, str]] = []
    comment_texts: dict[str, str] = {}
    missing_clusters = 0
    missing_microclusters = 0

    with open(args.final_result_csv) as f:
        for row in csv.DictReader(f):
            arg_id = row["arg_id"]
            cluster = cluster_by_arg.get(arg_id)
            micro = micro_by_arg.get(arg_id)
            if cluster is None:
                missing_clusters += 1
                continue
            if micro is None:
                missing_microclusters += 1
                continue

            comment_id = row["comment-id"]
            comment_text = row["original-comment"]
            if comment_id not in comment_texts and comment_text:
                comment_texts[comment_id] = comment_text

            rows.append({
                "arg_id": arg_id,
                "comment_id": comment_id,
                "argument": row["argument"],
                "cluster_l1": cluster["cluster_l1"],
                "cluster_l2": cluster["cluster_l2"],
                "is_centroid": micro["is_centroid"],
                "micro_cluster_id": micro["micro_cluster_id"],
                "micro_cluster_size": micro["cluster_size"],
                "centroid_arg_id": micro["centroid_arg_id"],
                "source": row.get("source", ""),
                "url": row.get("url", ""),
                "original_count": row.get("attribute_original_count", ""),
                "duplicate_group_id": row.get("attribute_duplicate_group_id", ""),
            })

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_csv, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "arg_id",
                "comment_id",
                "argument",
                "cluster_l1",
                "cluster_l2",
                "is_centroid",
                "micro_cluster_id",
                "micro_cluster_size",
                "centroid_arg_id",
                "source",
                "url",
                "original_count",
                "duplicate_group_id",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    args.comment_texts_json.parent.mkdir(parents=True, exist_ok=True)
    args.comment_texts_json.write_text(
        json.dumps(comment_texts, ensure_ascii=False, indent=2) + "\n"
    )

    unique_comments = len({row["comment_id"] for row in rows})
    unique_args = len({row["arg_id"] for row in rows})
    print(f"完了: {args.output_csv}")
    print(f"完了: {args.comment_texts_json}")
    print(f"  rows: {len(rows)}")
    print(f"  unique comments: {unique_comments}")
    print(f"  unique arguments: {unique_args}")
    print(f"  missing hierarchical clusters: {missing_clusters}")
    print(f"  missing microclusters: {missing_microclusters}")


if __name__ == "__main__":
    main()
