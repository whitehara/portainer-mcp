# Fork delta (whitehara/portainer-mcp vs upstream/main)

このファイルは、このフォークがupstream（`portainer/portainer-mcp`）から独自に持っている
差分を1行1パッチで管理する表。upstream追従（マージ）のたびに、このリストと
`git diff --stat upstream/main..HEAD` を突き合わせて棚卸しする
（手順は `.claude/skills/upstream-sync/SKILL.md` を参照）。

**不変条件**: `pyproject.toml` の `version` は編集しない。マージ時にupstreamの値を
そのまま採用する（フォーク独自リリースは `hl-<upstream-version>-<fork-rev>` タグで
区別し、`version`フィールド自体は変更しない）。CIでは強制していない
（強制するとupstream側のversion更新まで弾いてしまうため）——コミット時のレビューで守る。

## 差分一覧

| ファイル | 変更内容 | 存在理由 | upstreamで代替されたら削除できる条件 | 最終確認日 |
|---|---|---|---|---|
| `src/portainer_mcp/swarm.py` | 新規ファイル（8ツール: `listSwarmEnvironments`, `listSwarmNodes`, `listSwarmServices`, `listSwarmTasks`, `getSwarmInfo`, `getSwarmServiceLogs`, `createSwarmStack`, `updateSwarmStack`） | Docker Swarm運用（ホームラボの主要デプロイ先）向けの独自ツール群。upstreamはDocker Swarm特化のハンドライトツールを持たない | upstreamが同等のSwarmツール群を取り込んだら削除・置き換え検討 | 2026-08-09 |
| `tests/test_swarm.py` | 新規ファイル（`swarm.py`のテスト） | 上記の対 | `swarm.py`削除に連動 | 2026-08-09 |
| `src/portainer_mcp/server.py` | 4箇所のフォークパッチ: (1) `from portainer_mcp import (..., swarm, ...)` (2) `_TOOL_NAME_REMAP`定数 (3) `_annotate_read_only()`内のリマップ適用1行 (4) `swarm.register(mcp, client, read_only=read_only)`呼び出し（`proxy.register()`直後、`guidance.register()`/`mcp.add_transform()`より前） | (1)(4)は`swarm.py`registerのための配線。(2)(3)はOpenAPI生成ツール名がCloudflareの40文字制限を超える場合の短縮対応（upstream固有の問題ではなく、Cloudflare上でこのMCPサーバを公開運用しているフォーク固有の制約） | (1)(4)は`swarm.py`が無くなれば同時に削除。(2)(3)はCloudflareの制限が緩和されるか、upstreamが40文字以内の命名規則を採用したら削除 | 2026-08-09 |
| `tests/test_tool_names.py` | 新規ファイル。`PORTAINER_PROFILES=ALL`で全ツール名が40文字以内であることを検証する回帰テスト | 上記`_TOOL_NAME_REMAP`が今後のspec更新でも機能し続けることを保証するため | `_TOOL_NAME_REMAP`が不要になったら削除 | 2026-08-09 |
| `Dockerfile` | `HEALTHCHECK`が`PORTAINER_MCP_HTTP_PORT`環境変数を参照するよう動的化（2行差分） | upstream版はポート決め打ちだったための対応（バージョンにより差分内容が変わりうる。マージのたびに`git diff upstream/main..HEAD -- Dockerfile`で内容を確認すること） | upstream側がポート動的化を取り込んだら削除 | 2026-08-09 |
| `.github/workflows/release-docker.yml` | GHCR配布・`hl-<upstream-version>-<fork-rev>`タグ運用に書き換え（upstream版はDocker Hub・裸`X.Y.Z`タグ） | フォークはPyPI非配布でコンテナイメージのみ配布。タグ命名衝突回避のため独自タグ規約が必須 | フォークがupstreamと統合される、またはリリース運用を統一しない限り恒久的に残る | 2026-08-09 |
| `.github/workflows/release-mcpb.yml` | `on:`を`workflow_dispatch`のみに変更（upstream版はタグpushで自動実行） | フォークは`.mcpb`バンドルを配布しない。ファイル自体は残しupstreamとの差分を最小化 | upstreamがこのファイルを削除するか、フォークが`.mcpb`配布を始めたら統合検討 | 2026-08-09 |
| `.github/workflows/release.yml` | **削除**（upstream版はPyPI公開ワークフロー） | フォークはPyPI配布しない | 恒久的に削除のまま | 2026-08-09 |
| `.github/workflows/release-test.yml` | **削除**（upstream版はTestPyPI公開ワークフロー） | 同上 | 恒久的に削除のまま | 2026-08-09 |
| `docs/release.md` | 冒頭にfork note、"Fork release notes"節を追加（GHCR配布・タグ規約・`pyproject.toml` version不変条件） | フォーク独自のリリース運用をupstream由来のPyPI手順と混同させないため | リリース運用を統一しない限り恒久的に残る | 2026-08-09 |
| `docs/versioning.md` | 末尾に"Fork note"節を追加（`hl-*`タグ規約への参照） | 同上 | 同上 | 2026-08-09 |
| `CLAUDE.md` | "## Versioning"節末尾にfork固有の段落を追加 | 同上、プロジェクト規約ドキュメントとしての一貫性 | 同上 | 2026-08-09 |

## 運用ノート（コード外の判断だが記録しておく）

- 本番の`portainer-mcp`サービスには`PORTAINER_EXPOSE_ENV_VALUES=1`を設定している
  （upstream既定は無効=redacted）。理由: Portainerの`StackUpdate` APIは`Env`配列を
  全置換方式で受け取るため、portainer-mcp経由で*他の*スタックを差分更新する際、
  既存env値が読めないと安全に更新できないため。将来的にportainer-mcp側へ
  「サーバ内部でdiff-mergeしてLLMには値を見せない」ツールを追加できれば、この設定を
  redacted既定へ戻せる可能性がある（`.claude/ROADMAP.md`の「今後の検討事項」参照）。
- 本番の認証構成: `PORTAINER_MCP_TRUST_PROXY_TLS=1` + `PORTAINER_MCP_FORWARDED_ALLOW_IPS`
  + `PORTAINER_MCP_TRUST_PROXY_AUTH=1`（`server.py`へのパッチ無し、env変数のみ）。
  mcp-auth-proxy側（このリポジトリ外、`/tmp/portainer-agent-stack.yml`）で
  `--proxy-headers=X-Portainer-API-Key:<共通キー>`を設定し、claude.aiのようにヘッダを
  指定できないクライアント経路でも per-userキー検証を通している。詳細は
  `.claude/phases/phase-1-auth-decision.md` / `phase-4-production-deploy.md`。
