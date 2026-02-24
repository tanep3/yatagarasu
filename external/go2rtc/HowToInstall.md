# go2rtc インストールガイド

## 本家リポジトリ

https://github.com/AlexxIT/go2rtc

## ダウンロード

上記リポジトリから最新のバイナリをPATHの通ったディレクトリ（例: `~/bin/`）に配置します。

```bash
# ダウンロード例
wget https://github.com/AlexxIT/go2rtc/releases/download/v1.9.3/go2rtc_linux_amd64 -O ~/bin/go2rtc

# 実行権限付与
chmod +x ~/bin/go2rtc
```

## systemd サービス登録

ユーザー権限で systemd に登録することで、ログイン時に自動起動できます。

### 1. サービスファイル作成

`~/.config/systemd/user/go2rtc.service` を作成：

```ini
[Unit]
Description=go2rtc - Camera Streaming Service
After=network.target

[Service]
Type=simple
ExecStart=/home/<user>/bin/go2rtc -config /home/<user>/yatagarasu/external/go2rtc/go2rtc.yaml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

**注意**: `ExecStart` のパスは実際のインストール環境に合わせて変更してください。
- `/home/<user>/bin/go2rtc` → go2rtc バイナリのパス
- `/home/<user>/yatagarasu/external/go2rtc/go2rtc.yaml` → 設定ファイルのパス

### 2. サービスの有効化と起動

```bash
# systemd デーモンをリロード
systemctl --user daemon-reload

# サービスを有効化（自動起動オン）
systemctl --user enable go2rtc

# サービスを起動
systemctl --user start go2rtc

# 状態確認
systemctl --user status go2rtc
```

### 3. サービス管理コマンド

```bash
# 停止
systemctl --user stop go2rtc

# 再起動
systemctl --user restart go2rtc

# ログ確認
journalctl --user -u go2rtc -f
```

## 設定ファイル (go2rtc.yaml)

設定ファイルは `<workspace>/external/go2rtc/go2rtc.yaml` に配置します。

### 設定例

```yaml
streams:
  tapo_tc70:  # カメラのストリーム定義
    - rtsp://ユーザー名:パスワード@TC70のIP:554/stream1  # 高画質映像+音声（映像はオプション）
    - tapo://TP-Linkアプリのパスワード@TC70のIP  # Tapoプロトコルで双方向音声有効
    - ffmpeg:tapo_tc70#video=copy#audio=aac    # オーディオ対応（必要なら）

webrtc:  # WebRTCでスピーカー制御（ブラウザからテスト可能）
  candidates:
    - stun.l.google.com:19302  # STUNサーバー
```

### 設定項目説明

| 項目 | 説明 |
|------|------|
| `streams` | ストリーム定義のルート |
| `tapo_tc70` | ストリーム名（capture スクリプト等で使用） |
| `rtsp://...` | RTSP ストリーム URL（Tapo カメラの IP、ユーザー名、パスワードを設定） |
| `tapo://...` | Tapo プロトコル URL（双方向音声用） |
| `webrtc.candidates` | WebRTC の STUN サーバー設定 |

### 必要な情報

設定には以下の情報が必要です：

- **Tapo カメラの IP アドレス**: Tapo アプリで確認、またはルーターの DHCP 割当てから
- **Admin ユーザー名**: Tapo アプリで作成した管理者アカウントのユーザー名
- **パスワード**:
  - RTSP 用: カメラに設定した RTSP パスワード（または管理者パスワード）
  - Tapo プロトコル用: Tapo アプリのログインパスワード

## ポート設定

go2rtc は以下のポートを使用します：

| ポート | 用途 |
|--------|------|
| 1984 | HTTP API / Web UI |
| 8554 | RTSP ストリーム |

ファイアウォールを使用している場合は、これらのポートを許可してください。

## 動作確認

### Web UI にアクセス

ブラウザで `http://localhost:1984` にアクセスすると、Web UI が表示されます。

### ストリーム確認

```bash
# RTSP ストリームのテスト（ffmpeg が必要）
ffplay rtsp://localhost:8554/tapo_tc70
```

### capture スクリプトでテスト

```bash
# workspace で capture スクリプトを実行
./.claude/skills/view/scripts/capture -o test.jpg
```

## トラブルシューティング

### サービスが起動しない

```bash
# ログを確認
journalctl --user -u go2rtc -n 50
```

### ストリームに接続できない

1. **ネットワーク接続確認**: Tapo カメラと同じネットワークに接続しているか確認
2. **認証情報確認**: ユーザー名とパスワードが正しいか確認
3. **IP アドレス確認**: カメラの IP アドレスが正しいか確認

### Tapo error_code -64316

このエラーは PTZ モーターのエラーです。

```bash
# カメラの PTZ 動作をテスト
./.claude/skills/move-camera/scripts/ptz_control.sh --left
```

管理者権限を持つユーザーで、正しい Tapo プロトコルパスワードを使用しているか確認してください。

### 双方向音声が動作しない

- Tapo プロトコル URL が正しく設定されているか確認
- Tapo アプリのパスワードが正しいか確認
- go2rtc のログでエラーを確認

```bash
journalctl --user -u go2rtc -f
```

## 参考リンク

- [go2rtc GitHub](https://github.com/AlexxIT/go2rtc)
- [go2rtc Documentation](https://github.com/AlexxIT/go2rtc/blob/master/README.md)
