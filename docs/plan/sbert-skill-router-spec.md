# SBERT Skill Router 仕様検討

## 目的

Yatagarasu の応答遅延を減らすため、LLM による Skill 選択の前段に SBERT ベースの Intent Router を置く。
ユーザー入力と事前登録された意図テンプレートを意味類似度で比較し、高信頼で判定できる操作は LLM を経由せずに Skill またはスクリプトを直接実行する。

この仕組みは、LLM を「思考・説明・曖昧な判断」へ集中させ、SBERT Router を「反射的なロボット制御」へ使うことを狙う。

## 現在実装されているスキル

Codex 用と Claude 用のスキル構成は同一。
実行候補としては Codex 用パス `.codex/skills/<skill>/` を基準に考える。

| Skill | 主な機能 | 主なスクリプト |
| --- | --- | --- |
| `move-camera` | Tapo カメラの PTZ 制御。左・右・上・下・座標移動・キャリブレーション | `.codex/skills/move-camera/scripts/ptz_control.sh` |
| `view` | go2rtc 経由でカメラ画像を取得し、保存または標準出力へ出力 | `.codex/skills/view/scripts/capture` |
| `tanechan-search` | SearXNG による Web 検索 | `.codex/skills/tanechan-search/scripts/search.sh` |
| `tanechan-fetch` | URL の本文取得・要約・抽出 | `.codex/skills/tanechan-fetch/scripts/fetch.sh` |
| `recall` | SemanticMemory から過去記憶を検索 | `.codex/skills/recall/scripts/recall.sh` |
| `memorize` | SemanticMemory へ長期記憶を保存 | `.codex/skills/memorize/scripts/memorize.sh` |
| `skill-creator` | AgentSkill の作成・更新ガイド | なし |

## 1. SBERT 実行対象スキルの選定案

### 判定基準

SBERT Router に向く Skill は、以下を満たすものを優先する。

- 入力表現が比較的短く、意図が明確
- 実行パラメータが少ない、または定型的に決められる
- 実行結果がすぐ得られる
- 誤爆時の被害が小さい
- LLM の判断を待つより、即時実行した方が体感速度に効く

逆に、以下は LLM 経由を基本とする。

- 入力の曖昧さが高い
- 実行前に推論・計画・複数手順の組み立てが必要
- URL 選択、要約方針、保存内容など、文脈判断が重要
- 誤爆すると記憶汚染や不要な外部アクセスにつながる

### 推奨分類

| Skill | SBERT 直接実行 | 結果を LLM へ渡す | 方針 |
| --- | --- | --- | --- |
| `move-camera` | 推奨 | 原則不要 | LLM Skill から外し、SBERT Router による反射制御へ移す |
| `view` | 推奨 | 必須 | 画像取得は SBERT Router で実行し、撮影画像を LLM へ渡して考察させる |
| `recall` | 推奨 | 必須 | 過去記憶の明示的な思い出しを SBERT Router で実行し、結果を LLM へ渡す |
| `tanechan-search` | 対象外 | なし | クエリ抽出と結果選択に文脈判断が必要なため、従来どおり LLM Skill に任せる |
| `tanechan-fetch` | 対象外 | なし | URL 選択や読み取り目的の判断が必要なため、従来どおり LLM Skill に任せる |
| `memorize` | 対象外 | なし | 記憶保存は誤爆被害が大きいため、従来どおり LLM Skill に任せる |
| `skill-creator` | 対象外 | なし | 開発支援用であり、音声操作の反射実行対象ではない |

### 最初に実装する候補

第1段階では、効果が大きく誤爆被害が小さいものに絞る。

#### `move-camera`

`move-camera` は LLM Skill から SBERT Router へ移す。
カメラの方向制御は定型的であり、LLM に判断させる必要がほぼないため、最優先で反射制御化する。

直接実行候補:

- `move_camera_left`
- `move_camera_right`
- `move_camera_up`
- `move_camera_down`
- `move_camera_calibrate`

想定入力:

- 左を向いて
- 右を見て
- ちょっと上
- 下に向けて
- キャリブレーションして
- カメラの位置を初期化して

複数ヒット:

- `move-camera` 系 Intent は複数同時ヒットを許可する
- 例: 「右向いて上向いて」は `move_camera_right` と `move_camera_up` の両方を実行する
- 実行順は入力順の推定を理想とするが、初期実装では固定順でもよい
- 固定順にする場合は `left/right` の水平移動を先、`up/down` の垂直移動を後にする
- `calibrate` は他の移動より優先し、同時に他の移動がヒットした場合は `calibrate` 後に移動するか、初期実装では `calibrate` のみ実行する

実行後の扱い:

- 単純な移動指示なら、Skill 実行だけで終了してよい
- 「右を向いて見えているものの状況を説明して」のような複合指示では、`move-camera` 実行後に `view` を実行し、撮影画像を LLM へ渡す

#### `view`

`view` は SBERT Router で画像取得を実行する。
初期実装では「ただ写真を撮るだけ」の用途は後回しにし、`view` が発動した場合は撮影画像を LLM へ渡して考察・説明させる前提にする。

直接実行候補:

- `capture_image`

想定入力:

- 今何が見える？
- 見て
- カメラで確認して
- 目の前を見て
- 見えているものを説明して
- 状況を教えて

実行後の扱い:

- `view` がヒットした場合は、画像取得後に LLM または画像分析へ渡す
- 「写真を撮って」だけの保存用途は初期実装では対象外とする
- `move-camera` と同時ヒットした場合は、必ず `move-camera` を先に実行し、その後で `view` を実行する

複合実行例:

| 入力 | SBERT Router の実行 | LLM への伝搬 |
| --- | --- | --- |
| 右を向いて | `move_camera_right` | なし |
| 右を向いて上を向いて | `move_camera_right` → `move_camera_up` | なし |
| 今何が見える？ | `capture_image` | 撮影画像と元の指示を渡す |
| 右を向いて見えているものを説明して | `move_camera_right` → `capture_image` | 撮影画像と元の指示を渡す |

#### `recall`

`recall` は明示的な過去記憶の思い出しを SBERT Router へ移す。
ただし、既存の「直近会話を取得して記憶継承する」処理はそのまま残す。
SBERT Router が扱うのは、ユーザーが過去の会話や記憶を明示的に参照した場合の追加 recall である。

直接実行候補:

- `recall_memory`

想定入力:

- 覚えてる？
- 前に話したことある？
- 〇〇について思い出して
- 記憶を探して

実行後の扱い:

- recall の結果だけで終了せず、原則 LLM へ渡して自然文応答を生成する
- recall 結果は SYSTEM プロンプトまたは追加コンテキストとして付与する
- LLM には「以下の記憶候補を参考に、ユーザーの質問に要約して返答せよ」という形で伝搬する
- 入力が短すぎる場合は、会話履歴または直近文脈を検索クエリに補う

### SBERT 対象外のスキル

#### `tanechan-search`

検索は効果が大きいが、クエリ抽出と結果選択が難しい。
SBERT Router の対象外とし、従来どおり LLM Skill に任せる。

想定入力:

- 〇〇を検索して
- 〇〇を調べて
- 今日の〇〇について調べて

実行後の扱い:

- 検索結果 JSON を LLM へ渡し、要約・選択・追加 fetch 判断を LLM に任せる

#### `tanechan-fetch`

URL 選択や読み取り目的の判断が必要なため、SBERT Router の対象外とする。
search 結果から fetch 対象を選ぶ処理も LLM に任せる。

#### `memorize`

明示トリガーは検出できるが、保存内容の抽出と確認が必要。
記憶汚染を避けるため、SBERT Router の対象外とする。

#### `skill-creator`

開発支援用 Skill であり、音声操作の反射実行対象ではない。
SBERT Router の対象外とする。

## 暫定結論

最初の実装対象は以下に絞る。

1. `move-camera`
2. `view`
3. `recall`

この3つで「首を振る」「見る」「思い出す」というロボット体験の遅延を直接削れる。
`move-camera` は LLM Skill から外して SBERT Router へ移す。
`view` は撮影後に LLM へ画像を渡す前提で実行する。
`recall` は既存の直近会話継承とは別に、明示的な過去記憶検索として SBERT Router へ移す。

`search`、`fetch`、`memorize`、`skill-creator` は SBERT Router の対象外とする。

## 2. 意図テンプレート設計案

### 基本方針

意図テンプレートは、ユーザー入力を SBERT で照合するための短い発話例セットである。
初期実装ではテンプレートを `.env` から登録できるようにし、コード変更なしで運用環境ごとの言い回しを調整できるようにする。

SBERT Router は以下の順で処理する。

1. ユーザー入力を受け取る
2. 有効化された Intent のテンプレートと意味類似度を計算する
3. 閾値を超えた Intent を抽出する
4. 実行順に並べる
5. Router で完結できるものは直接実行する
6. LLM への伝搬が必要なものは、実行結果と元の入力を LLM に渡す

### Intent 定義の構成

各 Intent は次の属性を持つ。

| 属性 | 説明 |
| --- | --- |
| `intent_id` | Router 内部で使う一意なID |
| `skill` | 対応する Skill 名 |
| `action` | Skill 内の具体的な動作 |
| `templates` | SBERT 照合に使う発話例 |
| `threshold` | 直接ヒットとみなす類似度閾値 |
| `allow_multi_hit` | 同じ入力で複数 Intent 実行を許可するか |
| `requires_llm` | 実行結果を LLM に渡す必要があるか |
| `priority` | 複数ヒット時の実行順 |

### `.env` での設定案

`.env` では、まずは単純な区切り文字形式を採用する。
JSON は表現力が高いが、音声ロボットの運用設定としては編集しづらいため、初期実装では避ける。

```bash
# SBERT Skill Router
YATAGARASU_SBERT_ROUTER_ENABLED="false"
YATAGARASU_SBERT_DRY_RUN="true"
YATAGARASU_SBERT_MODEL="cl-nagoya/ruri-v3-70m"
YATAGARASU_SBERT_DEVICE="cpu"
YATAGARASU_SBERT_OFFLINE="false"
YATAGARASU_SBERT_HIGH_THRESHOLD="0.78"
YATAGARASU_SBERT_MIDDLE_THRESHOLD="0.68"
YATAGARASU_SBERT_TOP_K="5"
YATAGARASU_SBERT_MOVE_TIMEOUT_SEC="8"
YATAGARASU_SBERT_MOVE_SETTLE_SEC="1.0"
YATAGARASU_SBERT_VIEW_TIMEOUT_SEC="10"
YATAGARASU_SBERT_RECALL_TIMEOUT_SEC="8"
GO2RTC_FRAME_API_ENABLED="true"

# Intent templates
# 値は | 区切り。運用環境で言い回しを足せる。
YATAGARASU_INTENT_MOVE_LEFT="左を向いて|左を見て|左に向けて|カメラを左|左側を見て"
YATAGARASU_INTENT_MOVE_RIGHT="右を向いて|右を見て|右に向けて|カメラを右|右側を見て"
YATAGARASU_INTENT_MOVE_UP="上を向いて|上を見て|上に向けて|カメラを上|上側を見て"
YATAGARASU_INTENT_MOVE_DOWN="下を向いて|下を見て|下に向けて|カメラを下|下側を見て"
YATAGARASU_INTENT_MOVE_CALIBRATE="キャリブレーションして|カメラを初期化して|カメラの位置を直して|位置合わせして"

YATAGARASU_INTENT_VIEW_SCENE="今何が見える|何が見える|見えているものを説明して|周りを見て|状況を教えて"
YATAGARASU_INTENT_VIEW_FACE="僕の顔を見て|顔を見て|表情を見て|こっちを見て|私の顔を確認して"
YATAGARASU_INTENT_VIEW_OBJECT="これを見て|これ何|この物を見て|手元を見て|見せているものを確認して"
YATAGARASU_INTENT_VIEW_DOCUMENT_READ="この書類を読んで|何が書いてある|文章を読んで|内容を教えて|これ読める"
YATAGARASU_INTENT_VIEW_DOCUMENT_SUMMARIZE="この書類を要約して|内容を要約して|ざっくりまとめて|要点を教えて|ポイントをまとめて"
YATAGARASU_INTENT_VIEW_DOCUMENT_TRANSLATE="これを和訳して|日本語に訳して|翻訳して|英語を訳して|この文章を訳して"
YATAGARASU_INTENT_VIEW_DOCUMENT_TRANSCRIBE="文字起こしして|書いてある文字をそのまま読んで|全文を読んで|テキストにして|OCRして"

YATAGARASU_INTENT_RECALL_SUMMARIZE="覚えてる|前に話したことをまとめて|記憶を要約して|思い出して説明して|前の話を整理して"
YATAGARASU_INTENT_RECALL_CONFIRM="前に言ったっけ|覚えてるか確認して|記憶にあるか見て|前に話したことある|聞いたことある"
YATAGARASU_INTENT_RECALL_TOPIC="について覚えてる|について思い出して|の記憶ある|について前に言った|について話したことある"
YATAGARASU_INTENT_RECALL_COMPARE="前と比べて|前回と違う|前に話した内容と比較して|記憶と照らして|前の情報と比べて"
YATAGARASU_INTENT_RECALL_CONTEXTUALIZE="前に話したことを踏まえて|覚えていることを参考に|記憶をもとに考えて|過去の話から判断して"
```

### `move-camera` Intent

初期バージョンの `move-camera` は固定ステップのみ対応する。

| Intent | 動作 | 移動量 | LLM 伝搬 |
| --- | --- | --- | --- |
| `move_camera_left` | 左へ向く | 45度 | 不要 |
| `move_camera_right` | 右へ向く | 45度 | 不要 |
| `move_camera_up` | 上へ向く | 30度 | 不要 |
| `move_camera_down` | 下へ向く | 30度 | 不要 |
| `move_camera_calibrate` | キャリブレーション | カメラ依存 | 不要 |

初期実装では以下は扱わない。

- 90度移動
- 10度移動
- 「ちょっとだけ」移動
- 「少し右」などの微調整
- 任意角度指定

90度動かしたい場合は、ユーザーが「右を向いて」を2回指示する。

複数ヒットは許可する。

例:

| 入力 | 実行 |
| --- | --- |
| 右を向いて | `move_camera_right` |
| 右向いて上向いて | `move_camera_right` → `move_camera_up` |
| 左を向いて下を見て | `move_camera_left` → `move_camera_down` |
| キャリブレーションして | `move_camera_calibrate` |

### `view` Intent のユースケース

`view` は単なる撮影ではなく、「撮影した画像を LLM に渡して理解する」ための入口として扱う。
初期実装では画像保存だけを目的にした Intent は作らない。

想定ユースケース:

| Intent | 目的 | 想定入力 | LLM への依頼 |
| --- | --- | --- | --- |
| `view_scene` | 全景・周囲状況の把握 | 今何が見える？ / 周りを見て / 状況を教えて | 画像全体を観察し、見えているものや状況を説明する |
| `view_face` | ユーザーの顔・表情の確認 | 僕の顔を見て / 表情を見て / こっちを見て | 顔や表情から読み取れる範囲を説明する |
| `view_object` | ユーザーが見せている物体の確認 | これを見て / これ何？ / 手元を見て | 中心付近または手前の物体を重点的に説明する |
| `view_document_read` | 書類・画面・印刷物の内容把握 | この書類を読んで / 何が書いてある？ / 内容を教えて | 画像内の文字を読み取り、内容を自然文で説明する |
| `view_document_summarize` | 文書の要約 | この書類を要約して / 要点を教えて / ざっくりまとめて | 画像内の文字を読み取り、要点を短くまとめる |
| `view_document_translate` | 文書の翻訳 | これを和訳して / 日本語に訳して / 翻訳して | 画像内の文字を読み取り、指定または推定された言語へ翻訳する |
| `view_document_transcribe` | 文書の文字起こし | 文字起こしして / 全文を読んで / テキストにして | 画像内の文字をできるだけ原文に近く転記する |

初期実装では、view 系 Intent はすべて同じ `capture_image` を実行する。
違いは LLM へ渡す追加指示で表現する。

例:

| 入力 | Router 実行 | LLM 追加指示 |
| --- | --- | --- |
| 今何が見える？ | `capture_image` | 画像全体の状況を説明する |
| 僕の顔を見て | `capture_image` | 顔や表情を中心に見る |
| これ何？ | `capture_image` | ユーザーがカメラに見せている物体を中心に見る |
| この書類を読んで | `capture_image` | 画像内の文字を読み取り、内容を自然文で説明する |
| この書類を要約して | `capture_image` | 画像内の文字を読み取り、要点を短くまとめる |
| これを和訳して | `capture_image` | 画像内の文字を読み取り、日本語へ翻訳する |
| 文字起こしして | `capture_image` | 画像内の文字をできるだけ原文に近く転記する |

`view_document_*` の細分化:

| Intent | LLM 追加指示 |
| --- | --- |
| `view_document_read` | 画像内の文字を読み取り、何が書かれているかを自然に説明してください。全文転記ではなく、ユーザーが内容を理解できる返答を優先してください。 |
| `view_document_summarize` | 画像内の文字を読み取り、重要な要点だけを短く要約してください。細部の逐語転記は不要です。 |
| `view_document_translate` | 画像内の文字を読み取り、日本語へ翻訳してください。原文が日本語の場合は、内容をわかりやすく言い換えてください。 |
| `view_document_transcribe` | 画像内の文字を、読み取れる範囲でできるだけ原文のまま転記してください。推測で補いすぎず、不明な箇所は不明と示してください。 |

`move-camera` と `view` が同時にヒットした場合は、先に `move-camera` を実行する。

例:

| 入力 | Router 実行 | LLM 追加指示 |
| --- | --- | --- |
| 右を向いて何が見えるか教えて | `move_camera_right` → `capture_image` | 移動後の画像全体を説明する |
| 上を向いて状況を教えて | `move_camera_up` → `capture_image` | 移動後の画像全体を説明する |

### `recall` Intent のユースケース

`recall` は、ユーザーが明示的に過去の会話や記憶を求めた場合に実行する。
通常の直近会話継承は既存処理に残し、SBERT Router では追加の過去記憶検索だけを扱う。

想定ユースケース:

| Intent | 目的 | 想定入力 | LLM への依頼 |
| --- | --- | --- | --- |
| `recall_summarize` | 思い出した内容を要約して返す | 覚えてる？ / 前に話したことをまとめて / 記憶を要約して | 関連記憶を整理し、短く要約して返す |
| `recall_confirm` | 記憶にあるか確認する | 前に言ったっけ？ / 聞いたことある？ / 記憶にあるか見て | 関連記憶の有無を答え、あれば根拠を短く示す |
| `recall_topic` | 特定トピックの記憶を思い出す | 〇〇について覚えてる？ / 〇〇の記憶ある？ | トピックに関係する記憶を要約して返す |
| `recall_compare` | 過去記憶と現在情報を比較する | 前と比べて / 前回と違う？ / 記憶と照らして | 過去の記憶と現在の入力や観測結果を比較する |
| `recall_contextualize` | 過去記憶を踏まえて返答する | 前に話したことを踏まえて / 記憶をもとに考えて | 関連記憶を背景情報として使い、現在の質問に答える |

recall の検索クエリ:

- `recall_topic` はユーザー入力全体をクエリにする
- `recall_summarize` と `recall_confirm` はユーザー入力が短すぎる場合、直近会話または現在の話題を補助クエリに加える
- `recall_compare` は現在の入力に加えて、直近の観測結果や `view` 結果があれば比較対象として LLM へ渡す
- `recall_contextualize` は recall 結果を背景情報として扱い、回答本文では必要な範囲だけ使う

LLM への伝搬形式:

```text
以下は SemanticMemory から取得した記憶候補です。
ユーザーの入力に直接関係するものだけを使い、短く要約して返答してください。
関係が薄い記憶は無理に使わないでください。
```

`recall_*` の細分化:

| Intent | LLM 追加指示 |
| --- | --- |
| `recall_summarize` | 関連する記憶候補を整理し、ユーザーが思い出せるように短く要約してください。 |
| `recall_confirm` | 関連する記憶があるかどうかをまず答えてください。ある場合は根拠となる記憶を短く示し、ない場合は断定しすぎず「見つからない」と答えてください。 |
| `recall_topic` | ユーザーが指定したトピックに関係する記憶だけを使い、要点を短くまとめてください。 |
| `recall_compare` | 記憶候補と現在の入力または観測結果を比較し、同じ点・違う点・判断できない点を分けて答えてください。 |
| `recall_contextualize` | 記憶候補を背景情報として使い、現在の質問に自然に答えてください。記憶そのものの列挙は必要最小限にしてください。 |

### 複数 Intent 実行の基本ルール

複数 Intent がヒットした場合は、以下の順で実行する。

1. `move-camera`
2. `view`
3. `recall`
4. LLM 応答生成

初期実装では `view` と `recall` が同時ヒットした場合、両方の結果を LLM へ渡す。

例:

| 入力 | Router 実行 | LLM へ渡すもの |
| --- | --- | --- |
| 右を向いて何が見えるか教えて | `move_camera_right` → `capture_image` | 撮影画像、元の入力 |
| 前に話した展示について覚えてる？今見えるものと関係ある？ | `capture_image` → `recall_memory` | 撮影画像、記憶候補、元の入力 |

### LLM パススルー抑制ルール

SBERT Router が1つでも Intent を検出した場合、ユーザー入力をそのまま通常プロンプトとして LLM に丸投げしない。
Router の判定結果を反映した制御プロンプトに変換してから LLM へ渡す。

理由:

- LLM が同じ Skill を再実行する二重発動を防ぐ
- SBERT Router が実行済みの結果を LLM に認識させる
- Middle 判定の Intent 候補を LLM に渡し、曖昧な場合だけ LLM Skill 発動へ逃がせる
- 「移動だけで終わる指示」と「移動後に説明が必要な指示」を明確に分ける

基本ルール:

| Router 判定 | Router 実行 | LLM への渡し方 |
| --- | --- | --- |
| High なし / Middle なし | なし | 従来どおりユーザー入力を LLM へ渡す |
| High あり / LLM 不要 | Skill 実行のみ | LLM へ渡さず終了する |
| High あり / LLM 必要 | Skill 実行 | 実行結果、元の入力、追加指示を LLM へ渡す |
| Middle のみ | なし | Intent 候補として LLM へ渡し、必要なら LLM Skill を使わせる |
| High と Middle が混在 | High は実行 | 実行結果と Middle 候補を LLM へ渡す |

LLM へ渡す制御プロンプト例:

```text
以下は SBERT Router が事前実行した結果です。
実行済み Skill を再実行しないでください。
必要な場合のみ、Middle 判定の Skill 候補を検討してください。

元のユーザー入力:
右を向いて何が見えるか教えて

実行済み:
- move_camera_right: success
- capture_image: /path/to/capture.jpg

追加指示:
撮影画像を見て、移動後に見えているものの状況を短く説明してください。
```

### 判定レベル

SBERT の類似度は2段階で扱う。

| レベル | 条件 | 挙動 |
| --- | --- | --- |
| High | `score >= high_threshold` | Router が直接実行する |
| Middle | `middle_threshold <= score < high_threshold` | 直接実行せず、LLM に Intent 候補として渡す |
| Low | `score < middle_threshold` | 通常どおり LLM へ渡す |

初期値案:

- `high_threshold = 0.78`
- `middle_threshold = 0.68`

実測で誤爆と取りこぼしを見ながら調整する。
