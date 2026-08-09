# envdiffフェーズ1: `updateSwarmStack`のread-modify-write化

目安: 3〜5時間。実施主体: worktree fork委譲推奨（規模があるため）。
コミット前にreviewerを通す。

## ゴール

`updateSwarmStack`が、env値を一切ツール出力に出さないまま、既存envの保持・
差分追加/変更/削除を安全に行える状態。`PORTAINER_EXPOSE_ENV_VALUES`が
未設定でもスタック更新が完結する。

## 背景

Portainerの`StackUpdate` API（`PUT /stacks/{id}`）は`Env`配列を全置換方式で
受け取る（researcherがCE 2.44.0の`portainer/portainer`ソースコードで確認済み。
`api/http/handler/stacks/stack_update.go:271,350`で`stack.Env = payload.Env`と
無条件代入。省略時はGoのnilスライスが代入され全消去）。現状の`swarm.py`の
`update_swarm_stack`は`"env": env or []`と全件必須の設計になっており、
本番で`PORTAINER_EXPOSE_ENV_VALUES=1`を有効にしないと安全に使えない状態。

## タスク

対象ファイル: `src/portainer_mcp/swarm.py`（`update_swarm_stack`、421-473行付近）

1. シグネチャ変更:
   - `compose_file: str | None = None`（必須→任意）
   - `env: list[dict] | None`を削除し、代わりに以下を追加:
     - `env_set: dict[str, str] | None = None`（追加/上書きしたい変数のみ）
     - `env_unset: list[str] | None = None`（削除したい変数名のみ）
     - `env_replace: list[dict] | None = None`（全置換のエスケープハッチ。`[{name, value}]`）
   - `allow_git_stack: bool = False`を追加
   - `pull_image` / `prune`は現状維持

2. 関数冒頭、`read_only`チェック直後に`GET /stacks/{stack_id}`を発行するプリフライトを追加:
   - `Type`が1（Swarm）以外なら`ToolError`（「updateSwarmStackはSwarmスタック専用」。
     K8sスタックでのEnv扱いは未検証のため断定せずガードで除外する）
   - `GitConfig`が非nullかつ`allow_git_stack`がFalseなら`ToolError`。メッセージには
     「このスタックはgit連携されている。env のみ変更したい場合はPortainer UIもしくは
     gitリポジトリ側で変更し`StackGitRedeploy`を使うこと。本ツールで強行するとgit連携と
     AutoUpdate設定が失われ、再設定は手動になる」旨を含める
   - `allow_git_stack=True`は「git連携とAutoUpdateが失われることを呼び出し側が承知した
     上での強制実行」を意味する。**失われた設定は自動復元しない**。この意味論をdescriptionと
     返り値（`allow_git_stack=True`時に`"auto_update_cleared": true`を含める）の両方に明記する
   - `Env`（`[{name, value}]`）→ マージのベース

3. モジュールレベルのヘルパ`_merge_env(current, set_, unset) -> tuple[list[dict], dict]`を
   追加する（`register()`の外側。既存の`_infer_access_type` / `_strip_docker_frames`と
   同じ扱い。`test_swarm.py`から直接importしてテストできるようにする）:
   - 入力pairは`name`/`Name`、`value`/`Value`の両綴りを受け付け、出力は常に小文字
     `{"name": ..., "value": ...}`に正規化
   - `value`欠落は`""`として扱う
   - **重複解決**: 重複が起こり得るのは既存Env配列内のみ（`env_set`はdictなのでキー重複は
     構造上発生しない）。同一`name`が既存配列に複数現れた場合は**最後に出現した要素のvalueを
     採用**し、1件に畳む
   - 出力順: 既存配列の初出順→その後に新規追加分（`env_set`のうち既存に無かったキー、
     dictの挿入順）
   - 内部サマリ（ログ・デバッグ用、外部には出さない）: `{"added": [...], "updated": [...],
     "removed": [...], "unchangedCount": int, "notFound": [...], "deduped": [...]}`

4. 引数の排他チェック: `env_replace`と（`env_set`または`env_unset`）の同時指定は`ToolError`。
   3つとも`None`のときは「現在値をそのまま再送」。

5. `compose_file`が`None`のとき`GET /stacks/{stack_id}/file`を発行し、レスポンスの
   `StackFileContent`フィールドの値をPUTボディの`stackFileContent`キーにそのまま渡す
   （キー名の綴りがGETとPUTで異なる点に注意）。取得失敗・`StackFileContent`欠落・空文字は
   いずれも`ToolError`（**空文字を送らない**——空のcomposeファイルはスタックを破壊する）。

6. エラーボディのスクラブ関数`_scrub(text, secret_values) -> str`を追加し、この関数を
   全`ToolError`メッセージ（プリフライト・PUTの両方）に適用する。`secret_values`は
   ステップ2で読んだ既存env値の集合＋`env_set`の値。仕様:
   - **単純な文字列置換**（`str.replace`）。正規表現は使わない
   - **値を長さの降順にソートしてから順に置換する**（短い値を先に置換すると長い値の
     一部だけが`[REDACTED]`に変わって残りが漏れるため）
   - 空文字および4文字未満の値はスクラブ対象から除外する
   - **スクラブを先に行い、その後で`[:500]`の切り詰めを行う**（順序厳守。逆順にすると
     500文字境界で分断された秘密値が完全一致しなくなりスクラブをすり抜ける）
   - スクラブ範囲は意図的に広く取る（値の中身が秘密かどうかのヒューリスティック判定は
     行わない。公開URLのような無害な値が置換されるのは許容する。誤検知より漏洩の方が
     コストが高いため）
   - 理由: `proxy.py:123-133`の「エラーボディは呼び出し元自身のペイロードだから
     redactしない」というupstreamの判断は、サーバ側で読んだ値を送るこのツールには
     適用できない

7. PUT成功後の返り値: `{"id": <int>, "updated": true, "env_names": [...],
   "env_removed": [...]}`（既存ツールの命名様式=小文字スネークケースに合わせる。
   camelCaseは新規導入しない）
   - `env_names`: マージ後にPortainerへ送信したenv配列の`name`全件（送信順のまま。
     値は一切含めない）。Portainerのレスポンスに`Env`が無い/空の場合は、サーバが
     送信したマージ後env配列の`name`全件にフォールバックする（どちらの経路でも
     「更新後スタックに存在するenv変数名の全集合」という意味を一致させる）
   - `env_removed`: `env_unset`で実際に削除された名前のみ（存在しなかった名前は含めない）
   - `allow_git_stack=True`の場合は`"auto_update_cleared": true`を追加
   - キー名に`env` / `envvars`（`redaction._ENV_KEYS`と完全一致するもの）を使わない
     （`_select_wrapper`のredaction walkerが拾って名前配列を壊す可能性を避けるため）

8. ツールのdescriptionを書き換える（文面は実装時に決めてよい）。含める要素:
   - envは差分指定。省略した変数は保持される（現行の「All current environment
     variables must be included — omitting one removes it.」は削除）
   - 現在の変数名を知るには`StackInspect`を先に呼ぶ（値は`[REDACTED]`で返るが名前は見える）
   - 値そのものは決して返らない。返るのは変更された変数名だけ
   - `compose_file`省略時は現在のファイルを保持
   - 全消去は`env_replace=[]`
   - `allow_git_stack=True`はAutoUpdate設定を失う（自動復元しない）

9. `tests/test_swarm.py`にテストを追加する。既存の`_make_mock_client` /
   `mcp_with_swarm`フィクスチャ（実装を読んで既存様式に合わせること）に
   `/stacks/10`（GET: `Type=1`, `Env=[{name:A,value:"s3cr3t-alpha"},
   {name:B,value:"s3cr3t-bravo"}]`, `GitConfig=None`）、`/stacks/10/file`、
   `/stacks/12`（`GitConfig`非null）、`/stacks/13`（`Type=3`）を足し、PUTを
   記録するハンドラにする:
   - `test_merge_env_preserves_when_omitted`
   - `test_merge_env_set_upsert`
   - `test_merge_env_unset`
   - `test_merge_env_replace_empty_wipes`
   - `test_merge_env_replace_conflicts_with_set`
   - `test_merge_env_dedupes_duplicate_names`（後方の値が採用されること）
   - `test_merge_env_accepts_capitalized_pair_keys`
   - `test_update_keeps_compose_file_when_omitted`
   - `test_update_rejects_git_backed_stack` / `test_update_rejects_kubernetes_stack`
   - `test_update_response_contains_no_env_values`（`"s3cr3t-alpha"` /
     `"s3cr3t-bravo"`が返り値JSON文字列に含まれないこと）
   - `test_error_body_scrubbed`
   - `test_error_body_scrub_across_500_char_boundary`（秘密値が500文字境界を
     またぐエラーボディで、出力に秘密値の部分文字列が残らないこと）

## 完了条件

- [x] `uv run pytest tests/test_swarm.py -q` が全PASS（33件、新規13件含む）
- [x] `uv run pytest -q` が全PASS（318件、既存テストの回帰なし）
- [x] `uv run pytest tests/test_swarm.py --collect-only -q` に上記13テストが全て現れる
- [x] `uv run pytest tests/test_tool_names.py -q` がPASS
- [x] `grep -n 'resp.text\[' src/portainer_mcp/swarm.py` の結果のうち、
      `update_swarm_stack`内のものが全て`_scrub(...)`経由になっている
- [x] `git diff --stat upstream/main..HEAD` で新規に変更されたファイルが`swarm.py`と
      `tests/test_swarm.py`のみ

## 実施結果（2026-08-09）

worktree fork委譲で実装。reviewer PASS（Blocker/Should 0件）。任意指摘2件
（`removed`リストの非決定的な順序、`allow_git_stack=True`時に実際はgit連携で
なくても`auto_update_cleared`を返してしまう点）も追加で修正済み
（`allow_git_stack and stack.get("GitConfig")`の両方を満たす場合のみ返す形に修正）。
`ruff check`もPASS。mainへfast-forwardマージ・push済み。

## リスク・注意点

- PUTボディのキーは現行どおり小文字`env` / `stackFileContent`を維持する（Goの
  JSONデコードはフィールド名がケース非依存で、本番で実績があるため）
- `dict[str, str]`の`env_set`はJSON Schemaの`additionalProperties: string`になる。
  FastMCPのスキーマ生成で問題が出たら`list[dict]`（`[{name, value}]`）にフォールバック
- TOCTOUは残る（readとwriteの間に他者がenvを変更すると上書きする）。Portainerに
  ETag/version条件付き更新は無いため回避不能。返り値の`env_names`をLLMに確認させる
  以上のことはしない
