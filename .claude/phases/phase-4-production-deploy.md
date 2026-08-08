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

- [ ] GHCRに `ghcr.io/whitehara/portainer-mcp:2.44.0-1` が存在する（`docker pull` で確認）
- [ ] 本番サービスの `docker service ps` が `Running` で、タスクの再起動ループが起きていない
- [ ] サービスログに `SystemExit` / トレースバックが出ていない
- [ ] MCPクライアントからツール一覧が取得でき、`listSwarmEnvironments` が正常なレスポンスを返す
- [ ] `.claude/ROADMAP.md` と該当phases文書に、切り戻し用の旧イメージダイジェストと旧環境変数セット
      （変数名のみ）が記録されている

## リスク・注意点

- 起動拒否系のエラーはすべて `SystemExit` なのでコンテナが即死する。Swarmの再起動ポリシー次第で
  クラッシュループになるため、ログの取得はデプロイ直後すぐに行うこと。
- 切り戻しは「イメージダイジェスト＋旧環境変数セット」の**両方**を戻す必要がある
  （案Aで `PORTAINER_API_KEY` を消していると、旧イメージに戻しただけでは動かない）。

## 実施結果

（デプロイ実施後にここへ追記する: 切り戻し用ダイジェスト・実施日・確認結果）
