# envdiffフェーズ4: 実機検証と本番`PORTAINER_EXPOSE_ENV_VALUES`撤去

目安: 1〜2時間。実施主体: メインセッション。**ユーザー承認必須**（本番影響）。

## ゴール

検証用スタックでEEのEnvセマンティクスを実証したうえで、本番`portainer-mcp`から
`PORTAINER_EXPOSE_ENV_VALUES=1`を外す。

## 前提

**フェーズ2を飛ばして本フェーズに進まないこと。** ガード無しでredactionを
既定に戻すと、LLMが`docker_proxy`でserviceのread-modify-writeをした瞬間に
本番の秘密情報が`[REDACTED]`で上書きされる。

## タスク

1. `make dev`でローカル起動し、起動ログに`select`不変条件のログ（`` `select`
   arg present on all N tools ``）とredaction有効（`PORTAINER_EXPOSE_ENV_VALUES`
   未設定）が出ることを確認する。

2. **検証用スタック**（本番スタックは使わない）を`createSwarmStack`で1つ作る。
   composeの内容は最小構成でよい（サービス1個、軽量イメージをsleepさせる
   程度）。envを2〜3個持たせる。以下を実機で確認する:
   - `env_*`全省略の`updateSwarmStack`でcomposeだけ更新→`StackInspect`で
     env名が全て残っている
   - `env_set`で1つ追加→既存が消えていない
   - `env_unset`で1つ削除→指定分のみ消えている
   - 返り値に値が一切含まれていない
   - 同一の`env_set`を`dry_run=True`で実行したときの`env_names`/`env_added`/
     `env_removed`が、直後に`dry_run=False`で実行した結果と一致する
     （envdiff-2bのdry_runプレビューの実機検証）
   - **これがEE実装未検証という留保を解消するゲート**。挙動がCEと違った
     場合は、**メインセッションが本フェーズの作業を中断し、差異の内容を
     ユーザーに報告する。続行するか設計を変えるかの判断はユーザーが行う**
     （独断で回避策を入れて進めない）

3. 検証用スタックを削除する。

4. イメージをビルド・push（`swarm-deploy`スキルの手順）し、本番
   `portainer-mcp`サービスから`PORTAINER_EXPOSE_ENV_VALUES`を**環境変数の
   行ごと削除**して更新する（`=0`に設定するのではなく、変数自体を存在
   させない。`redaction.is_expose_enabled()`は未設定/`0`/`false`/`False`の
   いずれでもFalseを返すため、行削除と`=0`明示は等価だが、grepで状態を
   追えるよう行削除を採用する）。

5. 本番で`StackInspect`を1回叩き、env値が`[REDACTED]`で返ることと
   redactionサマリ行が付くことを確認する。

6. `.claude/FORK-DELTA.md`の「運用ノート」から`PORTAINER_EXPOSE_ENV_VALUES=1`の
   項を削除し、「redaction既定に戻した（日付・理由・代替手段は
   `updateSwarmStack`のenv差分マージ）」に書き換える。本ファイルに検証結果を
   記録する。

## 完了条件

- [x] 検証用スタックでの上記4項目の実機確認結果が本ファイルに記録されている
- [x] 本番サービスの環境変数一覧に`PORTAINER_EXPOSE_ENV_VALUES`が存在しない
- [x] 本番の`StackInspect`レスポンスに`[REDACTED]`とredactionサマリ行が出る
      — **注**: `portainer-stack`はPortainerのStack API管理下ではなく手動
      `docker stack deploy`運用のため`StackList`/`StackInspect`には現れない
      （`.claude/phases/phase-4-production-deploy.md`に記録済みの既知の運用
      形態）。代わりに`docker_proxy`でサービス仕様（`/services/{id}`の
      `Spec.TaskTemplate.ContainerSpec.Env`）を直接確認し、同じredaction
      サマリ行の付与を確認した（下記実施結果参照）
- [x] 本番サービスが`Running`かつ既存のSwarm操作（`listSwarmServices`等）が
      従来どおり動く
- [x] 切り戻し手順（1つ前のイメージタグ+`PORTAINER_EXPOSE_ENV_VALUES=1`の
      再付与）が記録されている

## リスク・注意点

- 検証用スタックは必ず新規作成する。本番スタックでは検証しない。
- 本番のPortainer URL・環境ID・スタック名などホームラボ固有値は、
  リポジトリ内のどのファイルにも書かない（変数名と意味のみ）。

## 実施結果

### 手順1〜3（実機検証、2026-08-10）

`make dev`をローカル起動し、起動ログで`select`不変条件（`select` arg present on
all 219 tools）とredaction有効（`env value redaction: enabled`、
`PORTAINER_EXPOSE_ENV_VALUES`未設定）を確認。

ローカルdevサーバーへのMCPクライアント接続は、per-user passthrough認証
（`Authorization`ゲートトークン＋`X-Portainer-API-Key`per-userキーの2層）が
必要なため当初つまずいた（ゲートトークン単体では`no_user_key`で401、
ユーザーが`.env`に追加した`X_PORTAINER_API_KEY`も当初はシェルのクォート起因で
値が壊れており`invalid_user_key`で401）。ユーザーが原因（`.env`の値を`''`で
囲んでいたため）を特定・修正し解消。検証用に`scripts/envdiff-phase4-verify.sh`
（curl+jqでMCP streamable-HTTPを直接叩くスクリプト）を作成した。

検証用スタック（environment_id=5 `docker-sock`、最小構成のalpineサービス、
env 2個）を`createSwarmStack`で作成し、以下を実機（Portainer CE 2.39.5）で確認:

- `env_*`全省略で`updateSwarmStack`→`env_names=["A","B"]`（両方保持）、
  `env_unchanged_count=2`、返り値に値の漏洩なし
- `env_set={"C":"verify-charlie"}`を`dry_run=True`で実行→
  `dry_run:true`, `updated:false`, `env_added:["C"]`, `env_names:["A","B","C"]`
- 同じ`env_set`を`dry_run=False`で実行→**dry_run結果と完全一致**
  （`env_added:["C"]`, `env_names:["A","B","C"]`）— envdiff-2bのdry_runプレビューが
  実行結果を正確に予測できることを実証（EE実装未検証という留保を解消するゲート、達成）
- `env_unset=["A"]`を実行→`env_removed:["A"]`, `env_names:["B","C"]`
- `StackInspect`で最終状態を確認→`Env`の値はすべて`[REDACTED]`（本物の値は出ない）

挙動はCEと差異なし（想定どおりの動作、独断での回避策は不要だった）。

検証用スタックは`StackDelete`（`id`＋`endpointId`の両方が必須。スクリプトの
初版は`endpointId`を渡しておらず失敗したため修正）で削除し、`StackList`で
`Id==31`が空配列になることを確認して完全に消えたことを検証した。検証終了後、
`scripts/envdiff-phase4-verify.sh`は一時ファイルのため削除し、ローカル
`make dev`サーバーも停止した（リポジトリには残っていない）。

### 手順4〜6（イメージビルド・本番反映、2026-08-10）

- タグ`hl-2.44.0-2`を作成・push。GitHub Actions `Release (Docker)`が成功
  （約6分）。`ghcr.io/whitehara/portainer-mcp:2.44.0-2`
  （digest `sha256:f70f7b68b27492b71131f6f77bedca2fd5d7922bba04f1650d36ed12a4ab6269`）
  としてpush済み（`:2.44.0`・`:latest`タグも同digestで更新）
- 本番`portainer-stack`の更新（`/tmp/portainer-agent-stack.yml`の編集・再デプロイ）は
  合意どおりユーザーが手動で実施。1回目のデプロイではイメージのみ更新され
  `PORTAINER_EXPOSE_ENV_VALUES`の行削除が未反映だったため、メインセッションが
  `docker_proxy`でサービスspecを直接確認して検出・報告。ユーザーが修正して
  再起動し、再確認で解消を確認
- 確認方法: `listSwarmServices(environment_id=1, ...)`で`portainer-stack_portainer-mcp`
  サービスID を特定し、`docker_proxy(path="/services/{id}", select="{name:...,
  env:Spec.TaskTemplate.ContainerSpec.Env,image:...}")`でコンテナ仕様の`Env`を
  直接確認（`portainer-stack`はPortainerのStack API管理下にないため
  `StackInspect`は使えない。上記完了条件の注記参照）
  - 修正前: `PORTAINER_EXPOSE_ENV_VALUES=1`を含む10個の環境変数が生値のまま
    返っていた（redaction無効の状態が実機で確認された）
  - 修正後: `PORTAINER_EXPOSE_ENV_VALUES`自体が変数一覧から消え（9個に減少）、
    残り全変数の値が`[REDACTED]`、redactionサマリ行
    `[9 env value(s) redacted; set PORTAINER_EXPOSE_ENV_VALUES=1 on the MCP
    server to disclose]`が付与されることを確認
  - `listSwarmServices`で`portainer-stack_portainer-mcp`
    （`ghcr.io/whitehara/portainer-mcp:2.44.0-2`、digest一致）・
    `portainer-stack_portainer-mcp-http`（mcp-auth-proxy）とも
    `replicas.desired == replicas.running == 1`を確認。他の全スタックの
    サービスも同様に稼働中で異常なし

**切り戻し手順**: 本番`/tmp/portainer-agent-stack.yml`のイメージタグを
1つ前の`hl-2.44.0-1`（＝`ghcr.io/whitehara/portainer-mcp:2.44.0-1`相当。
実際のタグ表記は`2.44.0-1`）に戻し、`PORTAINER_EXPOSE_ENV_VALUES=1`の行を
再度追加して再デプロイする。envdiff-1〜2bの`updateSwarmStack`拡張自体は
後方互換（`env_set`/`env_unset`/`env_replace`/`dry_run`はすべて新規追加の
オプション引数）なのでコード面の切り戻しは不要。

### 追加検証: 本番portainer-mcp経由での実機テスト（2026-08-10）

上記手順4〜6の検証は「ローカルの新コード→実際のPortainer API」という経路で
行っており、「本番デプロイされたportainer-mcpインスタンス自身（`mcp-auth-proxy`
経由）を通した`updateSwarmStack`呼び出し」は未検証だった。ユーザー指摘を受け、
`mcp-portal`（claude.ai既存接続）経由で追加検証を実施。

- `portal_toggle_single_server`でuntoggle→toggleしたがツールスキーマが
  古いまま（`env`必須の旧シグネチャ）だったため、`mcp-portal`自体の再認証
  （`/mcp`コマンド、ユーザー実施）が必要だった。再認証後、
  `updateSwarmStack`のスキーマに`dry_run`/`env_set`/`env_unset`/
  `env_replace`/`allow_git_stack`が反映されていることを確認
- 実在の本番スタック`tmux_mcp_stack`（id=24、environment_id=1、影響の
  少ないスタックとしてユーザーが選定、GitConfig=null）に対して実施:
  - `StackInspect`で既存8変数を確認（全て`[REDACTED]`）
  - `env_set={"ENVDIFF_PROD_TEST": "hello-envdiff-verification"}`を
    `dry_run=True`で実行→`env_added:["ENVDIFF_PROD_TEST"]`,
    `env_unchanged_count:8`。`dry_run=False`で実行→**dry_run結果と完全一致**
  - `StackInspect`で9変数（既存8＋新規1）全てが`[REDACTED]`で返ることを確認
  - **ユーザーがPortainer GUIで`ENVDIFF_PROD_TEST`の値が
    `hello-envdiff-verification`に正しく設定されていることを確認**
    （MCPからは値が見えないが実際には正しい値が入っている＝redactionが
    正しく機能していることの直接証拠）
  - `env_unset=["ENVDIFF_PROD_TEST"]`を`dry_run=True`→
    `env_removed:["ENVDIFF_PROD_TEST"]`, `env_unchanged_count:8`。
    `dry_run=False`で実行→dry_run結果と完全一致
  - `StackInspect`で元の8変数のみに戻ったことを確認
  - `listSwarmServices`で`tmux-mcp`・`mcp-auth-proxy`ともに
    `replicas.desired == replicas.running == 1`、異常なし

本番のportainer-mcp自身を経由した経路でも、env保持・追加・削除・dry_run一致・
値の非開示のすべてが実証された。
