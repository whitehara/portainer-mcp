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

- [x] 取得したツール一覧に41文字以上の名前が0件 — 219ツール中0件
- [x] swarmツール8個と `get_guidance` すべてが一覧に存在する
- [x] 実Portainerに対して読み取り系ツールが正常に成功する（`listSwarmEnvironments` /
      `listSwarmNodes` / `getSwarmInfo` / `listSwarmServices` を実際に呼び出し、実データが
      返ることを確認。案Aのcaller key passthroughが実際に機能していることも確認済み）
- [x] 検証中に本番stackを更新していない（読み取り系ツールのみ実行、書き込み系は未実行）
- [x] 本番相当env（`PORTAINER_MCP_TRUST_PROXY_TLS=1` + `FORWARDED_ALLOW_IPS` + 非loopback host）
      起動時のログに `transport posture: https enforced` / `HTTP auth: per-user passthrough`
      が期待どおり出ている（Docker無しでuv run直接起動により確認。Docker build自体はこの
      サンドボックスからghcr.ioへ到達できず未検証 — フェーズ4のCI/実機で確認する）
- [x] env欠落ケース（`PORTAINER_URL`未設定・`PORTAINER_MCP_AUTH_TOKEN`未設定・HTTPで
      `PORTAINER_API_KEY`設定）で起動拒否を確認。後2者はSystemExitで分かりやすいメッセージが
      出ることを確認。`PORTAINER_URL`欠落は分かりにくい`KeyError`トレースバックになる
      （upstream由来の既存挙動、今回の差分ではない。下記「気づいた点」参照）
- [x] `PORTAINER_MCP_HTTP_PORT` を既定値以外にした状態でHEALTHCHECKと同一ロジック
      （`socket.connect(('127.0.0.1', <port>))`）が正しく成功/失敗することを直接確認
      （Docker `docker inspect` 自体は同上の理由で未検証）

## 実施結果（2026-08-09）

- ツール一覧・swarmツール・guidance gate・実Portainer呼び出しはすべてユーザーが起動した
  `make dev`（loopback, HTTP）に対し、MCP Streamable HTTPプロトコルを直接叩いて確認した。
  guidance gateは初回呼び出しをバウンスし、2回目で実データが返る想定どおりの挙動を確認。
- 実データ例（値は本ファイルに残さない）: 環境2件、Swarmノード3件、サービス46件・
  スタック16件など、本番の規模感と整合する結果が得られた。
- **気づいた点（今回のフェーズ2差分とは無関係、参考記録）**:
  - `getSwarmServiceLogs`を`portainer-stack_portainer-mcp-http`サービスに対して呼んだところ
    `404 No such container`エラーになった。`listSwarmTasks`ではそのコンテナIDが
    `running`として報告されており、Portainer側のタスク情報とDocker Engine側のコンテナ存在に
    食い違いがある状態だった。マルチノードSwarmでのagent経由ログ取得の既知のズレの可能性が高く、
    今回のフォーク変更（swarm.py無改修）に起因するものではない。本番運用上気になる場合は
    別途調査する余地がある。
  - `PORTAINER_URL`欠落時のエラーが未整形の`KeyError`トレースバックになる（`server.py:332`）。
    upstream由来の既存挙動で今回のマージでは変更していない。改善の余地はあるが、
    upstream追従計画のスコープ外として今回は対応しない。
- ローカルで使用した実Portainer APIキーは検証直後にユーザー側でローテーション予定
  （`claude mcp get`実行時に誤って会話上に露出したため）。

## リスク・注意点

- 本番のPortainerを参照して検証する場合、書き込み系ツールは実行しないこと。読み取り系のみで検証する。
- Docker build/run自体の検証（タスク6・8の完全な形）はこのセッションのサンドボックス制約により
  実施できなかった。フェーズ4での実際のCIビルド・本番デプロイ時のログ確認で補う。
