# Entity candidate recall from takeaways

## Background

現在の entity candidate 生成は、`prepare_entity_candidates.py` / `prepare_entity_candidates_no_draft.py` で
L2 クラスタの `label` のみを入力として使っている。

この設計は precision 寄りで、`64` 個の L2 ラベルから `150` 前後の mention を作るため、
抽象語を抑えやすい一方で、ラベルに出てこない技術語・施策語を落としやすい。

## Observations

- `断熱`
  - `2_53 建物の断熱基準強化と省エネ推進の必要性` では、初期下書き (`raw_result_step1.json`) には出ていた
  - ただし最終 `data.json` では `省エネルギー` のみが残り、`断熱` は落ちている
- `蓄熱発電`
  - 元 argument には存在する
  - L2 ラベルには出ていない
  - `2_60` の `takeaway` には出ている
  - そのため、現行の `label only` フローでは非常に落ちやすい

## Current interpretation

- `label only` は canonical で安定した entity を拾うにはよい
- ただし、ラベル化の段階で代表表現から漏れた語は EL 候補化の段階で救いにくい
- 特に単発・少数出現の技術語は不利

## Possible improvements

### Option A

Stage 1 の入力を `L2 label + L2 takeaway` にする。

- 最小の変更で recall を上げやすい
- `蓄熱発電` のような語はこの段階で救える可能性が高い
- 一方で抽象語も増えるので、prompt 側で「抽象評価語は除く」を今より明示する必要がある

### Option B

Stage 1 の入力を `L2 label + L2 takeaway + representative arguments` にする。

- `takeaway` にも載らない少数語をさらに拾いやすい
- ただし token 量が増え、ノイズも増える
- 実施するなら centroid 優先で 2〜3 件程度に絞るのがよさそう

### Option C

EL 用の entity 抽出と、補助 keyword 抽出を分離する。

- canonical な Wikidata / local entity
- 周辺技術語・施策語

を別出力にすることで、precision と recall のトレードオフを緩和できる可能性がある。

## Suggested next step

まずは Option A を試す。

- 対象: `L2 label + L2 takeaway`
- 比較指標:
  - mention 数
  - unique entity 数
  - `断熱`, `蓄熱発電` のような既知の取りこぼしが回収されるか
  - 抽象語の過剰流入がどの程度増えるか

必要ならその次に Option B を試す。
