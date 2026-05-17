"""
Ward 法で argument micro-cluster を生成し、centroid 情報を出力する。

高次元 embedding を L2 正規化し、全ペア Euclidean 距離に対して
Ward hierarchical clustering を適用する。
"""

import argparse
import csv
import pickle
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from settings import DEFAULT_DATA_DIR, MICROCLUSTER_THRESHOLD  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument(
        "--embeddings-pkl",
        type=Path,
        default=None,
        help="Path to embeddings.pkl (default: --data-dir/embeddings.pkl)",
    )
    parser.add_argument(
        "--hierarchical-clusters-csv",
        type=Path,
        default=None,
        help="Path to hierarchical_clusters.csv (default: --data-dir/hierarchical_clusters.csv)",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="Output CSV path (default: --data-dir/argument_microclusters_t<threshold>.csv)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.data_dir = args.data_dir or DEFAULT_DATA_DIR
    threshold = args.threshold
    if threshold is None:
        threshold = MICROCLUSTER_THRESHOLD
    args.embeddings_pkl = args.embeddings_pkl or args.data_dir / "embeddings.pkl"
    args.hierarchical_clusters_csv = args.hierarchical_clusters_csv or args.data_dir / "hierarchical_clusters.csv"
    output_csv = args.output_csv or args.data_dir / f"argument_microclusters_t{threshold}.csv"

    print("embeddings 読み込み中...")
    with open(args.embeddings_pkl, "rb") as f:
        emb_data = pickle.load(f)
    embed_by_id = {d["arg-id"]: np.array(d["embedding"], dtype=np.float32) for d in emb_data}

    arg_ids: list[str] = []
    with open(args.hierarchical_clusters_csv) as f:
        for row in csv.DictReader(f):
            arg_ids.append(row["arg-id"])

    mat = np.array([embed_by_id[aid] for aid in arg_ids], dtype=np.float32)

    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    mat = mat / np.where(norms == 0, 1, norms)

    print(f"{len(arg_ids)} arguments で Ward dendrogram 構築中...")
    Z = linkage(pdist(mat, metric="euclidean"), method="ward")

    print(f"閾値 t={threshold} で fcluster...")
    labels = fcluster(Z, t=threshold, criterion="distance")
    n_clusters = len(set(labels))
    print(f"  -> {n_clusters} micro-clusters")

    buckets: dict[int, list[int]] = defaultdict(list)
    for i, lbl in enumerate(labels):
        buckets[int(lbl)].append(i)

    centroid_of: dict[int, str] = {}
    for lbl, indices in buckets.items():
        sub = mat[indices]
        center = sub.mean(axis=0)
        dists = np.linalg.norm(sub - center, axis=1)
        centroid_idx = indices[int(np.argmin(dists))]
        centroid_of[lbl] = arg_ids[centroid_idx]

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["arg_id", "micro_cluster_id", "cluster_size", "is_centroid", "centroid_arg_id"],
        )
        writer.writeheader()
        for i, aid in enumerate(arg_ids):
            lbl = int(labels[i])
            centroid_aid = centroid_of[lbl]
            writer.writerow({
                "arg_id": aid,
                "micro_cluster_id": lbl,
                "cluster_size": len(buckets[lbl]),
                "is_centroid": "true" if aid == centroid_aid else "false",
                "centroid_arg_id": centroid_aid,
            })

    n_centroids = len(buckets)
    n_multi = sum(1 for b in buckets.values() if len(b) >= 2)
    print(f"完了: {output_csv}")
    print(f"  centroid (= ユニーク論点): {n_centroids}")
    print(f"  2件以上のクラスタ: {n_multi}")


if __name__ == "__main__":
    main()
