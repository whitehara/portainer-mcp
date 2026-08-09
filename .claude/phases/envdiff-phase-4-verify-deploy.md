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

- [ ] 検証用スタックでの上記4項目の実機確認結果が本ファイルに記録されている
- [ ] 本番サービスの環境変数一覧に`PORTAINER_EXPOSE_ENV_VALUES`が存在しない
- [ ] 本番の`StackInspect`レスポンスに`[REDACTED]`とredactionサマリ行が出る
- [ ] 本番サービスが`Running`かつ既存のSwarm操作（`listSwarmServices`等）が
      従来どおり動く
- [ ] 切り戻し手順（1つ前のイメージタグ+`PORTAINER_EXPOSE_ENV_VALUES=1`の
      再付与）が記録されている

## リスク・注意点

- 検証用スタックは必ず新規作成する。本番スタックでは検証しない。
- 本番のPortainer URL・環境ID・スタック名などホームラボ固有値は、
  リポジトリ内のどのファイルにも書かない（変数名と意味のみ）。

## 実施結果

（実施後にここへ追記する）
