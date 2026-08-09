# envdiffフェーズ2b: `updateSwarmStack`のdry_runプレビュー

目安: 2〜3時間。実施主体: メインセッション（1ファイル+テストで完結するためworktree
fork委譲は必須ではない。envdiff-2をworktreeで実施した場合は同じworktreeで継続してよい）。
コミット前にreviewerを通す。

**前提**: envdiff-2（`[REDACTED]`書き戻しガード）が完了済みであること。本フェーズは
envdiff-2のコードが`update_swarm_stack`に入っている状態を出発点とする。

## 経緯

ユーザーからの「ドライラン/what-ifのようなモードを追加できないか。AIが影響を検証
できるように」という要望を受け、`updateSwarmStack`限定で対応する方針で
planner→planner-cross-review（3回反復）を実施。3回とも「未収束」判定だったが、
指摘は毎回プラン文面の曖昧さ（用語の混同・省略解釈の余地）に限られ、設計判断
そのものへの異論はなかった。上限到達によりスキルの規定に従い人手判断へ差し戻し、
ユーザーが最終プランのまま承認（2026-08-10「進めて」）。

## ゴール

1. `updateSwarmStack`に`dry_run`を追加し、`dry_run=True`のとき`PUT /stacks/{id}`を
   一切送らずに、マージ後のenv変数名一覧と「追加/変更/削除/該当なし」の名前別内訳、
   composeファイルが変わるか否かを返す。
2. **不変条件: 返り値にenvの「値」はdry_runでも実行パスでも一切含めない。** 返すのは
   常に変数「名」と件数のみ。これは本フェーズの中核要件であり、他のどの要件よりも
   優先する。

副次的に、既存の欠陥を1件修正する: `update_swarm_stack`は`env_replace`分岐で
`removed_names`を一切埋めていない（`env_replace=[]`で全env削除しても`env_removed: []`
と返る）。

## 設計判断（4論点）

| 論点 | 判断 | 理由 |
|---|---|---|
| dry_runで`read_only`チェックをスキップするか | **スキップする**（`if read_only and not dry_run:`） | dry_runが発行するのは`GET /stacks/{id}`と`GET /stacks/{id}/file`のみで、どちらもread-onlyモードでも`StackInspect`/`StackFileInspect`として既に呼べる。新たに到達可能になる情報はゼロ。`dry_run=False`は従来どおり拒否されるので権限昇格経路にならない |
| 返り値の形 | **実行パスと同じキー集合のsuperset** | プレビューと実行結果をフィールド単位で突き合わせられる |
| git連携・K8sガード | **dry_runでも同じ`ToolError`で落とす（緩めない）** | 「本番と同じ判定を、書き込みだけ抜いて実行する」忠実性を優先。ガードを緩めると「プレビューは通ったのに本番で落ちた」が起きる |
| 規模 | **フル（1フェーズ）プラン** | 返り値契約の変更+read_only意味論+他フェーズとの順序依存を含むため |

read_onlyの扱いはA1（dry_runはread-onlyでも許可・採用）とA2（全拒否）の二択で
A1を採用。`compose_file_changed`はスコープに含める（案D＝削る案は不採用）。

## タスク

対象ファイルは`src/portainer_mcp/swarm.py`と`tests/test_swarm.py`の2つのみ。

1. `swarm.py`のモジュールレベルに正規化ヘルパを切り出す。現在`_merge_env`冒頭にある
   「`name`/`Name`・`value`/`Value`両綴り受理→初出順`order`/`values` dict/`deduped`を
   作る」ループを`_normalize_pairs(pairs: list[dict]) -> tuple[list[str], dict[str, str], list[str]]`
   （初出順の名前リスト/名前→値dict/`deduped`リスト）として独立させ、`_merge_env`は
   これを呼ぶ形に書き換える。**これは純粋な抽出（extract function）であり、意味論の
   再定義ではない。** `deduped`の算出条件・値の上書き規則（先勝ちか後勝ちか）・順序の
   決め方・綴り違いキーの優先順位はすべて現在の`_merge_env`のコードをそのまま移動
   すること。実装前に`_merge_env`の当該ループを読み、その挙動を1バイトも変えずに
   移すこと。`_merge_env`の返り値・外部挙動は完全に不変。

2. `swarm.py`に`_replace_summary(current: list[dict], replacement: list[dict]) -> tuple[list[dict], dict]`
   を追加する。**これはenv置換のサマリ算出ヘルパであり、envdiff-2のsentinelガードとは
   無関係。**
   - 第1要素（`list[dict]`）は`_merge_env`の第1要素と同じ形式のマージ後Envペアリスト。
     `env_replace`の場合は「正規化・重複除去済みの`replacement`」そのもの（現在値は
     一切引き継がない）。ペアの綴り・キー順は`_merge_env`が実際に返しているものを
     読み取って完全に一致させること。
   - 第2要素（`dict`）は`_merge_env`が返すサマリと同じキー（`added`/`updated`/
     `removed`/`unchangedCount`/`notFound`/`deduped`）。`added`=置換後にあり現在に
     無い名前、`updated`=両方にあり値が異なる名前、`removed`=現在にあり置換後に
     無い名前、`notFound`=常に`[]`、`unchangedCount`=両方にあり値が同一の名前の数
     （int）、`deduped`=`_normalize_pairs(replacement)`の第3要素をそのまま。名前
     リストの順序は置換後リストの初出順（`removed`のみ現在リストの初出順）を保つ。
   - `_normalize_pairs`を両引数に適用して実装する。

3. `update_swarm_stack`の`env_replace`分岐を`_replace_summary`呼び出しに置き換え、
   `removed_names`を含むsummaryをdiff分岐と同じ変数に代入する（既存の欠陥修正）。
   分岐後は2経路とも`merged_env`（マージ後Envペアリスト）と`summary`（サマリdict）の
   2変数だけを持つ状態にする。

4. `update_swarm_stack`のシグネチャに`dry_run: bool = False`を追加する
   （`allow_git_stack`の後、`pull_image`の前）。`Field(description=...)`には
   「Validate and preview only: perform the same reads and checks, compute the
   merged result, and return which variable names would change — without sending
   the update. Never returns values.」の趣旨を書く。

5. `update_swarm_stack`冒頭のread_onlyチェックを`if read_only and not dry_run:`に
   変更し、エラーメッセージを`"updateSwarmStack is not allowed in read-only mode
   (dry_run=True is allowed — it only reads)"`に変更する。**`read_only`は
   `register(mcp, client, read_only=...)`の引数をクロージャで参照している値であり、
   ツールのシグネチャに存在しない。本タスクで`read_only`をツールのパラメータとして
   追加してはならない**（追加すると呼び出し側がread-only設定を自分で無効化できて
   しまう）。シグネチャに足すのはタスク4の`dry_run`だけ。

6. `compose_file`の解決ロジックを拡張する。挿入位置は現在の`if compose_file is None:`
   ブロック周辺。比較用の正規化は**`def`文でローカル関数`_norm(text: str) -> str`を
   定義**し、本体は`return text.replace("\r\n", "\n").strip()`の1行とする
   （`_norm = lambda text: ...`の形は書かない。ruff既定ルールE731に触れる）。

   挙動は`compose_file`の有無と`dry_run`の2軸・3セルで独立に決まる。以下の表が
   このタスクの完全な仕様であり、いずれかのセルを他のセルから推論しないこと。

   | # | `compose_file` | `dry_run` | GET発行 | 失敗・欠落・空文字のとき | `compose_changed` |
   |---|---|---|---|---|---|
   | 6-a | 省略（`None`） | True/Falseどちらでも | 発行する（既存の保持目的GET。dry_runとは無関係） | `ToolError`（既存挙動を変えない） | `False` |
   | 6-b | 指定あり | `True` | 発行する（本フェーズで新規追加。比較専用） | `ToolError`にしない。`compose_changed = None`として続行 | `_norm(current) != _norm(provided)` |
   | 6-c | 指定あり | `False` | 発行しない | — | `None` |

   6-bの実装方法: 比較用GETの呼び出しを`try`/`except Exception`で包み、例外・
   `StackFileContent`欠落・空文字のいずれでも`compose_changed = None`にして処理を
   継続する（ログ出力は任意）。このexceptで`ToolError`を送出しない。

7. PUTボディ組み立ての直前に`dry_run`の早期returnを置く。**順序制約**: envdiff-2
   フェーズで追加済みのsentinelガード（マージ後Envに`[REDACTED]`が含まれていないか
   の検証。本フェーズのタスク2とは別物）は、この早期returnより前に位置している
   こと（既に前にあるなら移動不要、位置を確認するだけでよい）。返り値は下記タスク8の
   共通ビルダで生成し、`dry_run=True`/`updated=False`/`env_names`は`merged_env`から
   算出する。

8. 返り値を共通のローカルビルダ（`update_swarm_stack`内のネスト関数で可）に集約し、
   dry_runパスと実行パスの両方がこれを使う。キー集合と型:
   - `id`（`int`）: `stack_id`
   - `dry_run`（`bool`）: 実行パスでも`False`を明示的に含める
   - `updated`（`bool`）: PUTを実際に実行して成功したか。dry_runでは`False`
   - `env_names`（`list[str]`）: 更新後に存在するenv変数名の全件。順序は元となった
     ペアリストの並び順をそのまま保つ（実行パスはPUTレスポンスの`Env`優先・無ければ
     `merged_env`フォールバック、dry_runは`merged_env`。ソートや再整列はしない）
   - `env_added`/`env_updated`/`env_removed`/`env_not_found`（`list[str]`）: summaryの
     `added`/`updated`/`removed`/`notFound`
   - `env_unchanged_count`（`int`）: summaryの`unchangedCount`
   - `compose_file_changed`（`bool`）: `compose_changed`が`None`でないときのみキーを
     含める。`None`のときはキー自体を辞書に入れない（`false`で代用しない）。表6-cに
     より`dry_run=False`かつ`compose_file`指定ありの実行パスでは常にキーが省略される
   - `auto_update_cleared`（`bool`）: 従来どおり`allow_git_stack and stack.get("GitConfig")`
     が真のときのみキーを含める。値はdry_run/実行パスともに`True`固定

   キー名に`env`/`envvars`と完全一致するものを使わないこと。

9. `updateSwarmStack`の`description`に2文追加する: dry_runの説明（同じ読み取りと
   検証を行い、マージ結果の変数名だけを返し、更新は送らない）と、プレビューは
   助言的であり適用ハンドルではない旨（実行時にはサーバが再度読み直すため、その間に
   他者が変更していれば結果は異なりうる）。

10. `tests/test_swarm.py`にテストを追加する。既存の`_stack_routes()`/
    `_make_mock_client(..., captured=...)`の仕組み、`_STACK_10_COMPOSE`等の
    フィクスチャ定義の有無は実装前にテストファイルを読んで確認すること。PUT不発の
    検証はローカルヘルパ（`_no_put(captured)`）に集約する。

    以下13件はすべて必須（envdiff-2完了が前提なのでsentinelテストも条件付きでは
    ない）。うち`test_dry_run_contains_no_env_values`はゴールの不変条件2を守る
    唯一のテストなので、他を削っても絶対に削らないこと。

    - `test_dry_run_sends_no_put`
    - `test_dry_run_reports_env_diff`
    - `test_dry_run_env_replace_reports_removals`
    - `test_env_replace_reports_removals`（タスク3の欠陥修正の回帰テスト）
    - `test_dry_run_contains_no_env_values`【必須不変条件】
    - `test_dry_run_rejects_git_backed_stack`
    - `test_dry_run_rejects_kubernetes_stack`
    - `test_dry_run_rejects_sentinel_in_env_set`
    - `test_dry_run_allowed_in_read_only`
    - `test_write_blocked_in_read_only`
    - `test_dry_run_detects_compose_change`
    - `test_dry_run_compose_preserved_is_unchanged`
    - `test_update_result_includes_diff_fields`

## 完了条件（実装担当）

- [ ] `uv run pytest tests/test_swarm.py -q` が全PASS
- [ ] `uv run pytest -q` が全PASS（既存テストの回帰なし）
- [ ] `uv run pytest tests/test_swarm.py --collect-only -q` に上記13件の新規テスト名が
      すべて現れる
- [ ] タスク1の抽出が挙動を変えていないこと: `_merge_env`を直接・間接に検証する
      既存テストが1件も変更されずにPASSする（`git diff tests/test_swarm.py`に
      既存テスト本体の変更が含まれない＝追加行のみ）
- [ ] `uvx ruff check src/portainer_mcp/swarm.py tests/test_swarm.py` がPASS
- [ ] `grep -n 'dry_run' src/portainer_mcp/swarm.py` の結果が、パラメータ定義・
      `read_only and not dry_run`・compose比較の条件（表6-bの分岐）・早期return・
      返り値ビルダのみで、PUT実行後のコードパスに`dry_run`分岐が存在しない
- [ ] `grep -n 'removed_names' src/portainer_mcp/swarm.py` が`env_replace`分岐でも
      代入されていることを示す
- [ ] `git diff --stat upstream/main..HEAD` で本フェーズにより新規に変更された
      ファイルが`src/portainer_mcp/swarm.py`と`tests/test_swarm.py`のみ

## 完了条件（メインセッション）

- [ ] reviewerサブエージェントがPASS（Blocker/Should 0件）。「自己申告の不安」には
      最低限、(a) `env_replace`のremoved算出が既存のdiffパスとサマリのキー・意味論で
      一致しているか、(b) dry_runパスに書き込み（PUT/POST/DELETE）が一切残っていないか、
      (c) タスク1の`_normalize_pairs`抽出で`_merge_env`の既存挙動（特に`deduped`と
      値の上書き規則）が変わっていないか、(d) `read_only`がツールのシグネチャに
      漏れ出していないか、の4点を含めること

## リスク・注意点

- **TOCTOU**: dry_run時点の状態と実行時点の状態はズレうる。緩和はdescriptionの
  文言のみ。プレビュー結果を保存して「これを適用」するハンドル、タイムスタンプ
  記録、ETagベースの楽観ロックはいずれも本フェーズのスコープ外で実装しない
  （Portainer側に対応する条件付き更新機構が無いため実効性がない）。
- **`updated: false`の誤読**: LLMが失敗と解釈する恐れがある。`dry_run: true`を
  同一オブジェクトに含めることとdescriptionの文面で緩和する。
- **read_onlyの意味論変更**: 「read-onlyモードでは`updateSwarmStack`は必ずエラー」
  →「dry_runのみ通る」に変わる。`docs/configuration.md`はupstreamファイルなので
  触らない。周知はツールのdescriptionと、envdiff-3で更新する`CLAUDE.md`の
  Architecture節に載せる。
- **GET回数の増加**: dry_run→実行の2段構えになるとGETが倍増しうる。既定`False`
  なので明示的に頼まれない限り増えない。
- `updateSwarmStack`の名前は変わらないため`tests/test_tool_names.py`
  （40文字制限）への影響はない。

## 実施結果

（実施後にここへ追記する）
