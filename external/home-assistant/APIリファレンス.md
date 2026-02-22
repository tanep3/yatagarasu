### APIリファレンス（Home Assistantの公式仕様ベース、純粋なリファレンス形式）

#### REST API
- **Base URL**: `http(s)://<host>:8123/api/`
- **認証**: すべてのリクエストにヘッダー必須  
  `Authorization: Bearer <long-lived access token>`

| Method | Path                              | Description                                      | Required Headers          | Request Body (JSON) Example | Response (主要フィールド) |
|--------|-----------------------------------|--------------------------------------------------|---------------------------|-----------------------------|----------------------------|
| GET    | /                                 | APIバージョン情報                                | Authorization             | -                           | { "version": "2025.x", ... } |
| GET    | /states                           | 全エンティティの現在の状態リスト                 | Authorization             | -                           | array of State objects     |
| GET    | /states/<entity_id>               | 特定エンティティの状態                           | Authorization             | -                           | State object               |
| POST   | /states/<entity_id>               | エンティティ状態を外部から強制更新               | Authorization, Content-Type: application/json | {"state": "...", "attributes": {...}} | 204 No Content (成功)     |
| POST   | /services/<domain>/<service>      | サービス実行（最も重要）                         | Authorization, Content-Type: application/json | {"entity_id": "...", ...}   | 200 OK or 204 No Content   |
| GET    | /services                         | 利用可能なサービス一覧                           | Authorization             | -                           | { "services": { ... } }    |
| GET    | /config                           | HA設定情報                                       | Authorization             | -                           | Config object              |
| GET    | /camera_proxy/<entity_id>         | カメラエンティティの最新画像プロキシ             | Authorization             | -                           | image/jpeg binary          |
| GET    | /camera_proxy_stream/<entity_id>  | カメラストリームプロキシ（MJPEGなど）            | Authorization             | -                           | multipart/x-mixed-replace  |
| POST   | /events/<event_type>/fire         | カスタムイベント発火                             | Authorization, Content-Type: application/json | arbitrary JSON              | 200 OK                     |

State object例（JSONスキーマ）:
```json
{
  "entity_id": "binary_sensor.tapo_tc70_motion",
  "state": "on" | "off",
  "attributes": { ... },
  "last_changed": "ISO8601",
  "last_updated": "ISO8601"
}
```

#### WebSocket API
- **URL**: `ws(s)://<host>:8123/api/websocket`
- **メッセージ形式**: 毎回JSONオブジェクト（"type"必須）
- **認証フロー**:
  1. 接続 → サーバーから `{"type": "auth_required", ...}` が来る
  2. クライアントから `{"type": "auth", "access_token": "..."}` 送信
  3. `{"type": "auth_ok"}` or `{"type": "auth_invalid"}`

| type                          | Direction | Description                              | Required Fields                          | Response/Events                     |
|-------------------------------|-----------|------------------------------------------|------------------------------------------|-------------------------------------|
| auth                          | Client → Server | 認証                                     | access_token                             | auth_ok / auth_invalid              |
| subscribe_events              | Client → Server | イベント購読                             | event_type (optional)                    | subscription id返却                 |
| unsubscribe_events            | Client → Server | 購読解除                                 | subscription                             | result                              |
| get_states                    | Client → Server | 全状態取得                               | -                                        | result: array of State objects      |
| call_service                  | Client → Server | サービス実行                             | domain, service, service_data (optional) | result                              |
| ping                          | Client → Server | 接続確認                                 | -                                        | pong                                |
| event                         | Server → Client | 購読中のイベント通知                     | -                                        | { "event_type": "...", "data": {...} } |

event data例（state_changed）:
```json
{
  "entity_id": "binary_sensor.xxx_motion",
  "old_state": { ... },
  "new_state": { "state": "on", ... }
}
```

