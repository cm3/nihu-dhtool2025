# kouchou-ai keyword-curation ワークフロー

CSV 形式のコメントデータを
[`digitaldemocracy2030/kouchou-ai`](https://github.com/digitaldemocracy2030/kouchou-ai)
の広聴AIレポート生成パイプラインにかけた中間出力を起点に、エネルギー政策コメントに出てくる
エンティティとその関係を整理するためのワークフローです。
広聴AIで生成した中間ファイルは、このリポジトリの `dataset/<dataset-name>/` に配置してから各スクリプトを実行します。
中間ファイルの探し方と配置方法は、詳細ページの「0. CSV を広聴AIで処理する」を参照してください。
Entity linking 候補生成では、L2 クラスタラベルに加えて takeaway も参照します。

詳細な説明は次のページを参照してください。

https://cm3.github.io/nihu-dhtool2025/

## 内容

- `index.qmd`: ワークフロー説明の元ファイル
- `scripts/`: entity linking 後の集計・分析スクリプト
- `dataset/energy-plan-pubcom-sample/`: サンプルデータセット
- `dataset/<dataset-name>/pair_relation_viewer.html`: 議論ビューアー

スクリプトは既定では `settings.py` の `DEFAULT_DATA_DIR` を読みます。
別データセットを一時的に使う場合は `--data-dir` で上書きできます。

```bash
python scripts/prepare_entity_candidates_no_draft.py --data-dir dataset/energy-plan-6th-7th-comparison
```

よく使うモデル名、microcluster の閾値、コメント件数なども `settings.py` にまとめています。

## セットアップ

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

## データに関する注意

- `dataset/energy-plan-pubcom-sample/` 以外のデータセットは Git 管理から除外しています。
- `dataset/` 以下の派生データにもコメント由来の要約・抜粋が含まれる場合があります。
- 公開前に、元データの公開条件と個人情報の有無を確認してください。

## ライセンス

- Code in `scripts/` and other software files is licensed under the MIT License.
- Documentation and report content, including `README.md`, `index.qmd`, and Quarto-generated pages, is licensed under Creative Commons Attribution 4.0 International (CC BY 4.0).
- Data files under `dataset/` are not covered by the software/documentation license grant unless separately stated.

See `LICENSE` for details.
