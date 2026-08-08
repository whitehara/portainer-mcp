# フェーズ0: タグ命名衝突の解消とupstreamタグの取り込み

目安: 1〜2時間。実施主体: メインセッション（worktree委譲なし）。コミット前にメインセッションからreviewerを呼ぶ。

## ゴール

`git fetch upstream --tags` がclobberエラーなく完了し、フォーク独自リリースが
upstreamと衝突しない命名空間（`hl-*`）に移行している。コード変更はリリース
ワークフローのトリガ／タグ生成規則のみ。

## 背景

origin の `2.42.4` `2.42.5` `2.42.6` `2.42.7` の4本だけがupstreamの同名タグと
衝突（別コミットを指す）。origin にある `2.43.0`〜`2.43.3` と `2.44.0` は
upstreamと同一コミットを指しており無害・触らない。

## タスク

1. 削除対象タグ4本に GitHub Release が紐付いているかを `gh release list --repo whitehara/portainer-mcp` で確認。
   紐付いていた場合:
   - `gh release view <旧タグ> --json body,name` で本文退避
   - 新タグ（下記タスク4で作成）に対して `gh release create <新タグ> --title <元のタイトル> --notes <退避した本文>`
   - `gh release delete <旧タグ> --yes`（`--cleanup-tag` は付けない、タグ削除はタスク4で明示的に行う）
   - 実行前にユーザーへ承認を得る
2. `.github/workflows/release-docker.yml` をタグ操作より先に編集（upstreamタグを誤ってoriginにpushした際の誤ビルド防止）:
   - `on.push.tags` を `'[0-9]+.[0-9]+.[0-9]+'` から `'hl-[0-9]+.[0-9]+.[0-9]+-[0-9]+'` に変更
   - 「Verify tag matches pyproject version」ステップを、`hl-` 接頭辞と `-<fork-rev>` 接尾辞を除いた部分を `pyproject.toml` の `version` と比較する形に書き換え
   - `docker/metadata-action` の `tags:` を以下に置き換え:
     - `type=match,pattern=hl-(\d+\.\d+\.\d+-\d+),group=1`
     - `type=match,pattern=hl-(\d+\.\d+\.\d+)-\d+,group=1`
     - `type=raw,value=latest`
   - ワークフロー冒頭のコメント（Docker Hub時代の残骸）をGHCR + `hl-*` タグ運用に合わせて書き直す
3. `docs/release.md` に、フォーク独自のタグ規約 `hl-<upstream-version>-<fork-rev>` と、
   「`pyproject.toml` の `version` は upstream の値のまま触らない」方針を追記。
4. フォーク独自コミットを指す4本のタグだけを新命名で打ち直す（`2.43.x` / `2.44.0` は対象外・削除しない）:
   - `git tag hl-2.42.4-1 4f282be`
   - `git tag hl-2.42.5-1 e05efb6`
   - `git tag hl-2.42.6-1 ba1067e`
   - `git tag hl-2.42.7-1 1709c12`
   - `git push origin hl-2.42.4-1 hl-2.42.5-1 hl-2.42.6-1 hl-2.42.7-1`
   - origin から旧タグ削除: `git push origin :refs/tags/2.42.4 :refs/tags/2.42.5 :refs/tags/2.42.6 :refs/tags/2.42.7`
   - ローカルの旧タグ削除: `git tag -d 2.42.4 2.42.5 2.42.6 2.42.7`
5. `git fetch upstream --tags` を実行し、upstreamの `2.42.4` `2.42.5` `2.42.6` を取り込む。
6. `git config rerere.enabled true` を設定（今後の反復マージで同じコンフリクト解決を再利用するため）。

## 完了条件

- [x] `git fetch upstream --tags` が警告・エラーなしで終了する（`echo $?` が0）
- [x] `git rev-list -n1 2.42.5` が `4bfeecb`（upstream側のコミット）を返す
- [x] `git rev-list -n1 hl-2.42.5-1` が `e05efb6`（フォーク側のコミット）を返す
- [x] `git ls-remote --tags origin | grep -E 'refs/tags/2\.42\.[4-7]$'` が空を返す
- [x] `git ls-remote --tags origin | grep -cE 'refs/tags/2\.43\.[0-3]$'` — **該当なし**。
      実施結果に記載のとおり、`2.43.x`/`2.44.0`はupstream remoteにのみ存在し、
      originには元々一度もpushされていなかった（計画時の前提誤り）。よって0を返すのが正しい状態。
- [x] `gh release list --repo whitehara/portainer-mcp` の出力に、存在しないgitタグを指すReleaseが無い
      （Release自体が0件のため該当なし）
- [x] `git config rerere.enabled` が `true` を返す

## 実施結果（2026-08-09）

- `gh release list --repo whitehara/portainer-mcp` は空 — GitHub Releaseは1件も
  存在しなかったため、タグの付け替え作業（タスク1の紐付き処理）は不要だった。
- `.github/workflows/release-docker.yml` を `hl-*` タグ運用に書き換え済み。
- `docs/release.md` にフォーク独自のタグ規約とversion不変条件を追記済み
  （併せて、upstream由来のPyPIリリース記述が本フォークには適用されないことを
  冒頭に明記した — release.yml/release-test.ymlは元々このフォークには存在しない）。
- 旧タグ4本（`2.42.4`〜`2.42.7`）を `hl-2.42.4-1`〜`hl-2.42.7-1` に打ち直し、origin
  へpush・旧タグをorigin/localから削除済み。
- `git fetch upstream --tags` 正常終了、`git config rerere.enabled true` 設定済み。
- **計画時の前提の誤りを1点訂正**: 計画では「originの`2.43.0`〜`2.43.3`/`2.44.0`は
  upstreamと同一コミットで無害だから触らない」としていたが、実際には
  これらのタグは**upstream remoteにのみ存在し、origin(whitehara/portainer-mcp)
  には一度もpushされていなかった**。実害はなく、むしろoriginには裸の`X.Y.Z`形式の
  タグが一切無い状態になったため、今後の衝突リスクはより低い。フェーズ0の完了条件
  「2.43.xが4本残っている」はorigin上には該当なし（never existed）として扱う。

## リスク・注意点

- GHCRに既にpublish済みのイメージタグ（`2.42.4`〜`2.42.7`, `latest`）は削除しない。
  gitタグ削除はGHCRのイメージタグに影響せず、`docker pull ghcr.io/…:2.42.7` は引き続き機能する。ロールバック先として温存する。
- 旧タグを消す前に、本番が現在どのイメージタグ／ダイジェストで動いているかを記録しておく（swarm-inspectorスキル）。フェーズ4のロールバック先になる。
