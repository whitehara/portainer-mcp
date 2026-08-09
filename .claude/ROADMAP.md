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

## プロジェクト2: スタックenv差分更新ツール（envdiff、2026-08-09開始）

upstream追従計画（フェーズ0〜6）完了後に着手した別プロジェクト。

### 背景

`PORTAINER_EXPOSE_ENV_VALUES=1`を本番で有効にしているのは、Portainerの`StackUpdate`
APIが`Env`配列を全置換方式で受け取る仕様（researcherが`portainer/portainer`ソースコードで
確認済み。省略時は既存値を全消去、Kubernetesスタックのみ`Env`フィールド自体が無く対象外）
のため、他スタックを差分更新する際に既存env値をLLM側が読めないと安全に更新できないことが
理由（フェーズ4完了後に判明）。planner→planner-cross-review（2回反復、機械的パッチ適用で
収束）を経て、`updateSwarmStack`をサーバ内部でread-modify-writeする形に拡張する計画を
策定・承認済み。

### フェーズ一覧

| フェーズ | 内容 | 状態 |
|---|---|---|
| envdiff-1 | `updateSwarmStack`のread-modify-write化 | 未着手 |
| envdiff-2 | `[REDACTED]`書き戻しガード＋hygieneガイド追記 | 未着手 |
| envdiff-3 | ドキュメント整合とfork delta棚卸し | 未着手 |
| envdiff-4 | 実機検証と本番`PORTAINER_EXPOSE_ENV_VALUES`撤去 | 未着手 |

詳細は`.claude/phases/envdiff-phase-1-read-modify-write.md`以下、各フェーズごとの
ファイルを参照。

### この計画に固有の決定事項

- env省略時の既定動作: **保持**（現状の全消去は実質的にバグと判断、破壊的変更として
  ユーザー承認済み）
- 既存`env`パラメータは`env_replace`に改名（互換維持しない）
- 単一ツール（`updateSwarmStack`拡張）に集約。新規ツールは追加しない
- git連携スタックは既定拒否、`allow_git_stack=True`の明示オプトインのみ許可
  （`AutoUpdate`消失は自動復元しない）
- Kubernetesスタック（Type=3）は未検証のため拒否
- フェーズ2の`[REDACTED]`書き戻しガードは`proxy.py`（upstream由来ファイル）に入るため、
  実装後にupstreamへのPR提出を検討する
- フェーズ2で`skills/portainer-mcp-hygiene/SKILL.md`（upstream由来、`get_guidance`で
  配信される運用ガイド）にも横断的な注意事項（`[REDACTED]`を書き戻さない）を追記する。
  これもupstreamにとって有益な一般原則のため、将来的にupstream PRを検討する
- フェーズ3→4はユーザー承認必須（本番影響）

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
