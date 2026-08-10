# envdiffフェーズ3: ドキュメント整合とfork delta棚卸し

目安: 1〜2時間。実施主体: メインセッション。コード変更なし
（reviewer任意、内容確認は目視でよい）。

## ゴール

実装内容がリポジトリのドキュメントに反映され、次回のupstream追従が
正しい前提で走る。

## タスク

1. `CLAUDE.md`のArchitecture節「Swarm tools are hand-written in `swarm.py`」の
   段落に、`updateSwarmStack`がread-modify-write（envはサーバ側マージ、値は
   ツール出力に出さない）である旨と、その理由（`PUT /stacks/{id}`のEnv全置換
   セマンティクス）を追記する。「Env variable values are intentionally
   excluded from service responses」の一文と並べる。
   併せて、`dry_run`パラメータの存在（PUTを送らず変更内訳のみ返すプレビュー
   モード）と、read-onlyモードでも`dry_run=True`だけは許可されること
   （envdiff-2bで追加した意味論変更）を同じ段落に追記する。

2. `.claude/FORK-DELTA.md`の差分表を更新する:
   - `swarm.py`行の「変更内容」にenv差分マージを追記
   - `proxy.py`行を新規追加（フェーズ2実施分。「upstreamで代替されたら
     削除できる条件」に「upstream PRがマージされたら削除」と書く）
   - `skills/portainer-mcp-hygiene/SKILL.md`行を新規追加（フェーズ2の
     ガイド追記分。同様に「upstream PRがマージされたら削除」）
   - **`CLAUDE.md`行の記述を実態に合わせて修正する**（現状「Versioning節の
     fork段落のみ」となっているが、実際は`git diff upstream/main..HEAD --
     CLAUDE.md`が29行あり、Architecture節のswarm解説も含めfork差分。
     今回の追記でさらに増える）
   - **`.gitignore`（2行、`.claude/worktrees/` / `.claude/agent-memory/`）を
     表に追加する**（現状未記載）
   - 「運用ノート」の`PORTAINER_EXPOSE_ENV_VALUES=1`の項を、フェーズ4完了時に
     書き換える前提でマークしておく

3. `.claude/ROADMAP.md`は既に「プロジェクト2: スタックenv差分更新ツール」節で
   このプロジェクト全体を記載済み（本フェーズでは各envdiff-phaseの状態を
   更新するのみ）。

4. `docs/configuration.md`の`PORTAINER_EXPOSE_ENV_VALUES`の説明はそのまま
   （upstreamファイル、フォーク都合の追記はしない）。

## 完了条件

- [x] `git diff --stat upstream/main..HEAD`の各行が`.claude/FORK-DELTA.md`の
      差分表に1対1で存在する（`.claude/**`配下を除く）
- [x] `.claude/ROADMAP.md`のenvdiffフェーズ一覧が実態に即して更新されている
- [x] `.gitignore`が`.claude/FORK-DELTA.md`の表に記載されている

## 実施結果（2026-08-10）

メインセッションで実施（コード変更なし）。

- `CLAUDE.md`のArchitecture節「Swarm tools are hand-written in `swarm.py`」段落に
  `updateSwarmStack`のread-modify-write化（env差分マージ・値非公開・sentinelガード）
  と`dry_run`（read-onlyモードでも許可される旨含む）を追記
- `.claude/FORK-DELTA.md`の差分表を更新: `swarm.py`行に envdiff-1〜2b の内容を追記、
  `proxy.py`/`skills/portainer-mcp-hygiene/SKILL.md`/`tests/test_proxy.py`の3行を
  新規追加、`CLAUDE.md`行の記述を実態（複数箇所への追記）に合わせて修正、
  `.gitignore`行を新規追加、運用ノートの`PORTAINER_EXPOSE_ENV_VALUES=1`項に
  envdiff-4完了時の書き換え予定を明記
- `git diff --stat upstream/main -- . ':!.claude'`で列挙される15ファイルすべてが
  `.claude/FORK-DELTA.md`の差分表にbacktick付きパスとして1対1で存在することを
  機械的に突合して確認済み（当初`tests/test_proxy.py`の記載漏れを検出し追加）
- `.claude/ROADMAP.md`のenvdiff-1〜3のステータスを実態に更新
- `docs/configuration.md`はupstreamファイルのため変更なし（プランどおり）
