# SBERT Skill Router システム設計

## 目的

`docs/plan/sbert-skill-router-spec.md` で定義した要件をもとに、SBERT Skill Router の実装方式を設計する。

## 1. 埋め込みモデル選定

### 現状

改修前のSemanticMemoryは`sentence-transformers`経由で
`cl-nagoya/ruri-small-v2`を使用していた。

ローカル確認結果:

- `external/SemanticMemory/src/db.py` の既定値は `SBERT_MODEL=cl-nagoya/ruri-small-v2`
- `external/SemanticMemory/src/chroma.py` は `SentenceTransformer(model_name, trust_remote_code=True)` でモデルをロードする
- SemanticMemory コンテナ内では `torch 2.11.0+cu130` が入っているが、`torch.cuda.is_available()` は `False`

改修前はCPUで推論しているにもかかわらず、依存としてCUDA付きPyTorchを持っていた。
現在はPyTorch公式CPU wheelを明示し、CUDA/NVIDIA依存を除外している。

### 候補比較

| モデル | パラメータ | 出力次元 | 最大長 | 依存 | コメント |
| --- | ---: | ---: | ---: | --- | --- |
| `cl-nagoya/ruri-small-v2` | 68M | 768 | 512 | `sentence-transformers`, `fugashi`, `sentencepiece`, `unidic-lite` | 既存 SemanticMemory と同じ。互換性と導入リスクが低い |
| `cl-nagoya/ruri-v3-30m` | 37M | 256 | 8192 | `transformers>=4.48.0`, `sentence-transformers`, `sentencepiece` | 最軽量。Intent Router 用には有力 |
| `cl-nagoya/ruri-v3-70m` | 70M | 384 | 8192 | `transformers>=4.48.0`, `sentence-transformers`, `sentencepiece` | v2 small と同規模で精度が高い。初期候補 |

### 判断

SBERT Skill Router は、SemanticMemory と同じベクトル空間で検索する必要はない。
Router が比較するのは「ユーザー入力」と「Intent テンプレート」であり、SemanticMemory の保存済み記憶ベクトルとは別用途である。

そのため、SemanticMemory と同じ `ruri-small-v2` に固定する必要はない。

初期設計では以下を推奨する。

1. Router の既定モデルは `cl-nagoya/ruri-v3-70m`
2. 依存や速度に問題が出た場合は `cl-nagoya/ruri-v3-30m` に落とす
3. SemanticMemory 側は当面 `cl-nagoya/ruri-small-v2` のまま変更しない

理由:

- Router 用途では長文検索より短文 Intent 判定が中心であり、SemanticMemory とのベクトル互換性は不要
- Ruri v3 は日本語埋め込み性能が高く、v3-70m は v2 small とほぼ同規模
- Ruri v3 は SentencePiece ベースで、v2 の `fugashi` / `unidic-lite` 依存を避けられる
- ただし v3 は `transformers>=4.48.0` が必要なため、既存環境との分離が望ましい

### CPU 依存方針

CUDA ライブラリを不要にするため、Router 用 Python 環境では CPU 版 PyTorch を明示的に導入する。

方針:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -U "transformers>=4.48.0" sentence-transformers sentencepiece
```

設計上の注意:

- `sentence-transformers` は PyTorch に依存する
- PyTorch を通常インストールすると環境によって CUDA 付き wheel が入る可能性がある
- CPU 専用にしたい場合は、PyTorch CPU wheel を先に入れる
- Router は `device="cpu"` を明示する

### 実装上の推奨

Router は SemanticMemory コンテナへ同居させず、Yatagarasu 側の独立した軽量 Python 環境として実装する。

理由:

- SemanticMemory の依存やモデル更新と Router の実験を分離できる
- Router は起動時に Intent テンプレートを埋め込み、以降は常駐またはキャッシュで高速化できる
- SemanticMemory の記憶DBを再構築する必要がない
- 将来 Router モデルだけ `ruri-v3-30m` / `ruri-v3-70m` で切り替えやすい

## 暫定結論

SBERT Skill Router は `cl-nagoya/ruri-v3-70m` を第一候補にする。
ただし、CPU負荷やインストールサイズが気になる場合は `cl-nagoya/ruri-v3-30m` を優先評価する。

SemanticMemory とRouterのモデル選定は分離する。SemanticMemoryを
`cl-nagoya/ruri-v3-70m`へ更新する場合は、768次元のv2ベクトルを流用せず、
SQLiteを正として384次元のベクトルを全件再構築する。

再構築は一時Chromaコレクションで完了・整合性確認してから切り替える。
Router側のベクトルは起動時にメモリ内生成されるため、SemanticMemoryの移行対象には
含まれない。

## 2. Intent テンプレート管理

### 配置方針

SBERT Skill Router は `listend.py` に組み込む。
`listend.py` は起動時に `YATAGARASU_CWD/.env` を読み込むため、Intent テンプレートも同じ `.env` から読み込む。

`.env` を変更した場合は `yatagarasu.service` を再起動し、起動時にテンプレートを再ロードする。

### ChromaDB を使うか

初期実装では、Intent テンプレート検索に ChromaDB は使わない。

理由:

- Intent テンプレートは数十件から多くても数百件程度であり、総当たり cosine similarity で十分速い
- ChromaDB の永続化・再作成・コレクション管理が増える
- `.env` 変更ごとに再作成するなら、永続DBの利点が小さい
- `listend` 起動時にテンプレートを埋め込み、メモリ上に保持すれば構成が単純

初期実装の構成:

```text
listend 起動
  ↓
.env 読み込み
  ↓
Intent テンプレート定義を構築
  ↓
ruri-v3-70m を CPU でロード
  ↓
テンプレート文を encode
  ↓
メモリ上に normalized embedding と Intent metadata を保持
  ↓
各 dispatch 前にユーザー入力を encode して cosine similarity
```

ChromaDB を検討する条件:

- Intent テンプレートが数千件以上になる
- ユーザーが動的に Intent を追加し、再起動なしで反映したい
- Intent 学習履歴やヒット統計をベクトルDBとして保存したい
- Skill 以外の大規模な意味ルーティングへ拡張する

### 起動時間への影響

起動時に重いのは ChromaDB の再作成ではなく、主に SBERT モデルロードである。
Intent テンプレートの埋め込み数が少なければ、テンプレート encode 自体は比較的軽い。

想定:

- 初回起動: Hugging Face からモデルをダウンロードするため遅い
- 2回目以降: ローカルキャッシュからモデルロードするため短縮される
- `.env` 変更後の再起動: モデルロード + テンプレート再encode が発生する

設計方針:

- 初期実装では起動時に毎回テンプレートを再encodeする
- 起動時間が問題になった場合のみ、テンプレート定義のハッシュをキーに embedding cache を導入する
- cache は `.env` のテンプレート値、モデル名、ルーター実装バージョンからハッシュを作って無効化する

### `.env` 変更耐性

`.env` で Intent テンプレートを編集できるようにする場合、起動時再構築は運用上わかりやすい。

運用フロー:

```text
workspace/.env の Intent テンプレートを編集
  ↓
systemctl --user restart yatagarasu
  ↓
listend 起動時にテンプレートを再読み込み
  ↓
SBERT Router の判定に反映
```

この方式では、起動中に `.env` を監視してホットリロードする必要はない。
音声監視プロセスでホットリロードを行うと、モデル再ロード中の認識遅延や状態不整合が起きやすいため、初期実装では避ける。

### Intent 定義の内部表現

`.env` から読み込んだテンプレートは、起動時に以下のような構造へ展開する。

```python
IntentDefinition(
    intent_id="move_camera_right",
    skill="move-camera",
    action="right",
    templates=["右を向いて", "右を見て", "右に向けて"],
    threshold=0.78,
    allow_multi_hit=True,
    allow_middle=True,
    requires_llm=False,
    priority=10,
)
```

`templates` は `|` 区切りで `.env` に記述する。
空のテンプレートは無効として扱う。

### 初期実装の結論

Intent Router は ChromaDB なしのメモリ内検索で実装する。
`.env` 変更は `listend` 再起動で反映する。

これにより、構成を単純に保ちながら、Intent テンプレートを運用環境で調整できる。

## 3. 残りの検討項目

### 3.1 Router をどこで実行するか

初期方針では `listend.py` に組み込む。
ただし、`listend.py` は音声監視・VAD・STT・状態管理をすでに担っているため、実装上は Router 本体を別モジュールに分離する。

推奨構成:

```text
python/listend.py
  - 音声監視
  - wake/stop 状態管理
  - dispatch 前に Intent Router を呼ぶ

python/intent_router.py
  - .env から Intent 定義を構築
  - SBERT モデルロード
  - 類似度判定
  - 実行計画を返す
```

### 3.2 Skill 実行をどこで行うか

Router が返すのは「実行計画」までにするか、Router 内で Skill 実行まで行うかを決める必要がある。

初期実装では、`intent_router.py` が実行計画を返し、`listend.py` 側が順序制御と dispatch 制御を行う。

理由:

- `listend.py` が最終的に LLM へ渡すかどうかを判断しやすい
- wake ack や dispatch timeout と同じ制御面に置ける
- Router を将来 CLI テストしやすい

### 3.3 実行フラグと順序制御

複数カテゴリの Intent は、カテゴリ跨ぎの特別分岐ではなくフラグ制御で扱う。

基本方針:

- Intent が High ヒットしたら対応する実行フラグを立てる
- 立っているフラグを固定順にすべて実行する
- `move-camera` は方向ごとの複数フラグを許可する
- `view` と `recall` も `move-camera` と同時に立てられる
- LLM へ渡すプロンプトは、立っていたフラグと実行結果から組み立てる

実行順:

1. `move_camera_calibrate`
2. `move_camera_left` / `move_camera_right`
3. `move_camera_up` / `move_camera_down`
4. `capture_image`
5. `recall_memory`
6. LLM 応答生成

例:

| 入力 | 立つフラグ | 実行 |
| --- | --- | --- |
| 右を向いて | `move_camera_right` | 右へ45度 |
| 右を向いて上を向いて | `move_camera_right`, `move_camera_up` | 右へ45度 → 上へ30度 |
| 右を向いて何が見えるか教えて | `move_camera_right`, `view_scene` | 右へ45度 → 撮影 → LLM |
| 前に話した展示について覚えてる？今見えるものと関係ある？ | `view_scene`, `recall_compare` | 撮影 → 記憶検索 → LLM |

同一カテゴリ内の扱い:

- `move-camera`: 複数方向を許可する
- `view`: 複数の読み方を許可する場合と、専用複合 Intent にまとめる場合を分ける
- `recall`: 原則最高スコア1件。ただし将来、複合 Intent が必要なら追加する

### 3.4 LLM へ渡すプロンプト形式

SBERT Router が1つでもヒットした場合、元の入力をそのまま LLM へ渡さない。
実行済み Skill、Middle 候補、元入力、追加指示を含む制御プロンプトへ変換する。

検討する出力:

- `move-camera` の実行結果
- `view` の画像パス
- `recall` の記憶候補
- Middle 判定の Intent 候補
- LLM に再実行させてはいけない Skill

制御プロンプトはフラグ実行結果から構築する。

```text
元のユーザー入力:
...

SBERT Router 判定:
- High: move_camera_right
- High: view_scene
- Middle: recall_contextualize

実行済み:
- move_camera_right: success
- capture_image: /absolute/path/to/capture.jpg

禁止:
- 実行済み Skill を再実行しない

追加指示:
- 撮影画像を見て、移動後の状況を説明する
- Middle 候補は必要な場合だけ検討する
```

### 3.5 `view` 画像を Codex CLI にどう渡すか

`view` は撮影後に LLM へ画像を渡す前提である。
Codex CLI に画像を渡す方法を設計する必要がある。

候補:

- `codex exec -i <image>` を使う
- 画像パスをプロンプトに書き、Codex 側の Skill に読ませる
- 画像分析用の別処理を先に走らせ、結果テキストだけ LLM に渡す

初期実装では、撮影した画像の絶対パスを LLM 制御プロンプトへ組み込む。

理由:

- 現在の `bin/yatagarasu` は Codex CLI の `-i` 画像入力を使っていない
- 絶対パスを渡せば、Codex がローカルファイルとして参照しやすい
- Claude / opencode など他エンジンとの互換性も保ちやすい

注意:

- 画像パスを渡すだけでモデルが必ず画像内容を理解できるとは限らない
- Codex CLI の画像入力 `-i` が安定して使える場合は、将来 `bin/yatagarasu` に画像引数対応を追加する
- 初期実装では「画像絶対パス + 画像を読む明示指示」をプロンプトへ入れる

制御プロンプト例:

```text
撮影画像:
/home/tane/tools/yatagarasu/workspace/media/capture_20260718_120000.jpg

上記の画像を確認し、ユーザーの元の指示に答えてください。
```

### 3.6 複合 Intent

複数 Intent を単純にフラグ合成するだけでは、LLM 追加指示が曖昧になるケースがある。
その場合は専用の複合 Intent を定義する。

初期候補:

| 複合 Intent | 想定入力 | Router 実行 | LLM 追加指示 |
| --- | --- | --- | --- |
| `view_document_summarize_translate` | この書類を要約して和訳して | `capture_image` | 画像内の文章を読み取り、日本語へ翻訳したうえで要点を短くまとめる |
| `view_document_transcribe_translate` | 文字起こしして和訳して | `capture_image` | 原文を転記し、その後に日本語訳を付ける |
| `view_scene_recall_compare` | 前と比べて今どう？ | `capture_image` → `recall_memory` | 現在の画像と過去記憶を比較する |

`view_document_summarize` と `view_document_translate` が両方ヒットした場合、初期実装では `view_document_summarize_translate` として扱う。

### 3.7 複数 Intent の衝突処理

複数ヒットは原則許可する。
初期実装では、複雑な衝突処理は実装しない。

例:

- 「右向いて左向いて」
- 「上向いて下向いて」
- `view_scene` と `view_document_translate` の同時ヒット
- `recall_summarize` と `recall_confirm` の同時ヒット

初期案:

- `move-camera` は複数実行を許可する
- 「右向いて左向いて」「上向いて下向いて」は矛盾ではなく、ロボットの首振りジェスチャーとして許可する
- 同一カテゴリの `view_*` は、複合 Intent に変換できる場合は変換し、できない場合は最高スコア1件に絞る
- 同一カテゴリの `recall_*` は、原則最高スコア1件に絞る
- カテゴリ跨ぎはフラグ制御により同時実行を許可する

懸念事項:

- 複数 Intent の組み合わせにより、LLM 追加指示が曖昧になる可能性がある
- 同一カテゴリの `view_*` が複数ヒットした場合、ユーザーの本当の意図と違う読み方を選ぶ可能性がある
- `recall_*` が複数ヒットした場合、返答方針がぶれる可能性がある

初期実装では、これらを厳密に解決しない。
判定ログを残し、実運用で問題が見えた Intent のみ個別に複合 Intent 化または抑制ルールを追加する。

### 3.8 類似度閾値のチューニング

`high_threshold=0.78`、`middle_threshold=0.68` は仮値である。
実運用の発話ログで調整する。

必要なログ:

- 入力テキスト
- 上位 Intent 候補
- 類似度スコア
- High/Middle/Low 判定
- 実行した Skill
- LLM へ渡したかどうか

### 3.9 誤爆時の安全策

初期対象は低リスクだが、誤爆対策は必要。

方針:

- `move-camera` のみ LLM 不要で完結可能
- `view` と `recall` は原則 LLM へ渡す
- `calibrate` は強めの閾値を使うか、専用テンプレートのみ許可する
- Router 無効化フラグを `.env` に置く
- ログで直近判定を確認できるようにする

### 3.10 発話フィードバック制御

SBERT Router により LLM を呼ばずに完結する場合、原則として追加発話しない。

初期実装の方針:

| ケース | 発話 |
| --- | --- |
| `move-camera` 単体で完結 | なし |
| `move-camera` 複数実行で完結 | なし |
| `move-camera` 後に `view` へ進み、LLM へ渡す | LLM 呼び出し前に従来どおり `考えるね` |
| `view` 単体で LLM へ渡す | LLM 呼び出し前に従来どおり `考えるね` |
| `recall` を LLM へ渡す | LLM 呼び出し前に従来どおり `考えるね` |
| Middle 判定のみで LLM へ渡す | LLM 呼び出し前に従来どおり `考えるね` |

理由:

- 首振りだけの動作で発話すると、テンポが悪くなる
- ロボットの身体動作そのものがフィードバックになる
- LLM 応答が必要な場合だけ「考えるね」を発話すれば、待ち時間の予告として機能する

### 3.11 テスト方法

実装前に、音声入力なしで Router 判定だけを試せる CLI が必要。

候補:

```bash
python/intent_router.py "右を向いて何が見えるか教えて"
```

期待出力:

```json
{
  "hits": [
    {"intent_id": "move_camera_right", "level": "high", "score": 0.91},
    {"intent_id": "view_scene", "level": "high", "score": 0.84}
  ],
  "plan": ["move_camera_right", "capture_image"],
  "requires_llm": true
}
```

## 4. コーディング仕様

### 4.1 実装ファイル

初期実装で追加・変更するファイル:

| ファイル | 内容 |
| --- | --- |
| `python/intent_router.py` | SBERT Router 本体。Intent定義、モデルロード、類似度判定、実行計画作成、CLIテスト |
| `python/listend.py` | dispatch直前に Router を呼び、Skill実行・LLM制御プロンプト生成を行う |
| `python/requirements.txt` または導入手順 | CPU Torch / sentence-transformers / transformers / sentencepiece の導入を追記 |
| `workspace/.env.example` | SBERT Router 設定と Intent テンプレート既定値を追加 |
| `docs/plan/sbert-skill-router-system-design.md` | 設計更新 |

### 4.2 `intent_router.py` の責務

`intent_router.py` は判定専用モジュールとする。
Skill 実行、画像撮影、記憶検索、LLM dispatch は行わない。

責務:

- `.env` / `os.environ` から Router 設定を読む
- Intent 定義を構築する
- `cl-nagoya/ruri-v3-70m` を CPU でロードする
- 起動時にテンプレートを encode する
- 入力テキストを encode する
- cosine similarity を計算する
- High / Middle / Low を分類する
- 実行フラグと LLM 追加指示を含む `RouterDecision` を返す
- CLI 実行時は JSON を出力する

非責務:

- `ptz_control.sh` の実行
- `capture` の実行
- `recall.sh` の実行
- `yatagarasu` / Codex CLI の呼び出し
- 音声フィードバック再生

### 4.3 データ構造

実装では `dataclass` を使う。

```python
@dataclass(frozen=True)
class IntentDefinition:
    intent_id: str
    category: str
    skill: str
    action: str
    templates: tuple[str, ...]
    threshold: float
    allow_multi_hit: bool
    allow_middle: bool
    requires_llm: bool
    priority: int
    llm_instruction: str


@dataclass(frozen=True)
class IntentHit:
    intent_id: str
    category: str
    score: float
    level: str  # high / middle
    matched_template: str
    requires_llm: bool
    llm_instruction: str


@dataclass(frozen=True)
class RouterDecision:
    enabled: bool
    original_text: str
    high_hits: tuple[IntentHit, ...]
    middle_hits: tuple[IntentHit, ...]
    flags: tuple[str, ...]
    requires_llm: bool
    llm_instructions: tuple[str, ...]
```

`flags` は `listend.py` が実行できるアクション名にする。

例:

```text
move_camera_right
move_camera_up
capture_image
recall_memory
```

### 4.4 Router 設定

`.env.example` に追加する設定:

```bash
YATAGARASU_SBERT_ROUTER_ENABLED="false"
YATAGARASU_SBERT_MODEL="cl-nagoya/ruri-v3-70m"
YATAGARASU_SBERT_DEVICE="cpu"
YATAGARASU_SBERT_OFFLINE="false"
YATAGARASU_SBERT_HIGH_THRESHOLD="0.78"
YATAGARASU_SBERT_MIDDLE_THRESHOLD="0.68"
YATAGARASU_SBERT_TOP_K="5"
YATAGARASU_SBERT_DRY_RUN="true"
YATAGARASU_SBERT_MOVE_TIMEOUT_SEC="8"
YATAGARASU_SBERT_MOVE_SETTLE_SEC="1.0"
YATAGARASU_SBERT_VIEW_TIMEOUT_SEC="10"
YATAGARASU_SBERT_RECALL_TIMEOUT_SEC="8"
```

`YATAGARASU_SBERT_DEVICE` は初期値 `cpu` 固定。
GPU は初期実装では対象外。
`YATAGARASU_SBERT_OFFLINE=true` の場合は、キャッシュ済みモデルだけを使い、Hugging Face への確認通信を行わない。
`YATAGARASU_SBERT_DRY_RUN` は Router 判定ログだけを出し、Skill 実行とプロンプト変換を行わない検証用フラグである。

Intent テンプレートは `|` 区切り。

### 4.5 Intent 定義

初期実装で持つ Intent:

| Intent | Category | Flag | LLM |
| --- | --- | --- | --- |
| `move_camera_left` | `move` | `move_camera_left` | 不要 |
| `move_camera_right` | `move` | `move_camera_right` | 不要 |
| `move_camera_up` | `move` | `move_camera_up` | 不要 |
| `move_camera_down` | `move` | `move_camera_down` | 不要 |
| `move_camera_calibrate` | `move` | `move_camera_calibrate` | 不要 |
| `view_scene` | `view` | `capture_image` | 必要 |
| `view_face` | `view` | `capture_image` | 必要 |
| `view_object` | `view` | `capture_image` | 必要 |
| `view_document_read` | `view` | `capture_image` | 必要 |
| `view_document_summarize` | `view` | `capture_image` | 必要 |
| `view_document_translate` | `view` | `capture_image` | 必要 |
| `view_document_transcribe` | `view` | `capture_image` | 必要 |
| `view_document_summarize_translate` | `view` | `capture_image` | 必要 |
| `view_document_transcribe_translate` | `view` | `capture_image` | 必要 |
| `recall_summarize` | `recall` | `recall_memory` | 必要 |
| `recall_confirm` | `recall` | `recall_memory` | 必要 |
| `recall_topic` | `recall` | `recall_memory` | 必要 |
| `recall_compare` | `recall` | `recall_memory` | 必要 |
| `recall_contextualize` | `recall` | `recall_memory` | 必要 |

### 4.6 判定アルゴリズム

起動時:

1. `RouterSettings.from_env()` を作る
2. `IntentDefinition` を構築する
3. 空テンプレートの Intent を除外する
4. 全テンプレートを1次元リストへ展開する
5. `SentenceTransformer(model_name, device="cpu")` をロードする
6. テンプレートを encode し、normalize 済み embedding を保持する

dispatch前:

1. 入力テキストを normalize せず、そのまま SBERT encode する
2. 入力 embedding とテンプレート embedding を単位ベクトルに normalize する
3. normalize 済み embedding 同士の dot product を取り、cosine similarity として扱う
4. 判定補助用にだけ、入力テキストを NFKC・小文字化・カタカナひらがな寄せ・句読点除去で軽く正規化する
5. 方向抽出など語句ゲートを明示した Intent だけ、`gate_terms` が入力に含まれなければ候補から除外する
6. Intent ごとに最高スコアのテンプレートを採用する
7. `score >= high_threshold` を High とする
8. `allow_middle=True` の Intent だけ、`middle_threshold <= score < high_threshold` を Middle とする
9. High hit をカテゴリごとの採用規則で整理する
10. High hit から flags を構築する
11. Middle hit は LLM 候補として保持する
12. `requires_llm` を決定する

注意:

- SBERT では表記ゆれを吸収したいため、原則として入力テキストの強い正規化はしない
- `view_scene` は天気・ニュース・予定との意味的な近さや、Move-only 指示の「向く／見る」との曖昧性があるため、専用 High 閾値 `0.90` と `allow_middle=False` を使う
- `view_scene` の `gate_terms` は `見え`、`映`、`何が`、`周り`、`目の前`、`カメラ`など、現在視界の説明要求を示す語に限定する。これにより「右を向いて」「右を見て」はMoveだけ、「右を向いて何が見える」はMove+Viewとして扱う
- `gate_terms` は、方向スロットの抽出や、意味類似度だけでは分離できない近接Intentの適用条件に限定して使う
- 複合 Intent は `gate_required_groups` で「要約系 + 翻訳系」「転記系 + 翻訳系」のようなAND条件を持てる。これにより、単なる「翻訳して」が `文字起こしして和訳して` に誤分類されるのを防ぐ
- Ruri v3 の prefix は Intent 判定では付けない。これは検索クエリ/検索文書ではなく、短文同士の意味類似度判定として扱うため
- Score は cosine similarity に統一する。ベクトル距離は閾値調整が直感的でないため初期実装では使わない
- `SentenceTransformer.encode(..., normalize_embeddings=True)` を使い、テンプレート・入力の両方を normalize する
- ログ表示用には `listend.py` 既存の normalize 関数を使ってよい
- テンプレート同士は短文なので、encode 時は `show_progress_bar=False` にする

### 4.7 High hit から flags への変換

基本:

- `move_camera_*` はヒットした分だけ flags に入れる
- `view_*` は1つ以上ヒットしたら `capture_image` を1回だけ入れる
- `recall_*` は1つ以上ヒットしたら `recall_memory` を1回だけ入れる

重複排除:

```text
view_scene + view_document_read -> capture_image は1回
recall_topic + recall_compare -> recall_memory は1回
```

High hit の採用規則:

- `move` は複数採用する。`右を向いて左を向いて` のような首振り動作を許可する
- 複数の `move` は、固定順ではなく入力テキストに現れた順序で実行する
- `view` は原則1件に絞る。`view_document_summarize_translate` などの複合 Intent があれば、それを優先する
- `recall` は原則最高スコア1件に絞る

実行順は `intent_router.py` の `ACTION_ORDER` で固定し、`listend.py` はその順序で実行する。

```python
ACTION_ORDER = (
    "move_camera_calibrate",
    "move_camera_left",
    "move_camera_right",
    "move_camera_up",
    "move_camera_down",
    "capture_image",
    "recall_memory",
)
```

### 4.8 `listend.py` 組み込み位置

既存の `_dispatch_session()` は以下の流れで動く。

```text
session_text_chunks を結合
logging.info("dispatch session ...")
self._dispatch(text)
last_wake_ack_at 更新
```

Router は `_dispatch(text)` の直前に挟む。

新しい流れ:

```text
session_text_chunks を結合
logging.info("dispatch session ...")

if router enabled:
    decision = router.route(text)
    if decision has High/Middle:
        if dry-run:
            log decision
            self._dispatch(text)
            return
        result = self._execute_router_decision(decision)
        if result.completed_without_llm:
            return
        text = build_control_prompt(text, decision, result)

play "考えるね"
self._dispatch(text)
last_wake_ack_at 更新
```

撮影画像を LLM へ渡す dispatch では、過去の画像説明が現在画像の認識を
上書きしないよう SemanticMemory の自動リコールだけを停止する。現在の
ユーザー発話と応答の保存は継続し、一般会話・Recall Intent の記憶処理は
従来どおり維持する。

### 4.9 Skill 実行仕様

`listend.py` に Router 実行用の補助メソッドを追加する。

```python
def _execute_router_decision(self, decision: RouterDecision) -> RouterExecutionResult:
    ...
```

`RouterExecutionResult`:

```python
@dataclass(frozen=True)
class RouterExecutionResult:
    completed_without_llm: bool
    executed_actions: tuple[ActionResult, ...]
    image_path: str | None
    recall_text: str | None
    errors: tuple[str, ...]
```

`ActionResult`:

```python
@dataclass(frozen=True)
class ActionResult:
    action: str
    ok: bool
    stdout: str
    stderr: str
    elapsed_sec: float
```

実行コマンド:

| Action | Command |
| --- | --- |
| `move_camera_left` | `PTZ worker -> moveMotor(-45, 0)` |
| `move_camera_right` | `PTZ worker -> moveMotor(45, 0)` |
| `move_camera_up` | `PTZ worker -> moveMotor(0, 30)` |
| `move_camera_down` | `PTZ worker -> moveMotor(0, -30)` |
| `move_camera_calibrate` | `PTZ worker -> calibrateMotor()` |
| `capture_image` | `<workspace>/.codex/skills/view/scripts/capture` |
| `recall_memory` | `<workspace>/.codex/skills/recall/scripts/recall.sh "<query>"` |

Router 経由の `move-camera` は `ptz_worker` を優先する。
`ptz_worker` はスキル配下 `.venv` の Python で常駐し、`pytapo` import と Tapo 接続/認証を初回だけ行う。
これにより、音声指示ごとに Python 起動・import・ログインを繰り返さず、move 実行を `moveMotor()` 本体の時間に近づける。

通常の Skill / CLI 経由では従来どおり `ptz_control.sh` も使える。
`ptz_control.sh` はスキル配下に `.venv` があればそれを優先し、専用 `.venv` がない開発環境では `uv run` へフォールバックする。

`capture_image` は `GO2RTC_FRAME_API_ENABLED=true` の場合、go2rtc の HTTP frame API (`/api/frame.jpeg?src=<stream>`) を優先する。
取得したJPEGを ffmpeg で指定サイズへリサイズし、失敗時のみ従来の RTSP 1フレーム取得へフォールバックする。

実行タイムアウト:

```bash
YATAGARASU_SBERT_MOVE_TIMEOUT_SEC="8"
YATAGARASU_SBERT_MOVE_SETTLE_SEC="1.0"
YATAGARASU_SBERT_VIEW_TIMEOUT_SEC="10"
YATAGARASU_SBERT_RECALL_TIMEOUT_SEC="8"
```

`YATAGARASU_SBERT_MOVE_SETTLE_SEC` は、PTZ 移動の後にまだ次の Router action がある場合だけ挿入する待機秒数である。
Tapo API は `moveMotor()` の応答が返っても物理モーターの移動完了を厳密には通知しないため、複合 move や move→view の安定化に使う。

### 4.10 LLM 要否判定

LLM を呼ばずに終了する条件:

- High hit が `move-camera` 系のみ
- Middle hit がない
- Skill 実行がすべて成功

LLM を呼ぶ条件:

- `capture_image` を実行した
- `recall_memory` を実行した
- Middle hit が1件以上ある
- Router 実行中にエラーがあり、ユーザーへ説明が必要

`move-camera` 単体で一部失敗した場合:

- 初期実装では LLM を呼ばず、ログにエラーを残す
- ユーザーへの音声通知はしない

### 4.11 「考えるね」再生タイミング

LLM を呼ぶことが確定した後、`_dispatch(text)` の前に既存の `LISTEND_WAKE_ACK_WORD` を再生する。

改訂前の `listend.py` は ON 遷移時に `LISTEND_WAKE_ACK_WORD` を再生していた。
現行実装では、Router 有効/無効にかかわらず LLM dispatch 直前へ移している。

変更後の方針:

- ON 遷移時には `考えるね` を再生しない
- LLM dispatch が必要だと確定した場合だけ、dispatch 直前に既存の `LISTEND_WAKE_ACK_WORD` を再生する
- Router 無効時も dispatch 直前に再生する
- Router 無効時は wake 後に必ず通常 dispatch へ進むため、体感挙動は従来とほぼ同じになる

実装案:

- 新しい発話用環境変数は追加しない
- 既存の `LISTEND_WAKE_ACK_WORD`、`LISTEND_WAKE_ACK_SPEAKER_ID`、`LISTEND_WAKE_ACK_TIMEOUT_SEC`、`LISTEND_WAKE_ACK_ZUNDA_CMD`、`LISTEND_WAKE_ACK_TAPOVOICE_CMD` をそのまま使う
- `_set_state(ON)` では `_play_wake_ack()` を呼ばない
- `_dispatch(text)` を呼ぶ直前で `_play_wake_ack()` を呼ぶ
- 再生失敗時はログ警告のみで LLM dispatch は継続する

wake ack pending:

- ON 遷移時に再生しないため、ON 遷移時の pending は不要になる
- dispatch 直前に同期的に再生を試みる
- 再生失敗時に pending 再試行するかは初期実装では不要。ログ警告のみでよい

### 4.12 制御プロンプト生成

`build_control_prompt()` を `listend.py` または小さな別モジュールに実装する。

入力:

- 元ユーザー入力
- `RouterDecision`
- `RouterExecutionResult`

出力:

- `yatagarasu` に渡す文字列

テンプレート:

```text
以下は SBERT Skill Router による前処理結果です。
実行済みの操作を再実行しないでください。

元のユーザー入力:
{original_text}

実行済み操作:
{executed_actions}

撮影画像:
{image_path}

記憶検索結果:
{recall_text}

Middle判定のIntent候補:
{middle_hits}

追加指示:
{llm_instructions}
```

この制御プロンプトはLLM実行専用とする。SemanticMemoryの自動リコールに使う
検索語と、応答後に保存する`[user]`本文には`original_text`を使用し、
Routerの実行結果や内部指示を会話記憶として保存しない。

「さっき」「先ほど」「直前」「今の話」など、直近ターンを参照する入力では、
古い意味類似記憶より`recent_history`を優先する。特定トピックが明示された
通常の`recall_topic`では、従来どおり意味検索を使用する。

`image_path` は必ず絶対パスにする。

### 4.13 ログ仕様

INFO:

- Router enabled / disabled
- Router model loaded
- Intent template count
- dispatch ごとの High / Middle hit
- 実行 flags
- completed_without_llm / requires_llm

DEBUG:

- 上位 `top_k` Intent と score
- matched_template
- action stdout/stderr の短縮版

WARNING:

- モデルロード失敗
- Skill 実行失敗
- capture 失敗
- recall 失敗

Router 初期化失敗時:

- エラーをログに出す
- Router disabled として listend は従来動作を続ける

### 4.14 CLI 仕様

`intent_router.py` は単体で動く。

```bash
YATAGARASU_CWD=/home/tane/tools/yatagarasu/workspace \
  python/intent_router.py "右を向いて何が見える？"
```

オプション:

```text
--json          JSON出力
--top-k N       上位候補数
--no-model      モデルロードせずIntent定義だけ表示
--list-intents  Intent一覧表示
```

既定出力は JSON。

### 4.15 テスト仕様

単体テスト:

- `.env` テンプレート読み込み
- 空テンプレート除外
- Intent 定義数
- 複数 move hit の flags
- view hit 時 `requires_llm=True`
- move only 時 `requires_llm=False`
- Middle only 時 `requires_llm=True`
- `capture_image` 重複排除
- `recall_memory` 重複排除
- `view_document_summarize_translate` の複合 Intent

手動テスト:

```bash
python/intent_router.py "右を向いて"
python/intent_router.py "右を向いて上を向いて"
python/intent_router.py "今何が見える？"
python/intent_router.py "この書類を要約して和訳して"
python/intent_router.py "前に話した展示について覚えてる？今見えるものと関係ある？"
```

### 4.16 実装順序

1. `python/intent_router.py` をCLI付きで実装する
2. `.env.example` にRouter設定とテンプレートを追加する
3. CPU Torch 導入手順を docs に追記する
4. CLIでIntent判定を手動評価する
5. `listend.py` にRouter初期化だけ組み込む
6. `listend.py` にRouter判定ログだけ出す dry-run モードを追加する
7. `move-camera` 実行を組み込む
8. `view` 実行と制御プロンプト生成を組み込む
9. `recall` 実行を組み込む
10. `考えるね` 再生タイミングを調整する

初期実装では `YATAGARASU_SBERT_ROUTER_ENABLED="false"` を既定にし、手動で有効化する。
