# フェーズ5: 継続追従運用の仕組み化

目安: 3〜4時間。実施主体: メインセッション。コミット前にメインセッションからreviewerを呼ぶ。

## ゴール

upstreamの新コミットが自動で通知され、次回の同期が手順書どおりに実行でき、フォーク独自差分の
棚卸しが毎回ゼロから調査しなくて済む状態になっている。

## タスク

1. `.claude/FORK-DELTA.md` を新規作成する。フォーク独自差分を1パッチ1行で管理する表:
   対象ファイル / 変更内容 / 存在理由 / upstreamで代替されたら削除できる条件 / 最終確認日
   - 初期エントリ: swarmツール（`swarm.py` + `tests/test_swarm.py` + `server.py` のimport行と
     register行）、ツール名リマップ（`_TOOL_NAME_REMAP` + `_annotate_read_only` の1行）、
     `Dockerfile` のHEALTHCHECKポート動的化、GHCR切替＋`latest`、`release.yml`/`release-test.yml`
     削除（PyPI非配布）、`release-mcpb.yml` の `workflow_dispatch` 化、`tests/test_tool_names.py`、
     フェーズ2タスク3-5（案B/Cの共有キーパッチ）および3-6（ハンドライトツールへの明示配線）を
     入れた場合はそれぞれ独立エントリ
   - 「`pyproject.toml` の `version` は編集しない」という不変条件も明記する
     （**CIで強制せず運用上の合意として扱う**。強制するとupstream側のversion更新まで弾いてしまうため）
2. `.github/workflows/upstream-drift.yml` を新規作成する。週次スケジュール（`schedule: cron`）+
   `workflow_dispatch` で:
   - `actions/checkout` を `fetch-depth: 0` で実行し、`git remote add upstream
     https://github.com/portainer/portainer-mcp` → `git fetch upstream main`
   - `git rev-list --count HEAD..upstream/main` が0より大きければ、`gh issue` で
     「upstream drift: N commits」という固定タイトルのIssueを作成または更新し、本文に
     `git log --oneline HEAD..upstream/main` と `git diff --stat` を貼る
     （既存のopen Issueがあればコメント追記して重複を防ぐ）
   - 差分が0なら何もしない
   - `permissions:` ブロックを最小権限（`contents: read`, `issues: write`）で明示する
3. `.claude/skills/upstream-sync/SKILL.md` を新規作成し、今回の手順を再利用可能な形で記録する:
   - `git fetch upstream` → `git log --oneline HEAD..upstream/main` で差分確認
   - `git merge-tree --write-tree HEAD upstream/main` で**マージ前にコンフリクト箇所を予測**する
     （作業ツリーを汚さずコンフリクト対象ファイルだけを列挙できる）
   - コンフリクトが想定される箇所（`server.py` のHTTP認証分岐とregister順序）と、
     `.claude/FORK-DELTA.md` を突き合わせる手順
   - specが更新された場合の必須チェック: `tests/test_tool_names.py` のPASS、
     `git diff <前回のフォークタグ>..HEAD -- src/portainer_mcp/data/portainer-patched.yaml |
     grep -E '^[+-]\s+operationId:'` によるoperationIdの増減確認（`_TOOL_NAME_REMAP` の棚卸しに直結）、
     `profiles.py` の新規タグ確認
   - タグ付け規約（`hl-<upstream-version>-<fork-rev>`）とデプロイ手順への接続
4. `docs/release.md` にフォーク運用の節を追記し、上記スキルへの参照を張る。
5. `.claude/ROADMAP.md` に「upstream追従は月次またはdrift Issue起票時に実施」という運用リズムを記載する。

## 完了条件

- [x] `.claude/FORK-DELTA.md` が存在し、`git diff --stat upstream/main..HEAD` で出るファイルが
      すべて表に載っている
- [x] ~~`gh workflow run upstream-drift.yml` を手動実行して成功し、差分0の状態ではIssueが
      作られないことを確認できる~~ — **タスク2自体を撤回**（下記「実施結果」参照）。
      代わりに、オンデマンド運用（ユーザー依頼時に`upstream-sync`スキルで対応）へ変更した
- [x] `.claude/skills/upstream-sync/SKILL.md` が存在し、`git merge-tree --write-tree` による
      事前コンフリクト予測手順とoperationId差分確認手順が含まれている
- [x] `.claude/ROADMAP.md` に追従サイクルの記載がある（オンデマンド運用として記載）

## 実施結果（2026-08-09）

タスク1・3・4・5は計画どおり実施。**タスク2（`.github/workflows/upstream-drift.yml`によるCI
駆動のdrift検知・Issue自動化）は実装後に撤回した**。

- 実装 → `gh workflow run`で実機検証 → `gh api repos/whitehara/portainer-mcp --jq '.has_issues'`
  が`false`、すなわち**このリポジトリはGitHub Issues機能自体を無効化している**ことが判明。
  Issue駆動の通知は原理的に成立しない。
- 加えてユーザーから「公開レポであるため、私有レポのようにIssueを課題管理としない。
  upstream追随はユーザーからの依頼で行い、スキルで半自動対応とする」という運用方針が
  示された。
- そのため`.github/workflows/upstream-drift.yml`を削除し、GitHub上に作成済みだった
  `upstream-drift`ラベルも削除。`.claude/ROADMAP.md`・`docs/release.md`・
  `.claude/skills/upstream-sync/SKILL.md`から関連記述を除去し、「ユーザーが依頼した
  タイミングで`upstream-sync`スキルを使う」オンデマンド運用に統一した。
- `.claude/FORK-DELTA.md`はこのワークフローに一度も言及していなかったため、削除に伴う
  修正は不要だった。

結果として、フェーズ5のゴール（「upstreamの新コミットが自動で通知され」）のうち
「自動通知」の部分は当初計画から撤回されたが、「次回の同期が手順書どおりに実行でき、
フォーク独自差分の棚卸しが毎回ゼロから調査しなくて済む」という残りの目的（スキル化・
FORK-DELTA.md整備）は達成している。

## リスク・注意点

- CLAUDE.mdの「Project / Issueの書き込みはメインセッションのみ」ルールはサブエージェントに対する
  制約であり、CIワークフローには適用されない。ただし本レポはProject運用ではなく、かつ
  GitHub Issues機能自体を使わない方針のため、drift検知自体をIssueに紐付けない（上記の通り
  この仕組み自体を撤回した）。
