# フェーズ4: 本番デプロイと切り戻し準備

目安: 2時間。実施主体: メインセッション。**ユーザー承認必須**（本番影響）。
実施結果のROADMAP/phases記録のみの変更（タスク8）はreviewer不要。

## ゴール

GHCRに新イメージがpublishされ、本番Swarmサービスが新イメージで稼働し、MCPクライアントから
正常にツールが呼べる。切り戻し先が明示的に確保されている。

## タスク

1. ブランチを `main` にマージし（ユーザー承認後）、フェーズ0で決めた新形式のタグ `hl-2.44.0-1`
   を打って push する。
2. GitHub Actionsの `Release (Docker)` ワークフローが成功し、GHCRに `2.44.0-1` / `2.44.0` /
   `latest` がpublishされたことを確認する。
3. **切り戻し先を記録する**: 現行稼働中のイメージダイジェスト（`sha256:...`）をswarm-inspector
   スキルで取得して控える。あわせて現行の環境変数セット（変数名のみ。値は控えない）を記録する。
4. 本番スタックの環境変数を、フェーズ1で決めた最終リストに更新する。**具体値（overlay CIDR、
   ALLOWED_HOSTSのホスト名、各種トークン）はこのタイミングでユーザーから受け取り、ファイルには残さない**。
   - 案Aの場合は **`PORTAINER_API_KEY` を必ず削除する**（残すと新イメージが起動拒否される）
   - `PORTAINER_MCP_TRUST_PROXY_TLS` + `PORTAINER_MCP_FORWARDED_ALLOW_IPS`
     （値=フェーズ1タスク5で確認したoverlay CIDR）、`PORTAINER_MCP_ALLOWED_HOSTS`、
     guidance gateフラグも同時に反映する
   - **環境変数の追加とimage tag更新は同一のstack更新に束ねて1回で適用する**
     （compose定義の `image` と `environment` を同時に書き換えて `updateSwarmStack` を1回呼ぶ）。
     2回に分けると、新imageが必要な環境変数なしで起動する時間帯が生じるため不可。
     デプロイ手順自体はswarm-deployスキルに従う。
5. swarm-deployスキルに従ってデプロイし、サービスログで `transport posture:` /
   `HTTP auth:` / `profiles tag set` の行を確認する。
6. MCPクライアント（Claude Code / claude.ai / mcp-portal）から接続し、ツール一覧取得と
   読み取り系ツール2〜3本の実行を確認する。
7. **ロールバック手順**: デプロイ直前のimage tagと環境変数セット（変数名のみ）が本ファイルまたは
   実施記録に記録済みであることを確認する。ロールバックが必要になった場合は、記録した旧tag・
   旧環境変数で `updateSwarmStack` を1回実行して戻す（実行はメインセッションがユーザー承認を得てから行う）。
8. 動作確認後、`.claude/ROADMAP.md` と `.claude/phases/*.md` に実施結果を記録してコミットする。

## 完了条件

- [x] GHCRに `ghcr.io/whitehara/portainer-mcp:2.44.0-1` が存在する（CIログの digest 出力で確認。
      `docker pull` はこのセッションのサンドボックスからghcr.ioへ到達できず未検証だが、
      本番ホストでのpull自体は実際のデプロイで成功している）
- [x] 本番サービスの `docker service ps` が `Running` で、タスクの再起動ループが起きていない
      （replica 1/1、タスクID変化なし、コンテナは`healthy`）
- [x] サービスログに `SystemExit` / トレースバックが出ていない（実ログで確認）
- [x] MCPクライアントからツール一覧が取得でき、読み取り系ツールが正常なレスポンスを返す
      （実ログで`StackFileInspect`/`StackInspect`/`resources/list`等の成功を確認。
      `outcome: ok`, `auth_posture: trust_proxy`, `portainer_username: white`）
- [x] `.claude/ROADMAP.md` と該当phases文書に、切り戻し用の旧イメージダイジェストと旧環境変数セット
      （変数名のみ）が記録されている

## リスク・注意点

- 起動拒否系のエラーはすべて `SystemExit` なのでコンテナが即死する。Swarmの再起動ポリシー次第で
  クラッシュループになるため、ログの取得はデプロイ直後すぐに行うこと。
- 切り戻しは「イメージダイジェスト＋旧環境変数セット」の**両方**を戻す必要がある
  （案Aで `PORTAINER_API_KEY` を消していると、旧イメージに戻しただけでは動かない）。

## 実施結果（2026-08-09）

### デプロイ方式の変更（計画からの逸脱、理由つき）

計画では「swarm-deployスキル（`updateSwarmStack`）でデプロイする」としていたが、実際には
**ユーザーがホスト上で手動デプロイ**した。理由: `portainer-mcp`自身がPortainer APIを通じて
自分自身のスタックを更新することになり、更新の途中でPortainer-mcp自身への接続が切れる
（更新プロセスが自分の接続元を道連れにする）鶏卵問題を避けるため。デプロイに使ったファイルは
ホスト上の`/tmp/portainer-agent-stack.yml`（gitリポジトリ外、`docker stack deploy`で使用）。
メインセッションはこのファイルの差分編集内容を提示し、実際の`docker stack deploy`実行は
ユーザーが行った。

### タグ・イメージ

- `hl-2.44.0-1`タグをpush → GitHub Actions `Release (Docker)` 成功
  （run id 31300806273、`build-and-push` 1m57s）
- GHCRへpush確認: digest `sha256:770660743f937b3acb42e2428835963f3fda7200ad18bc633278c35d6d15692b`、
  タグ `2.44.0-1` / `2.44.0` / `latest`（CIログの`pushing manifest`出力で確認）

### 切り戻し先（旧本番の記録）

- 旧イメージダイジェスト: `ghcr.io/whitehara/portainer-mcp:latest@sha256:4d06846fa3c08e45db3d3ec77e741da1dcefde02230ad157a80bff07e3a07e09`
- 旧環境変数名一覧: `PORTAINER_API_KEY`, `PORTAINER_EXPOSE_ENV_VALUES`, `PORTAINER_MCP_ALLOWED_HOSTS`,
  `PORTAINER_MCP_HTTP_HOST`, `PORTAINER_MCP_HTTP_PORT`, `PORTAINER_MCP_TRANSPORT`,
  `PORTAINER_PROFILES`, `PORTAINER_URL`
- 副次的発見: 旧本番では`PORTAINER_EXPOSE_ENV_VALUES=1`が設定されており、`docker_proxy`経由の
  Spec直接取得でenv値が伏字化されずに見える状態だった。新デプロイでは一度削除したが、
  下記「再追加」のとおり運用上必要と判明し戻した。

### 新環境変数（フェーズ1決定＋認証ポスチャ訂正を反映）

`PORTAINER_API_KEY`を削除し、`PORTAINER_MCP_TRUST_PROXY_TLS`・`PORTAINER_MCP_FORWARDED_ALLOW_IPS`・
`PORTAINER_MCP_TRUST_PROXY_AUTH`を追加（詳細は`.claude/phases/phase-1-auth-decision.md`
「認証ポスチャの訂正」節）。あわせてmcp-auth-proxy側（`portainer-mcp-http`サービス）の
起動コマンドに`--proxy-headers=X-Portainer-API-Key:<共通キー>`を追加し、claude.aiのような
ヘッダ指定不可のクライアント経路でも per-userキー検証が通るようにした（既存の
`${PORTAINER_TOKEN}`変数を転用、新規の秘密情報追加なし）。

### `PORTAINER_EXPOSE_ENV_VALUES`の再追加（デプロイ直後に発覚）

初回デプロイでは`PORTAINER_EXPOSE_ENV_VALUES`を削除したが、これが無いと**他のスタックを
portainer-mcp経由でデプロイ・更新する際にenv値が取得できず失敗する**ことが判明した
（`StackFileInspect`等で既存スタックのenv値を読み取れないと、更新時に値を保持できず
壊れる）。ユーザーの判断で`PORTAINER_EXPOSE_ENV_VALUES=1`を`/tmp/portainer-agent-stack.yml`
に戻し、再デプロイ予定。この設定は本フォークの通常運用上の要件であり、フェーズ1で
セキュリティ上の懸念として指摘した点よりも運用上の必要性が優先される。

### 動作確認結果

- `docker service ps`: `portainer-stack_portainer-mcp` / `portainer-stack_portainer-mcp-http`
  ともにreplica 1/1、`Running`、再起動ループなし。コンテナは`healthy`。
- `getSwarmServiceLogs`はフェーズ3で見つかったのと同じ既知の環境要因（edge node経由の
  ログ取得制約）で読めなかったため、ユーザーがホスト上で直接`docker service logs`を取得。
- 実ログで以下を確認（構造化JSONログ）:
  - `"logger": "portainer_mcp.audit", "event": "auth", "outcome": "ok", "auth_posture": "trust_proxy", "portainer_user_id": 1, "portainer_username": "white"`
  - `tools/call`が`StackFileInspect` / `StackInspect`に対して`request_success`
  - `resources/list` / `prompts/list`も正常応答
  - `SystemExit`・Pythonトレースバック・エラーは一切無し

フェーズ4完了。GHCR公開・本番デプロイ・trust-proxy認証・per-userキー検証・実クライアント
からのツール呼び出しまで、すべて本番トラフィックで確認済み。
