# フェーズ1: HTTP認証・TLSポスチャの方針決定

目安: 2〜3時間。コード変更なし。実施主体: メインセッション（reviewer不要、ドキュメントのみ）。

## ゴール

フェーズ2のマージで `server.py` のコンフリクトをどう解決するかが一意に決まっており、
判断根拠が本ファイルまたは追記ファイルに記録され、コミット済みである。

## 背景（upstreamがHTTPトランスポートの前提を根本から変えた3点）

1. `PORTAINER_API_KEY` が **HTTPトランスポートで**設定されていると `SystemExit` で起動拒否
   （`server.py:build_server()`）。HTTPは各クライアントが `X-Portainer-API-Key` を送る
   per-userパススルー専用になった。**stdioでは従来どおり必須**。
2. 非loopbackバインドでTLSポスチャ未宣言だと起動拒否（`tls.resolve_posture`）。
   現行の0.0.0.0+平文構成はそのままでは通らない。
3. `PORTAINER_MCP_AUTH_TOKEN` 未設定は `auth.require_token` がSystemExit。フォークの
   e05efb6（bearer任意化）はupstreamの `PORTAINER_MCP_TRUST_PROXY_AUTH` に「思想としては」
   置き換わったが、trust-proxyでもper-userキーは必須なので1:1の代替にはならない。

## タスク

1. **3経路それぞれの `X-Portainer-API-Key` 注入可否を確認**（担当・方法固定）:
   - Claude Code経路: メインセッションが実機確認
     （`claude mcp add <名前> --transport http <URL> --header 'X-Portainer-API-Key: …'`）
   - claude.aiカスタムコネクタ経路: researcherサブエージェントに調査依頼
     （問い:「claude.aiのremote MCP custom connectorで任意HTTPヘッダを設定できるか。
     OAuth以外の認証手段のサポート範囲」）
   - mcp-portal経路: ユーザーに口頭確認
   - **判定ルール**: 3経路すべてYesなら案A。1経路でもNoなら案A単独は選ばず案BまたはCへ。
2. **upstreamのpassthrough実装をコードで確定する**（「共有clientなので自動で効くはず」と仮定しない）:
   - (a) callerのキーがhttpxリクエストヘッダに載る箇所を「ファイル名:関数名」で特定
   - (b) `proxy.py` の `docker_proxy`/`kubernetes_proxy` と `swarm.py` の8ツールが、
     (a)と同じhttpxクライアント経路を通るか否かを判定
   - (b)が「通らない」場合、フェーズ2で採る配線方式を次から1つ選び理由つきで記録:
     - 方式A: 共有httpxクライアントへのrequest event hook追加
     - 方式B: FastMCP middleware層でのヘッダ注入
     - 方式C: ハンドライトツール内で毎回クライアント構築
   - (b)が「通る」場合、フェーズ2のパッチ再適用からcallerキー配線タスクを外す
3. `src/portainer_mcp/guidance.py` を読み、caller keyの導出元をコードで確定させる
   （共有キー運用で全callerが1バケットに縮退するかどうか）。
4. 代替案A/B/Cから1案をユーザーと合意して選ぶ（下記「代替案」参照）。
5. **TLSポスチャを決める（前提の検証を含む）**:
   - traefikがバックエンドへ `X-Forwarded-Proto: https` を付与しているかを検証
     （ユーザーのtraefik設定確認、または現行コンテナのログ/リクエストヘッダ実測）
   - 付与ありの場合の推奨: `PORTAINER_MCP_TRUST_PROXY_TLS=1` +
     `PORTAINER_MCP_FORWARDED_ALLOW_IPS=<overlayネットワークのCIDR>`
   - 未確認/なしの場合のフォールバック: `PORTAINER_MCP_DANGEROUSLY_ALLOW_PLAINTEXT_HTTP=1`
     （案Aとは併用不可 — `auth_posture.resolve` が起動拒否する）
   - **overlay CIDRの具体値はこのタスクでユーザーに口頭確認し、ファイルには書かない**。
     確認した値はフェーズ4タスク4で本番環境変数に設定する際に改めて受け取る。
6. `PORTAINER_MCP_ALLOWED_HOSTS` の現行値をユーザーに確認し、本番で必要なホスト名
   （traefikが転送する `Host` ヘッダの値）とローカル検証用のloopback値の両方を決める。
   **具体値はファイルに書かない**。
7. guidance gateの扱いを決める（`PORTAINER_MCP_DISABLE_GUIDANCE_GATE=1` にするか、
   バウンス挙動を受け入れるか）。タスク3で「共有キーだと1バケット」が裏づけられ、
   かつ案B/Cを選ぶ場合は無効化を推奨。
8. 決定内容を本ファイルの「決定事項」節に追記し、**コミットする**
   （フェーズ2のworktreeから参照できるようにするため）。

## 完了条件

- [ ] 選択した認証案（A/B/C）・TLSポスチャ・`ALLOWED_HOSTS`方針・guidance gate方針と、
      それぞれの却下理由が記載されている
- [ ] 3経路それぞれの `X-Portainer-API-Key` 注入可否（Yes/No/未確定）と判断根拠が記載されている
- [ ] passthroughのcallerキー適用層（ファイル名:関数名）と、
      ハンドライトツールへの明示配線要否がコード根拠つきで記載されている
- [ ] guidance.pyのcaller key導出元が1〜2行、コード根拠つきで記載されている
- [ ] traefikの `X-Forwarded-Proto` 付与の検証結果（付与あり／なし／未確認）が記載されている
- [ ] 本番に設定する環境変数の最終リスト（**値そのものではなく変数名と意味**）が列挙されている
- [ ] 案B/Cを選ぶ場合、`server.py` に追加するフォークパッチの疑似コード（分岐条件とenv変数名）が記載されている
- [ ] 本ファイルが `git log --oneline -1` で確認できる形でコミット済み

## 代替案（HTTP認証モデル）

| 案 | 内容 | メリット | デメリット | 推奨度 |
|---|---|---|---|---|
| A: upstream準拠のper-user passthrough | `PORTAINER_API_KEY`を本番HTTP envから削除。各クライアントが`X-Portainer-API-Key`を送る | フォーク差分が最小、監査ログにuser属性、guidance gateもcallerごとに正しく効く | 全経路がヘッダ注入できないと成立しない、overlay CIDR固定必要、平文フラグと併用不可 | ⭐⭐⭐ |
| B: 共有upstreamキーを維持するフォークパッチ | `PORTAINER_MCP_SHARED_UPSTREAM_KEY=1`（フォーク独自）で共有キーをベイク | 現行接続方法を変えず切替リスク最小 | `server.py`に恒久パッチ、毎回同期でコンフリクト確定発生、guidance gateが全caller1バケット、upstreamのセキュリティ強化を捨てる | ⭐⭐ |
| C: BからAへ段階移行（→フェーズ6） | フェーズ4はBで切替、稼働確認後にAへ移行 | 本番停止リスク最小化しつつ最終的にフォーク差分最小化 | 移行が2段階、FORK-DELTA.mdで暫定パッチを管理し続ける必要 | ⭐⭐⭐（Aが即座に確認できない場合の第一候補） |

## 決定事項

（このタスク実施後にここへ追記する）
