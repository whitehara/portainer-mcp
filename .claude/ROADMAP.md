# ROADMAP

このレポは従来方式（`.claude/ROADMAP.md` / `.claude/phases/*.md`）で進捗管理する。

## 背景

`origin`（whitehara/portainer-mcp）は `upstream`（portainer/portainer-mcp）から
`1351ada`（"rebase on Python/FastMCP upstream and add Docker Swarm tools"）で分岐し、
以後フォーク独自コミット7件（Swarmツール追加・GHCR切替・HTTP bearer auth任意化・
HEALTHCHECKポート動的化・Cloudflare 40文字制限対応のツール名リマップ等）のみ。
一方upstreamは分岐後28コミット進み、GITOPSプロファイル・TLS posture強制・
`.mcpb`バンドル対応・ユーザー単位APIキーpassthrough・spec 2.42.0→2.44.0（Portainer
2.44.x対応）などを取り込み済み。さらにフォーク側が打った `2.42.4`〜`2.42.7` タグが
upstreamの同名タグと衝突している（別コミットを指す）。

2026-08-09、upstream追従計画をplanner→planner-cross-review（3回反復、収束基準は
機械的差分適用まで到達）で策定し、ユーザー承認済み。

## フェーズ一覧

| フェーズ | 内容 | 状態 |
|---|---|---|
| 0 | タグ命名衝突の解消とupstreamタグの取り込み | 完了（2026-08-09） |
| 1 | HTTP認証・TLSポスチャの方針決定（コード変更なし） | 完了（2026-08-09、案A採用） |
| 2 | upstream/mainのマージとフォークパッチ再適用 | 完了（2026-08-09、docker build検証はフェーズ3へ持ち越し） |
| 3 | ローカル検証 | 完了（2026-08-09、Docker build/run実機確認のみフェーズ4へ持ち越し） |
| 4 | 本番デプロイと切り戻し準備 | 完了（2026-08-09、手動デプロイ、詳細はphase-4参照） |
| 5 | 継続追従運用の仕組み化 | 完了（2026-08-09、CI自動化(drift Issue)は撤回しオンデマンド運用に変更） |
| 6 | 案Aへの移行（フェーズ1で案Cを選んだ場合のみ） | 対象外（案A採用のため不要） |

詳細は `.claude/phases/phase-0-tag-cleanup.md` 以下、各フェーズごとのファイルを参照。

## 今後の検討事項（このプランの範囲外・バックログ）

- **スタックenvの差分更新ツール**（2026-08-09提案）: `PORTAINER_EXPOSE_ENV_VALUES=1`を
  本番で有効にしているのは、Portainerの`StackUpdate` APIが`Env`配列を全置換方式で
  受け取る仕様のため、他スタックを差分更新する際に既存env値をLLM側が読めないと
  安全に更新できないことが理由（フェーズ4完了後に判明）。portainer-mcp側に
  「サーバ内部で現在の全Env値を取得（LLMには見せない）→渡された差分をマージ→
  全体を送信」という新しいハンドライトツールを追加すれば、`PORTAINER_EXPOSE_ENV_VALUES`を
  有効にせずに済む可能性がある。upstream追従計画（本ファイル）の範囲外の新機能提案として、
  この一連の作業完了後に別途plannerで検討する。

## 運用ルール（このプランに固有）

- フェーズ1→2、フェーズ3→4はユーザー承認必須（設計判断／本番影響のため）。
- フェーズ2は `Agent(subagent_type="fork", isolation="worktree")` に委譲。
- ホームラボ固有情報（overlay CIDR、ホスト名、Portainer URL、APIキー、GHCR認証情報）は
  このレポのいかなるファイルにも書かない。変数名と意味のみを記載し、具体値はユーザーへの
  口頭確認・報告に留める。
- `pyproject.toml` の `version` はフェーズ2以降 upstream の値のまま編集しない
  （フォーク独自リリースは `hl-<upstream-version>-<fork-rev>` タグで区別する）。

## 継続運用（フェーズ5以降）

このレポは公開レポであり、私有レポのようなIssueベースの課題管理は行わない方針のため、
upstream追従の検知はCI駆動の自動化（GitHub Actions + Issue起票）ではなく、
**ユーザーが依頼したタイミングで`upstream-sync`スキルを使った半自動対応**とする
（2026-08-09、CI自動化案からこの方針に変更。理由: このリポジトリはGitHub Issues機能
自体を無効化しており、Issue駆動の通知は成立しない。加えて公開レポでの運用方針として
そもそもIssueを使わない）。

ユーザーが「upstream追従して」「upstreamとの差分を確認して」等と依頼した際に
`.claude/skills/upstream-sync/SKILL.md`の手順（`git fetch upstream`→差分確認→
`git merge-tree`での事前コンフリクト予測→…）に従って対応する。フォーク独自差分の
一覧は`.claude/FORK-DELTA.md`を参照。
