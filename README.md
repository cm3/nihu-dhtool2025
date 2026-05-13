# kouchou-ai keyword-curation workflow

CSV 形式のコメントデータを
[`digitaldemocracy2030/kouchou-ai`](https://github.com/digitaldemocracy2030/kouchou-ai)
の broad listening pipeline にかけた中間出力を起点に、エネルギー政策コメントに出てくる
エンティティとその関係を整理するためのワークフローです。

詳細な説明は次のページを参照してください。

https://cm3.github.io/nihu-dhtool2025/

## Contents

- `index.qmd`: ワークフロー説明の元ファイル
- `scripts/`: entity linking 後の集計・分析スクリプト
- `data/`: レポートとビューアで参照する中間データ
- `pair_relation_viewer.html`: エンティティ関係の静的ビューア

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

LLM を呼び出すスクリプトでは `OPENAI_API_KEY` が必要です。

```bash
export OPENAI_API_KEY=...
```

Quarto サイトを生成する場合:

```bash
quarto render
```

GitHub Pages 用の `gh-pages` ブランチを更新する場合:

```bash
./scripts/publish_pages.sh
git push origin main
git push origin gh-pages
```

## Data Notes

- `data/comment_texts.json` は元コメント本文を含むため Git 管理から除外しています。
- `data/` 以下の派生データにもコメント由来の要約・抜粋が含まれる場合があります。
- 公開前に、元データの公開条件と個人情報の有無を確認してください。

## License

- Code in `scripts/` and other software files is licensed under the MIT License.
- Documentation and report content, including `README.md`, `index.qmd`, and Quarto-generated pages, is licensed under Creative Commons Attribution 4.0 International (CC BY 4.0).
- Data files under `data/` are not covered by the software/documentation license grant unless separately stated.

See `LICENSE` for details.
