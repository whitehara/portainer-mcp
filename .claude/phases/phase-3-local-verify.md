# フェーズ3: ローカル検証

目安: 2〜3時間。実施主体: メインセッション。検証のみでコード変更がなければreviewer不要
（修正が発生したらフェーズ2のworktreeに差し戻してreviewerを通す）。

## ゴール

マージ後のイメージが、フェーズ1で決めた本番相当の環境変数構成で起動し、swarmツールを
含む主要ツールが実Portainerに対して動作することを、**本番のSwarmサービスに一切触れずに**確認できている。

## 検証範囲（重要）

ローカル検証は本番Portainer APIに対して**読み取り専用ツールのみ**を呼ぶ。呼んでよいのは
`listSwarmEnvironments` / `listSwarmNodes` / `listSwarmServices` / `listSwarmTasks` /
`getSwarmInfo` / `getSwarmServiceLogs` と、OpenAPI由来ツールのうちGET相当のもの。
`createSwarmStack` / `updateSwarmStack`、および `docker_proxy` / `kubernetes_proxy` の
GET以外のメソッドは**実行しない**。本番Swarmのstack・service・volumeは一切変更しない。

## 環境変数の前提

案Aを選んだ場合、**HTTP起動時のenvに `PORTAINER_API_KEY` を含めてはいけない**
（含めると `SystemExit` で起動拒否される）。代わりにクライアントが
`X-Portainer-API-Key` ヘッダを送る。stdioでのローカル開発は従来どおり `PORTAINER_API_KEY` を使う。

## タスク

1. `make dev`（HTTP、loopbackバインド）でローカル起動し、
   `claude mcp add portainer-dev --transport http http://127.0.0.1:17717/mcp`
   （案Aなら `--header 'X-Portainer-API-Key: …'` 付き）で接続してツール一覧を取得する。
2. ツール名がすべて40文字以内であることを確認する。
3. swarmツール8個（`listSwarmEnvironments` / `listSwarmNodes` / `listSwarmServices` /
   `listSwarmTasks` / `getSwarmInfo` / `getSwarmServiceLogs` / `createSwarmStack` /
   `updateSwarmStack`）と `get_guidance` が一覧に含まれることを確認する。
4. `listSwarmEnvironments` / `listSwarmNodes` / `getSwarmInfo` を実行し、実Portainer
   から結果が返ることを確認する（`getSwarmServiceLogs` のログフレーム除去も1件確認）。
   **案Aの場合、これはフェーズ1タスク2の結論（swarmツールがcallerのキーで動くか）の実測検証でもある**。
   401/403が返る場合は配線が足りていないということなので、フェーズ2に差し戻す。
5. guidance gateの挙動を実測する: 最初のツール呼び出しがバウンスされるか、
   フェーズ1の決定どおりか（無効化した場合はバウンスしないこと）を確認する。
6. 本番相当の非loopback構成をローカルDockerで再現する（`docker run` でコンテナを1つ起動。
   `PORTAINER_MCP_HTTP_HOST=0.0.0.0` + フェーズ1で決めたTLS/認証env）。コンテナが起動し、
   `docker logs <container>` に `transport posture:` と `HTTP auth:` の行が期待どおり出ることを確認する。
   **本番Swarmのサービスは操作しない（`docker service …` は使わない）**。
7. 意図的にenvを1つ欠落させて起動し、`SystemExit` メッセージが分かりやすいことを確認する。
   案Aでは「`PORTAINER_API_KEY` を敢えて設定した場合に起動拒否されること」も1ケース確認する。
8. HEALTHCHECKの回帰確認: `PORTAINER_MCP_HTTP_PORT` を既定の17717以外（例18000）にして
   コンテナを起動し、`docker inspect --format '{{.State.Health.Status}}' <container>` が
   `healthy` になることを確認する。

## 完了条件

- [ ] 取得したツール一覧に41文字以上の名前が0件
- [ ] swarmツール8個と `get_guidance` すべてが一覧に存在する
- [ ] 実Portainerに対して読み取り系ツールが、本番Swarmのservice一覧と件数が一致する形で成功する
      （案Aではcallerが送ったキーの権限で成功していること）
- [ ] 検証中に本番stackを更新していないこと（Portainerのstack更新日時が検証前後で変化していない）
- [ ] 本番相当envで起動した**ローカルコンテナ**の `docker logs` に、期待した `transport posture:` /
      `HTTP auth:` の行が出ている
- [ ] env欠落ケースで `SystemExit` とその理由がログに出る
- [ ] `PORTAINER_MCP_HTTP_PORT` を既定値以外にした状態で `docker inspect` のHealth Statusが `healthy`

## リスク・注意点

- 本番のPortainerを参照して検証する場合、書き込み系ツールは実行しないこと。読み取り系のみで検証する。
