# kouchou-ai-keyword-curation-workflow

Quarto で `keyword-curation` 周辺の技術レポートを書くための作業用ディレクトリです。

含める想定:

- ワークフローの説明
- 技術メモ
- スライド
- 短い論文・報告書

主要ファイル:

- `_quarto.yml`: Quarto プロジェクト設定
- `index.qmd`: 入口ページ
- `slides.qmd`: スライド下書き
- `paper.qmd`: 論文・報告書下書き
- `scripts/`: entity linking 後の集計・分析スクリプト
- `data/`: レポートとビューアで参照する中間データ
- `pair_relation_viewer.html`: `data/pair_relations.json` と `data/entity_opinions.json` を見るための静的ビューア

レンダリング例:

```bash
cd vendor/kouchou-ai-keyword-curation-workflow
quarto render
```

Python スクリプトの依存関係:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

LLM を呼び出すスクリプトでは `OPENAI_API_KEY` が必要です。

```bash
export OPENAI_API_KEY=...
python scripts/prepare_entity_candidates_no_draft.py --help
```

注意:

- `data/comment_texts.json` は元コメント本文を含むため Git 管理から除外しています。
- `data/` 以下の派生データにもコメント由来の要約・抜粋が含まれる場合があります。
