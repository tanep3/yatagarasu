# LiveKit WakeWord対応 要件定義 v0.3

- 作成日: 2026-07-27
- 対象: `python/listend.py` のウェイクワード検出
- 対象リリース: 次期Yatagarasu
- 既定ウェイクワード: 「ねぇ、ヤタガラス」

## 1. 背景

現在のYatagarasuは、OFF状態の発話をSTTで文字起こしし、
`LISTEND_WAKE_WORDS`との文字列一致によってウェイクを判定している。

この方式には次の課題がある。

- STTの日本語認識結果にウェイク判定精度が左右される。
- OFF状態でも発話ごとにSTTを実行するため、CPU負荷と検出遅延が発生する。
- 表記揺れを`.env`へ列挙する必要がある。
- ウェイクワードだけを発話した場合に、命令待機へ自然に移行できない。

ウェイク判定を専用ONNXモデルへ移し、STTを命令認識へ専念させる。

## 2. ゴール

- 「ねぇ、ヤタガラス」を専用ONNXモデルで検出する。
- ウェイク検出後、同梱済みの「はい」音声を即時再生する。
- フィードバック再生後に命令音声を録音し、無音確定後にSTTへ渡す。
- OFF状態の通常発話ではSTTを起動しない。
- CPUのみの環境で常時運用できる。
- 従来のSTTウェイク方式を明示的な互換バックエンドとして残す。
- 標準設定とコード上の既定バックエンドをONNX方式とし、`.env`でSTT方式へ切り替えられる。
- 第8世代Core i7のCPUのみの環境で、待機時の追加CPU使用率を平均5%以下に抑えることを
  性能目標とする。
- Yatagarasuの標準話者をVOICEVOXの青山龍星へ変更する。

## 3. 採用コンポーネント

### 3.1 ウェイクワード実行基盤

- ライブラリ: `livekit-wakeword`
- 上流: https://github.com/livekit/livekit-wakeword
- ライセンス: Apache-2.0
- 使用API: `WakeWordModel`
- 使用しない機能: `WakeWordListener`
  - Yatagarasuはマイクを直接開かず、既存のRTSP音声を使用する。
  - `listener` optional dependencyのPyAudioは導入しない。
- 実行Provider: ONNX Runtime `CPUExecutionProvider`

### 3.2 ウェイクワードモデル

- 論理名: `nee_yatagarasu`
- 対象フレーズ: 「ねぇ、ヤタガラス」
- 取込元ファイル名:
  - `nee_yatagarasu.onnx`
- 配布時の格納先:
  - `models/wakeword/nee_yatagarasu.onnx`
- SHA-256:
  - `0a2926bf00ff15c24e6ed0cf09e60e5550339439db5103335a517d9d0a70feb8`
- ファイルサイズ: 約933KB
- ONNX入出力:
  - 入力: `embeddings` / `[batch, 16, 96]` / `float32`
  - 出力: `score` / `[batch, 1]` / `float32`
- 配布時のファイルmode: `0644`
- 作成者: `Tane Channel Technology`
- 学習方法: LiveKit WakeWordのVoxCPM公式設定、録音音声の追加なし
- 配布ライセンス: Apache License 2.0

### 3.3 ウェイク即時フィードバック音声

- 発話内容: 「はい」
- 話者: VOICEVOX 青山龍星
- 取込元ファイル名:
  - `hai.mp3`
- 配布時の格納先:
  - `assets/audio/wake_prompt_hai.mp3`
- SHA-256:
  - `5039cd6f77dd7d57db65edefac5b2f56356f4f4a3c04a6ef9d42fd16c2d13257`
- 音声仕様:
  - MP3
  - 8kHz
  - mono
  - 約1.01秒
- 配布時のファイルmode: `0644`
- 必須クレジット:
  - `VOICEVOX:青山龍星`

## 4. 対象範囲

### 4.1 対象

- ONNXウェイクワード検出器の追加
- RTSP音声のローリングバッファ管理
- OFF / WAKING / ON状態遷移
- 同梱MP3による即時フィードバック
- フィードバック音声の回り込み抑制
- 命令音声のVAD、無音確定、STT連携
- STTウェイク方式への明示的切替
- 設定項目、doctor、ログ、テスト、利用者向け文書
- `workspace/.env.example`の標準話者変更
- READMEと音声asset文書へのクレジット追加

### 4.2 初期バージョンの対象外

- 「ねぇヤタガラス、右を向いて」の一息発話を正式対応すること
- フィードバック再生中の割り込み発話
- 音響エコーキャンセル
- 複数ウェイクワードモデルの同時運用
- Yatagarasu上でのウェイクワード学習
- ONNXモデルの自動ダウンロード
- GPU Execution Provider

## 5. 標準対話

初期バージョンの標準操作は、次の2ターン方式とする。

```text
利用者: 「ねぇ、ヤタガラス」
Yatagarasu: 「はい」
利用者: 「右を向いて」
Yatagarasu: カメラを右へ移動
```

- 利用者は「はい」の後に命令を発話する。
- ウェイク語と命令を一息で発話した場合、命令部分の認識を保証しない。
- ウェイク検出だけではLLMを呼び出さない。
- `LISTEND_WAKE_ACK_WORD`の「考えるね。」は、従来どおりLLM dispatch直前だけ再生する。

## 6. 状態遷移要件

### 6.1 状態

- `OFF`
  - ウェイクワードONNX推論を行う。
  - 標準構成ではSTTを行わない。
- `WAKING`
  - 「はい」のフィードバックを開始する。
  - 音声入力は読み続けるが、命令バッファへ追加しない。
  - フィードバック再生処理はRTSP音声入力をブロックしない。
  - ONNX推論とSTTを行わない。
- `ON`
  - 命令音声をVADで収録し、無音確定後にSTTへ渡す。
  - ウェイクワードONNX推論を行わない。

### 6.2 遷移

1. `OFF` + ONNX scoreが閾値以上 -> `WAKING`
2. `WAKING` + フィードバック抑制時間終了 -> `ON`
3. `ON` + 命令ターン無音確定 -> dispatch完了後に`OFF`
4. `ON` + stop word検出 -> `OFF`
5. `ON` + 無音タイムアウト -> `OFF`
6. 任意状態 + RTSP再接続 -> 状態と一時音声バッファを安全に初期化

### 6.3 ウェイク検出時

- 検出イベントにはモデル名、score、閾値、検出時刻を含める。
- 現在のVADセグメントとSTT対象バッファを破棄する。
- ONNXローリングバッファを初期化する。
- `WAKING`へ遷移する。
- 同梱MP3を`tapovoice`経由で再生する。
- 再生開始処理に失敗しても、警告ログを出して命令待機へ進む。

### 6.4 命令待機

- `WAKING`中の音声は、カメラスピーカーからの「はい」の回り込みを避けるため破棄する。
- 抑制時間終了時にVADと命令バッファを初期化して`ON`へ遷移する。
- `ON`遷移後、命令がまだ無くても直ちに`OFF`へ戻らない。
- 命令未入力時は`ON`遷移から`LISTEND_SILENCE_TIMEOUT_SEC`まで待機する。
- 標準設定では3秒間命令が無ければ、発話せず`OFF`へ戻る。

### 6.5 無音タイマーの責務

2つの既存設定は、次のように責務を分離する。

- `LISTEND_SESSION_END_SILENCE_SEC`
  - 認識済みの命令テキストが存在する場合に、1ターンの終端を確定する時間。
  - 経過後は蓄積した命令をSkillまたはLLMへdispatchする。
  - 標準値は3秒とする。
- `LISTEND_SILENCE_TIMEOUT_SEC`
  - `ON`状態で新しい命令を待ち続ける上限時間。
  - ウェイク後に何も話さなかった場合のキャンセルにはこちらを使用する。
  - 標準値は3秒とする。

1回のウェイクにつき1命令だけをdispatchし、成功・失敗・Router完結を問わず
dispatch完了後は`OFF`へ戻る。LLM応答などのシステム音声を再生した場合は、
処理中にffmpegへ蓄積した音声を次の入力へ流用せず、RTSP音声consumerだけを
即時再接続して破棄する。go2rtc自体は再起動しない。

## 7. 音声入力要件

- 入力は既存のgo2rtc RTSP音声を使用する。
- ffmpeg出力は16kHz、mono、signed 16-bit PCMとする。
- ONNX推論用に直近約2秒の音声を保持する。
- モデルへ渡す音声窓は、分類器が必要とする16 embeddingsを生成できる
  32000 samplesで固定する。
- 起動・reset直後に不足する過去音声は内部的な無音sampleで補い、
  2秒間の検出不能時間を発生させない。
- 実音声を何秒蓄積してから推論を許可するかは
  `LISTEND_WAKE_WARMUP_SEC`で0.0秒から2.0秒まで調整可能にする。
- 基本フレームは既存の80msチャンクとする。
- RTSPから受け取った全フレームを、推論間隔にかかわらずローリングバッファへ追加する。
- 既存のSilero VAD結果を再利用し、発話中と待機中でONNX推論間隔を切り替える。
- 発話開始時は、前回推論からの間隔にかかわらず最新の2秒窓で推論を要求する。
- 推論中もRTSP読込を止めない。
- RTSP読込処理とONNX推論処理を同一のblocking workerへ載せない。
- 推論要求を無制限にキューへ蓄積しない。
- 推論要求は実行中1件、保留中1件を上限とする。
- 推論が前の音声に追いつかない場合は、保留中の古い要求を最新音声で置き換える。
- raw音声を通常ログや永続ファイルへ保存しない。

## 8. 設定要件

標準設定を次に示す。閾値と時間値は実機評価後に確定する。

```bash
# RTSP音声入力のbufferを抑制
LISTEND_RTSP_LOW_LATENCY="true"

# Wake backend: livekit / stt
LISTEND_WAKE_BACKEND="livekit"

# 空なら同梱モデルを使用
LISTEND_WAKE_MODEL_PATH=""
LISTEND_WAKE_THRESHOLD="0.65"
LISTEND_WAKE_EARLY_THRESHOLD="0.15"
LISTEND_WAKE_EARLY_CONSECUTIVE="3"
LISTEND_WAKE_DEBOUNCE_SEC="2.0"
LISTEND_WAKE_ACTIVE_INTERVAL_SEC="0.08"
LISTEND_WAKE_IDLE_INTERVAL_SEC="1.5"
LISTEND_WAKE_ACTIVITY_RMS_DBFS="-50"
LISTEND_WAKE_SPEECH_HOLD_SEC="2.0"
LISTEND_WAKE_WARMUP_SEC="0.0"

# 空なら同梱の青山龍星「はい」MP3を使用
LISTEND_WAKE_PROMPT_AUDIO=""
LISTEND_WAKE_PROMPT_WORD="はい"
LISTEND_WAKE_PROMPT_GUARD_SEC="0.8"
LISTEND_WAKE_PROMPT_TIMEOUT_SEC="2.0"

# STT backend時の文字列ウェイク、および表示・ログ用
LISTEND_WAKE_WORDS="ねぇ、ヤタガラス,ねえ、ヤタガラス,ねえ、やたがら"

# 1ターンの終端と、命令待ちキャンセル
LISTEND_SESSION_END_SILENCE_SEC="3"
LISTEND_SILENCE_TIMEOUT_SEC="3"

# Yatagarasu標準話者: VOICEVOX 青山龍星
SPEAKER_ID="13"
```

### 8.1 互換性

- `LISTEND_WAKE_BACKEND="stt"`では、既存の文字起こし結果による判定を維持する。
- `LISTEND_WAKE_BACKEND`の許容値は`livekit`と`stt`だけとする。
- 値を省略した場合のコード上の既定値と、`workspace/.env.example`の値は
  ともに`livekit`とする。
- 不明な値は設定エラーとして起動を失敗させる。
- `LISTEND_WAKE_WORDS`を書き換えても、ONNXモデルが認識する音声は変化しない。
- ONNX方式のウェイクワードを変更する場合は、対応するモデルファイルが必要である。
- 既存利用者の`workspace/.env`をGit更新で上書きしない。
- `workspace/.env.example`では`SPEAKER_ID="13"`を新しい既定値とする。
- `workspace/.env.example`とコード上の
  `LISTEND_SILENCE_TIMEOUT_SEC`既定値はともに3秒とする。
- `LISTEND_WAKE_ACK_SPEAKER_ID=""`は`SPEAKER_ID`を継承する。
- 既存`.env`に`LISTEND_WAKE_BACKEND`が無い場合も、コード上の既定により`livekit`を選択する。
- 既存環境の更新手順には、service停止、コード更新、Python依存更新、
  `yatagarasu doctor`、service再開をこの順で記載する。
- 依存更新前にserviceを再起動してONNX方式だけが利用不能になる事態を避けるため、
  セットアップガイドとリリースノートで破壊的な既定変更として明示する。

## 9. 起動・障害要件

- `livekit`選択時は起動時に次を検証する。
  - `livekit-wakeword`をimportできる。
  - モデルファイルが存在し、読み取り可能である。
  - ONNX入力が`[batch, 16, 96]`である。
  - ONNX出力が`[batch, 1]`である。
  - `CPUExecutionProvider`でSessionを生成できる。
- 検証失敗時は、理由をログへ出して起動を失敗させる。
- 設定不良を隠す自動STTフォールバックは行わない。
- 利用者が`LISTEND_WAKE_BACKEND="stt"`を明示した場合だけ旧方式を使用する。
- フィードバック音声が失敗した場合は、ウェイク検出自体を取り消さない。
- フィードバック再生用subprocessは専用workerで実行し、RTSP読込loopで待機しない。
- 推論workerの例外は主処理へ通知し、無言でウェイク不能にならない。

## 10. 性能要件

- OFF状態のONNX推論はCPUのみで実行できること。
- ONNX推論がRTSP音声読込、VAD、STTをブロックしないこと。
- ONNXモデルの入力窓は常に2秒分とし、短い入力を直接渡さないこと。
- 標準設定では、起動・reset後の最初の音声チャンクから推論可能であること。
- 待機中は1.5秒間隔、発話中は80ms間隔を確定値とし、無音時に80ms間隔では推論しないこと。
- Silero VADが発話開始を逃した場合は、設定可能なRMS音量gateでactive intervalへ移行すること。
- RMS音量gateはウェイク推論のschedulerだけに使用し、命令STTのVAD判定を置き換えないこと。
- 通常閾値未満でも早期閾値以上が設定回数連続した場合はウェイク検出とすること。
- 早期候補が1回でも閾値を下回った場合は連続回数をリセットすること。
- 通常閾値以上では連続回数を待たず従来どおり即時検出すること。
- RTSP入力は設定で無効化可能なFFmpeg低遅延フラグを既定で使用すること。
- 第8世代Core i7で60秒のウォームアップ後、5分間の無音待機を測定し、
  ONNXウェイク導入による`listend`の追加CPU使用率を平均5 percentage points以下とすることを
  性能目標とする。
- CPU使用率は、1論理CPUを100%とするLinuxのプロセスCPU指標で測定する。
- 追加CPU使用率は、同じRTSP入力、チャンク長、Silero VAD設定で
  ONNX推論を無効にした基準値との差分として算出する。
- 発話中の一時的な5%超過は許容するが、1論理CPUへ継続的に張り付かないこと。
- 精度要件を満たしたまま性能目標を達成できない場合は、測定結果と調整案を提示し、
  目標緩和や追加最適化をプロジェクト所有者へ相談する。無断で精度または目標を緩和しない。
- ウェイク検出イベントからMP3再生要求開始まで、ローカル処理を200ms以内とする。
- Tapo/go2rtcネットワーク区間の実再生遅延は、上記200msの測定対象外とする。
- OFF状態では、ウェイク検出前にfaster-whisperまたはReazonSpeechを実行しないこと。
- 推論回数、推論時間、キュー待ち、drop件数、scoreを計測可能にすること。
- heartbeatには累積推論回数とdrop件数を記録すること。

## 11. ログ・診断要件

### 11.1 通常ログ

- 選択ウェイクバックエンド
- 読み込んだモデル名と絶対パス
- threshold、debounce、active/idle推論間隔
- 無音補完のmode、target、最大補完量、判定閾値
- ウェイク検出score
- `OFF -> WAKING -> ON`遷移理由
- フィードバック再生成否
- prompt送信timeout
- prompt guard開始・終了
- 推論worker異常

### 11.2 DEBUGログ

- 最大score
- ONNX推論時間
- 推論要求のdrop件数
- debounceまたは状態によって無視した検出

scoreログは大量出力を避けるため間引けること。

### 11.3 doctor

`bin/yatagarasu doctor`で次を確認できること。

- `LISTEND_WAKE_BACKEND`
- `livekit-wakeword` import
- ONNXモデルの存在、mode、SHA-256、入出力shape
- ONNX Runtime Provider
- prompt MP3の存在、mode、形式、長さ

READMEの必須クレジットはdoctorではなく、リリース確認または文書テストで検証する。

## 12. クレジット・配布要件

READMEに次を明記する。

```text
ウェイクワード検出時の応答音声には、VOICEVOXで生成した青山龍星の音声を使用しています。

VOICEVOX:青山龍星
```

- `assets/audio/README.md`にも同じクレジットを記載する。
- VOICEVOX音声モデル利用規約を記載する。
  - https://github.com/VOICEVOX/voicevox_vvm/blob/main/TERMS.txt
- VOICEVOX 青山龍星の公式ページを記載する。
  - https://voicevox.hiroshiba.jp/product/aoyama_ryusei/
- 企業が関与する利用では、青山龍星の利用規約に従い事前確認が必要である旨を記載する。
- 同梱音声の再配布者にもクレジット要件が伝わる構成にする。
- LiveKit WakeWordをREADMEの第三者ソフトウェア一覧へ追加する。
- `models/wakeword/README.md`へカスタムモデルの対象フレーズ、入出力shape、
  SHA-256、作成者・配布許諾に関する来歴を記載する。
- カスタムモデルの作成者名は`Tane Channel Technology`に統一する。
- カスタムモデルは、LiveKit WakeWordのVoxCPM公式設定を使用し、
  録音音声を追加せず合成データから学習したものとして記録する。
- カスタムモデルには、作成者の意思によりApache License 2.0を適用する。
- 学習基盤であるLiveKit WakeWordとVoxCPMがApache License 2.0であることを
  モデルの来歴文書に記載する。

## 13. 受け入れ条件

### AC-01 起動

- 標準設定で同梱ONNXモデルがCPUへロードされる。
- ログにモデル名、threshold、Providerが表示される。

### AC-02 標準ウェイク

- OFF状態で「ねぇ、ヤタガラス」を発話すると`WAKING`へ遷移する。
- 同梱された青山龍星の「はい」が再生される。
- prompt guard終了後に`ON`へ遷移する。

### AC-03 命令認識

- 「はい」の後に「右を向いて」と発話すると、命令部分がSTTへ渡る。
- ウェイク語だけではSkillまたはLLMを実行しない。
- 命令が無い場合、設定時間待機してからOFFへ戻る。

### AC-04 回り込み防止

- カメラスピーカーから再生した「はい」が命令テキストへ混入しない。
- 「はい」だけでdispatchしない。

### AC-05 OFF負荷

- ウェイク前の通常発話でSTTが呼ばれない。
- 推論が遅延してもRTSP音声読込が継続する。
- 推論要求は実行中1件と保留中1件を超えない。
- 5分間の無音待機で、ONNXウェイクによる追加CPU使用率が平均5 percentage points以下を
  目標とする。
- 発話中もCPUが1論理CPUへ継続的に張り付かない。
- CPU試験結果には、基準値、ONNX有効時、差分、推論回数、測定時間を記録する。
- 5 percentage pointsを超えた場合は、検出品質を落として合格扱いにせず、
  測定結果をもとにプロジェクト所有者と対応を決定する。

### AC-06 互換バックエンド

- `LISTEND_WAKE_BACKEND="stt"`で従来の文字列ウェイクが動作する。
- `livekit`の設定不良時に、自動で旧方式へ切り替わらない。

### AC-07 既定話者

- `workspace/.env.example`の`SPEAKER_ID`が`13`である。
- 新規標準設定の通常応答が青山龍星で再生される。
- ウェイク即時フィードバックは、話者設定にかかわらず同梱MP3を使用する。

### AC-08 配布

- ONNXとMP3がリポジトリ内の既定パスに存在する。
- 両ファイルのmodeが`0644`である。
- READMEに`VOICEVOX:青山龍星`が記載される。
- doctorがモデルと音声assetを正常と判定する。

### AC-09 検出品質

- 実機から1mの距離で、2人以上が「ねぇ、ヤタガラス」を合計30回発話し、
  27回以上検出する。
- 試験回数は話者間で大きく偏らせず、話者ごとの回数と検出数を記録する。
- テレビ音声と通常の生活音を含む8時間の待機試験で、誤検出を1回以下とする。
- 閾値決定時は正例の検出率と誤検出率を両方記録する。

実機受入とCPU測定の確定結果は
`docs/plan/livekit-wakeword-test-results.md`へ記録する。

### AC-10 無音タイマー

- 「はい」の後に何も話さない場合、`ON`遷移から3秒後に発話せず`OFF`へ戻る。
- 命令を認識した場合、3秒の無音で1ターンをdispatchする。
- dispatch完了後は直ちに`OFF`へ遷移する。
- システム音声を再生したdispatchでは、処理中に蓄積したRTSP音声を破棄し、
  ヤタガラス自身の返答を次の命令として再dispatchしない。

### AC-11 既存環境の更新

- 既存の個人設定を上書きせず、文書化した手順でONNX方式へ更新できる。
- 依存更新後のdoctorが正常終了してからserviceを再開できる。
- STT方式を継続する利用者は、`.env`へ`LISTEND_WAKE_BACKEND="stt"`を設定して更新できる。

## 14. テスト観点

- 1mの距離で、2人以上による通常速度、早口、小声のウェイク
- `LISTEND_WAKE_WARMUP_SEC`を0.0、1.0、2.0秒へ変えた場合の検出率と初回検出遅延
- 「ねえ」「ねぇ」の発音差
- テレビ、人声、環境音による誤検出
- ウェイク直後に命令を話し始めた場合の仕様どおりの扱い
- prompt guard中の「はい」回り込み
- prompt再生失敗時の命令待機
- RTSP再接続前後の古い音声による誤検出
- ONからOFFへ戻った直後のdebounce
- 長時間待機時のCPU使用率とメモリ使用量
- 無音時と発話時それぞれの推論回数、平均・p95推論時間、CPU使用率
- faster-whisper / ReazonSpeechそれぞれとの組み合わせ

## 15. CPU負荷低減の設計制約

`test_wakeword_optimized_v2.py`は、実装コードではなく負荷低減方式の参考資料として扱う。

採用する考え方:

- `WakeWordModel.predict()`は改変せず、呼び出し頻度を制御する。
- 約2秒のローリングバッファを維持する。
- 待機中と発話中で推論間隔を切り替える。
- 発話開始時に即時推論を要求する。
- 推論workerを1本に制限し、古い保留要求を最新要求で置き換える。

そのまま採用しない実装:

- PyAudioによるマイク入力とWindows固有の`msvcrt`
- 音声入力とONNX推論を同じ1本のexecutorで直列実行する構造
- RMS閾値だけによる発話判定
- `os._exit()`による強制終了

Yatagarasuでは既存のRTSP入力とSilero VADを利用し、音声取得経路とONNX推論workerを
分離する。RMS gateを追加する場合も、Silero VADを置き換える唯一の判定にはしない。

## 16. 実装前に実機で決定する値

- `LISTEND_WAKE_THRESHOLD`
  - 参考テストに合わせた初期候補は`0.6`。
  - 正例・生活音・テレビ音声でscore分布を確認して決定する。
- `LISTEND_WAKE_PROMPT_GUARD_SEC`
  - 実機調整後の初期値は`0.6`秒。
  - Tapo実機で「はい」の聞こえ終わりと命令録音開始を確認して決定する。
- ONNX推論間隔
  - 実機調整後の確定値は発話中80ms、待機中1.5秒、発話保持2秒。
  - 第8世代Core i7でCPU使用率、検出率、検出遅延を測定して決定する。

## 17. 将来拡張

- 「ねぇヤタガラス、右を向いて」の一息発話
- 命令音声pre-roll
- フィードバック再生中のbarge-in
- 複数のウェイクワードモデル
- ウェイクモデルのユーザー差し替え支援
- false positive時の任意音声保存と評価支援
