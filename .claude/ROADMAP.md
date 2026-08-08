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
| 1 | HTTP認証・TLSポスチャの方針決定（コード変更なし） | 未着手 |
| 2 | upstream/mainのマージとフォークパッチ再適用 | 未着手 |
| 3 | ローカル検証 | 未着手 |
| 4 | 本番デプロイと切り戻し準備 | 未着手 |
| 5 | 継続追従運用の仕組み化 | 未着手 |
| 6 | 案Aへの移行（フェーズ1で案Cを選んだ場合のみ） | 条件付き・未着手 |

詳細は `.claude/phases/phase-0-tag-cleanup.md` 以下、各フェーズごとのファイルを参照。

## 運用ルール（このプランに固有）

- フェーズ1→2、フェーズ3→4はユーザー承認必須（設計判断／本番影響のため）。
- フェーズ2は `Agent(subagent_type="fork", isolation="worktree")` に委譲。
- ホームラボ固有情報（overlay CIDR、ホスト名、Portainer URL、APIキー、GHCR認証情報）は
  このレポのいかなるファイルにも書かない。変数名と意味のみを記載し、具体値はユーザーへの
  口頭確認・報告に留める。
- `pyproject.toml` の `version` はフェーズ2以降 upstream の値のまま編集しない
  （フォーク独自リリースは `hl-<upstream-version>-<fork-rev>` タグで区別する）。
