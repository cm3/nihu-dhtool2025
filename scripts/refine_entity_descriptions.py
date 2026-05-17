"""
キュレーション後 data.json の entities[].desc を日本語で補強・整形する。

想定タイミング:
  - data.json の人手修正が終わった直後
  - discover_property_paths.py / build_entity_graph.py の前

既定動作:
  - 全 entity を対象に LLM で説明文を見直す

必要なら --only-weak で
  - desc が空
  - desc がほぼ英語
  - desc が短すぎる
ものだけに絞れる。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from settings import DEFAULT_DATA_DIR, LLM_MODEL  # noqa: E402

SYSTEM_PROMPT = """\
あなたは、エネルギー政策コメント分析用の entity 辞書を整える編集者です。

与えられた entity について、日本語の短い説明文を 1 つだけ作ってください。

要件:
- 出力は日本語
- 20〜50文字程度を目安に簡潔に
- 名詞句または短い説明文にする
- Wikidata 項目なら既存 desc を自然な日本語に言い換えてよい
- local entity なら、この corpus での使われ方に沿って説明する
- 分からないことを断定しない
- 「〜に関する概念」「〜を表す語」などの逃げすぎた説明は避ける
- ラベルそのものの単純な繰り返しだけで終わらせない

出力は必ず JSON のみ。

出力形式:
{"desc": "..." }
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--data-json",
        type=Path,
        default=None,
        help="Input curated data.json path (default: --data-dir/data.json)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Output path (default: overwrite --data-json)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model name",
    )
    parser.add_argument(
        "--only-weak",
        action="store_true",
        help="Only rewrite empty / mostly-ascii / too-short descriptions",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N target entities",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="If output exists, reuse already written desc values from it",
    )
    return parser.parse_args()


def mostly_ascii(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    visible = [c for c in stripped if not c.isspace()]
    if not visible:
        return False
    ascii_count = sum(1 for c in visible if ord(c) < 128)
    return ascii_count / len(visible) >= 0.85


def needs_refinement(desc: str) -> bool:
    stripped = (desc or "").strip()
    if not stripped:
        return True
    if mostly_ascii(stripped):
        return True
    if len(stripped) < 10:
        return True
    return False


def build_context_maps(data: dict) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    item_label_by_id = {item["id"]: item.get("label", "") for item in data.get("items", [])}

    surfaces_by_entity: dict[str, list[str]] = defaultdict(list)
    item_labels_by_entity: dict[str, list[str]] = defaultdict(list)

    for mention in data.get("mentions", []):
        entity_id = mention.get("entity_id", "").strip()
        if not entity_id:
            continue

        surface = (mention.get("mention") or "").strip()
        if surface and surface not in surfaces_by_entity[entity_id]:
            surfaces_by_entity[entity_id].append(surface)

        item_id = mention.get("item_id", "")
        item_label = item_label_by_id.get(item_id, "")
        if item_label and item_label not in item_labels_by_entity[entity_id]:
            item_labels_by_entity[entity_id].append(item_label)

    return surfaces_by_entity, item_labels_by_entity


def build_user_message(
    entity_id: str,
    label: str,
    desc: str,
    surfaces: list[str],
    item_labels: list[str],
) -> str:
    kind = "wikidata" if entity_id.startswith("Q") else "local"
    surface_text = ", ".join(surfaces[:6]) if surfaces else "（なし）"
    item_text = "\n".join(f"- {label}" for label in item_labels[:6]) if item_labels else "- （なし）"
    existing_desc = desc.strip() or "（なし）"

    return f"""\
entity_id: {entity_id}
kind: {kind}
label: {label}
existing_desc: {existing_desc}
surface_forms: {surface_text}

item_contexts:
{item_text}
"""


def call_llm(
    client: OpenAI,
    *,
    entity_id: str,
    label: str,
    desc: str,
    surfaces: list[str],
    item_labels: list[str],
    model: str,
    retries: int = 3,
) -> str:
    msg = build_user_message(entity_id, label, desc, surfaces, item_labels)
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": msg},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            payload = json.loads(resp.choices[0].message.content)
            refined = re.sub(r"\s+", " ", payload.get("desc", "")).strip()
            if refined:
                return refined
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"[LLM ERROR] {entity_id}: {exc}", file=sys.stderr)
    return desc.strip()


def main() -> None:
    cli = parse_args()
    cli.data_dir = cli.data_dir or DEFAULT_DATA_DIR
    cli.model = cli.model or LLM_MODEL
    cli.data_json = cli.data_json or cli.data_dir / "data.json"
    output_json = cli.output_json or cli.data_json

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    data = json.loads(cli.data_json.read_text())
    entities = data.get("entities", {})

    if cli.resume and output_json.exists():
        existing = json.loads(output_json.read_text())
        existing_entities = existing.get("entities", {})
        for entity_id, meta in entities.items():
            existing_desc = existing_entities.get(entity_id, {}).get("desc", "").strip()
            if existing_desc:
                meta["desc"] = existing_desc

    surfaces_by_entity, item_labels_by_entity = build_context_maps(data)

    targets: list[tuple[str, dict]] = []
    for entity_id, meta in entities.items():
        desc = meta.get("desc", "")
        if (not cli.only_weak) or needs_refinement(desc):
            targets.append((entity_id, meta))

    if cli.limit is not None:
        targets = targets[:cli.limit]

    print(f"target entities: {len(targets)}")

    for idx, (entity_id, meta) in enumerate(targets, start=1):
        label = meta.get("label", "").strip() or entity_id
        old_desc = meta.get("desc", "").strip()
        new_desc = call_llm(
            client,
            entity_id=entity_id,
            label=label,
            desc=old_desc,
            surfaces=surfaces_by_entity.get(entity_id, []),
            item_labels=item_labels_by_entity.get(entity_id, []),
            model=cli.model,
        )
        meta["desc"] = new_desc
        print(f"[{idx:02d}/{len(targets)}] {label}")
        print(f"  old: {old_desc or '∅'}")
        print(f"  new: {new_desc or '∅'}")

        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    print(f"\n完了: {output_json}")


if __name__ == "__main__":
    main()
