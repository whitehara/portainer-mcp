# フェーズ2: upstream/mainのマージとフォークパッチ再適用

目安: 半日〜1日。実施主体: `Agent(subagent_type="fork", isolation="worktree")` に委譲。
ブランチ名例: `chore/upstream-sync-2.44.0`。reviewerはworktree内で通す（コミットしない、メインセッションが行う）。

**前提**: フェーズ1が完了・コミット済みであること。委譲プロンプトには
フェーズ1の決定内容（特にタスク2の passthrough 配線要否）を転記すること
（コミットで参照可能にしたうえで、プロンプト本文にも転記。両方行う）。

## ゴール

`main` から切ったブランチ上で `upstream/main`（28コミット）がマージされ、
フォーク独自機能（swarmツール・ツール名リマップ・フェーズ1で決めた認証構成）が
すべて動作し、`uv run pytest` が全件PASSする。

## タスク

1. `git merge upstream/main` を実行。コンフリクトは `pyproject.toml` と
   `src/portainer_mcp/server.py` の2ファイルのみ発生する（実測済み）。upstreamが
   新規追加したファイル（`release-mcpb.yml` 等）はコンフリクトせず自動で入ってくる。
2. `pyproject.toml` のコンフリクトを解決: **upstream側を全面採用**
   （`version = "2.44.0"`、`cryptography>=42` 追加、`fastmcp>=3.4.2`、`starlette`
   直接ピン削除、SKILL.md同梱、`mcpb` dependency-group）。フォーク側の
   `version = "2.42.7"` は捨てる。**以後フォークはこの行を編集しない**。
3. `src/portainer_mcp/server.py` のコンフリクトを解決。upstream側の新しい
   `build_server()` を土台に、フォークパッチ（必須4件＋条件付き2件）を再適用:
   1. `from portainer_mcp import (...)` に `swarm` を追加
   2. モジュール定数 `_TOOL_NAME_REMAP` を復元
   3. `_annotate_read_only()` 内のリマップ処理を復元
   4. `proxy.register(mcp, client, read_only=read_only)` の直後に
      `swarm.register(mcp, client, read_only=read_only)` を挿入。
      **`guidance.register()` および `mcp.add_transform(shaping.SelectArgTransform())` より前**に置くこと
   5. （フェーズ1で案B/Cを選んだ場合のみ）フェーズ1文書に記録した共有キー用の分岐を
      `if transport == "http":` ブロック先頭に追加
   6. （フェーズ1タスク2で「ハンドライトツールに明示配線が必要」と判明した場合のみ）
      フェーズ1文書に記録された配線内容を `swarm.py` および `proxy.py` に適用。
      この場合、フェーズ5の `.claude/FORK-DELTA.md` に独立エントリとして追加する対象になる

   **HEALTHCHECKの扱い**: 「自動マージされるので手を入れない」と断定しない。
   マージ後に `Dockerfile` のHEALTHCHECK行を確認する。コンフリクトしなかった場合は
   `PORTAINER_MCP_HTTP_PORT` を参照する形が残っていることだけ確認する。
   **コンフリクトした場合は `PORTAINER_MCP_HTTP_PORT` を参照する側（フォーク側の実装）を採用**して解決する。
4. `_TOOL_NAME_REMAP` の内容を新spec（2.44.0）に合わせて棚卸し:
   - 削除: `"Upload_a_file_under_a_specific_path_on_the_file_system_o"`
     （新specで `EndpointDockerBrowsePut` に変わり生成されなくなる）
   - 追加: `"CurrentUserEndpointNamespaceAuthorizationsInspect"`（49文字、`users`タグ /
     `/users/me/auth/{endpointID}/namespaces`）→ 40文字以内の短縮名を割り当てる。
     制約: 「40文字以内」「既存ツール名と重複しない」「元の操作内容が推測できる」の3点。具体名は実装側の裁量。
   - 既存6件（`GetKubernetesIngressControllersByNamespace` ほか）は新specにも同名で存在するため維持
5. `tests/test_tool_names.py` を新規追加。`server.build_server()` で構築したサーバの
   全ツール名について `len(name) <= 40` を検証する回帰テスト。既存の `tests/test_server.py`
   のフィクスチャ／envスタブの流儀に合わせる。
6. `CLAUDE.md` の自動マージ結果を確認・修正。upstream側の追記（guidance / passthrough /
   auth_posture / tls / timeouts）とフォーク側のswarm記述が両立しているか確認し、
   フェーズ1で決めた認証構成に合わせて「HTTP transport requires a bearer token」節を書き直す。
7. `docs/configuration.md` に、フォーク独自の環境変数（案B/Cを選んだ場合の共有キー用フラグ）を追記。
   案Aかつ追加envなしなら追記不要。
8. `.github/workflows/release-mcpb.yml` を `on:` が `workflow_dispatch` のみになるよう変更
   （フォークは `.mcpb` バンドルもPyPIも配布しないが、upstreamとの差分を最小にするためファイル自体は残す）。
9. `uv sync` → `uv run pytest` を実行して全件PASSを確認。
10. reviewerサブエージェントでコミット前レビューを通す（要対応の指摘がなくなるまで反復）。
    **コミットはしない**（メインセッションが行う）。

## 完了条件

- [ ] `git log --oneline -1` がマージコミットを示し、`git rev-list --count HEAD..upstream/main` が `0`
- [ ] `uv run pytest` が全件PASS（新規の `tests/test_tool_names.py` を含む）
- [ ] `uv build` が成功し、`unzip -l dist/*.whl | grep SKILL.md` がヒットする
- [ ] `grep -n "swarm.register" src/portainer_mcp/server.py` がヒットし、その行番号が `mcp.add_transform` の行番号より小さい
- [ ] `_TOOL_NAME_REMAP` に `Upload_a_file_...` が存在せず、`CurrentUserEndpointNamespaceAuthorizationsInspect` が存在する
- [ ] `Dockerfile` のHEALTHCHECKが `PORTAINER_MCP_HTTP_PORT` を参照している
- [ ] フェーズ1文書で「明示配線が必要」とされた場合、その配線が `swarm.py` / `proxy.py` に入っている（不要とされた場合は変更なし）
- [ ] `docker build -t portainer-mcp:sync-test .` が成功する
- [ ] reviewerサブエージェントが要対応指摘なしでPASS

## リスク・注意点

- **`swarm.py` の改修要否はフェーズ1タスク2の結論に完全に従うこと。**「共有clientなので自動で効く」と仮定して無改修で進めない。実際にcallerのキーが使われるかはフェーズ3タスク4の実測でも再確認する。
- 案Aではswarmツールもcallerのキーの権限に従うため、権限不足で挙動が変わる可能性がある。
- upstreamの `redaction.count_in()` 導入で、`select` でenvフィールドを落とした場合のリダクション件数報告が変わる。`swarm.py` は独自にenv値を除外しているため、二重報告や不整合が出ないか `tests/test_swarm.py` の結果を確認する。
- `release-docker.yml` は自動マージでupstreamのmulti-arch化（`setup-qemu-action` 追加 + `platforms: linux/amd64,linux/arm64`）を取り込む。QEMU経由のarm64ビルドはビルド時間が大幅に伸びる。arm64が不要なら `platforms: linux/amd64` に戻すか、そのまま受け入れるかをユーザーに確認すること。
- **rebase / cherry-pickは使わないこと。** originにタグ済み・push済みの履歴を書き換えることになり、rebase方式は同期のたびに同じコンフリクトを再解決させられる（merge + rerereなら2回目以降が軽くなる）。
