# envdiffフェーズ2: `[REDACTED]`書き戻しガード＋hygieneガイド追記

目安: 1〜2時間。実施主体: メインセッション（フェーズ1がworktreeなら同じworktreeで
継続してもよい）。コミット前にreviewerを通す。

## ゴール

redaction既定に戻した状態で、LLMが読み取った`[REDACTED]`を実値として書き戻そうと
したら、書き込み到達前にツールエラーで止まる。加えて、この横断的な注意事項を
運用ガイド（`get_guidance`で配信されるhygieneスキル）にも明記する。

## タスク

### コードガード

1. `src/portainer_mcp/proxy.py`の`_call()`内、`client.request(...)`の**直前**に
   ガードを追加する:
   - 条件: `method.upper() not in {"GET", "HEAD"}` かつ `body`に
     `redaction.SENTINEL`が含まれ、かつ `not redaction.is_expose_enabled()`
   - 動作: `ToolError`を送出。メッセージに「リクエストボディにredaction
     sentinel `[REDACTED]`が含まれており、実際の秘密情報をプレースホルダで
     上書きしようとしている」「swarm serviceの場合はservice specを直接書かず
     `updateSwarmStack`で所有スタックを編集せよ」の2点を含める
   - `from portainer_mcp import redaction`のimportを追加
2. `src/portainer_mcp/swarm.py`の`update_swarm_stack`内でも、マージ後のEnv値に
   `redaction.SENTINEL`が含まれていたら同様に`ToolError`（`env_set` /
   `env_replace`由来のケース）
3. `tests/test_proxy.py`に`test_write_with_redaction_sentinel_rejected`と
   `test_write_with_sentinel_allowed_when_expose_enabled`
   （`monkeypatch.setenv("PORTAINER_EXPOSE_ENV_VALUES", "1")`）を追加
4. `tests/test_swarm.py`に`test_update_rejects_sentinel_in_env_set`を追加

### hygieneガイドへの追記

5. `skills/portainer-mcp-hygiene/SKILL.md`（upstream由来、`get_guidance`ツール
   経由でguidance gateが全callerに配信する運用ガイド本体）の「Env values are
   redacted by default」節に、以下の趣旨を追記する:
   - `[REDACTED]`はリテラルのプレースホルダであり、これをそのまま書き戻す
     （service specやstack envの更新リクエストに含めて送信する）と、
     実際の秘密情報がこの文字列で上書きされる
   - env値を変更したい場合は、まず現在の値を伏字化された状態のまま
     `updateSwarmStack`（stackの場合）等の差分更新ツールを使うこと。
     生のspecをread-modify-writeする形で値を書き戻そうとしない
   - このリスクはコード側（本フェーズのガード）でも検知されるが、事前に
     知っておくことで無駄なエラー往復を避けられる

## 完了条件

- [ ] `uv run pytest tests/test_proxy.py tests/test_swarm.py -q` が全PASS
- [ ] `uv run pytest -q` が全PASS
- [ ] `git diff upstream/main..HEAD -- src/portainer_mcp/proxy.py | grep -c '^+'`
      が15行以下（fork deltaを小さく保つ確認）
- [ ] `skills/portainer-mcp-hygiene/SKILL.md`の「Env values are redacted by
      default」節に上記の追記がある

## リスク・注意点

- `proxy.py`と`skills/portainer-mcp-hygiene/SKILL.md`はいずれもupstream由来
  ファイルなので、このフェーズでfork deltaが2件増える。ただしどちらも
  upstream本体にとっても有益な内容（`[REDACTED]`書き戻し防止は一般的な
  問題）なので、**実装後にupstream（`portainer/portainer-mcp`）へのPR提出を
  ユーザーに提案する**。マージされれば`.claude/FORK-DELTA.md`からこの2件の
  エントリを削除できる
- `redaction.py`には触らない（`SENTINEL`と`is_expose_enabled`をimportする
  だけ）
- 誤検知: ユーザーが本当に文字列`[REDACTED]`を値として設定したい場合は
  通らない。回避方法（`PORTAINER_EXPOSE_ENV_VALUES=1`）を**エラーメッセージ
  には書かない**（回避方法をLLMに教えると自分でオフにしようとする恐れが
  ある）。ユーザー向けの逃げ道はdocs側にだけ書く
