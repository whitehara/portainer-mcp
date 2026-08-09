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

- [x] 選択した認証案（A/B/C）・TLSポスチャ・`ALLOWED_HOSTS`方針・guidance gate方針と、
      それぞれの却下理由が記載されている
- [x] 3経路それぞれの `X-Portainer-API-Key` 注入可否（Yes/No/未確定）と判断根拠が記載されている
- [x] passthroughのcallerキー適用層（ファイル名:関数名）と、
      ハンドライトツールへの明示配線要否がコード根拠つきで記載されている
- [x] guidance.pyのcaller key導出元が1〜2行、コード根拠つきで記載されている
- [x] traefikの `X-Forwarded-Proto` 付与の検証結果（付与あり／なし／未確認）が記載されている
- [x] 本番に設定する環境変数の最終リスト（**値そのものではなく変数名と意味**）が列挙されている
- [x] 案B/Cを選ぶ場合、`server.py` に追加するフォークパッチの疑似コード（分岐条件とenv変数名）が記載されている
      — 案Aを選択したため該当なし
- [x] 本ファイルが `git log --oneline -1` で確認できる形でコミット済み（このコミット自体で満たす）

## 代替案（HTTP認証モデル）

| 案 | 内容 | メリット | デメリット | 推奨度 |
|---|---|---|---|---|
| A: upstream準拠のper-user passthrough | `PORTAINER_API_KEY`を本番HTTP envから削除。各クライアントが`X-Portainer-API-Key`を送る | フォーク差分が最小、監査ログにuser属性、guidance gateもcallerごとに正しく効く | 全経路がヘッダ注入できないと成立しない、overlay CIDR固定必要、平文フラグと併用不可 | ⭐⭐⭐ |
| B: 共有upstreamキーを維持するフォークパッチ | `PORTAINER_MCP_SHARED_UPSTREAM_KEY=1`（フォーク独自）で共有キーをベイク | 現行接続方法を変えず切替リスク最小 | `server.py`に恒久パッチ、毎回同期でコンフリクト確定発生、guidance gateが全caller1バケット、upstreamのセキュリティ強化を捨てる | ⭐⭐ |
| C: BからAへ段階移行（→フェーズ6） | フェーズ4はBで切替、稼働確認後にAへ移行 | 本番停止リスク最小化しつつ最終的にフォーク差分最小化 | 移行が2段階、FORK-DELTA.mdで暫定パッチを管理し続ける必要 | ⭐⭐⭐（Aが即座に確認できない場合の第一候補） |

## 決定事項（2026-08-09）

### 選択案: A（upstream準拠のper-user passthrough）

`server.py` への認証関連フォークパッチは**ゼロ**。フェーズ2で再適用する必須パッチ4件
（swarm importとregister、`_TOOL_NAME_REMAP`、`_annotate_read_only`の1行）のみで、
5件目・6件目の条件付きパッチは不要。

### 却下した案

- **案B（共有キーの恒久フォークパッチ）**: `server.py`に恒久パッチが増え、毎回の同期で
  コンフリクトが確定的に発生するため却下。ただし後述のとおり運用上は「共有キー」を
  実質採用しており、パッチをこのリポジトリの外（mcp-auth-proxy側）に追い出した形。
- **案C（段階移行）**: 案Aが最初から成立する見込みが立ったため不要。フェーズ6は実施しない。

### 3経路の`X-Portainer-API-Key`注入可否

| 経路 | 可否 | 根拠 |
|---|---|---|
| Claude Code CLI | ○ | `claude mcp add --transport http --header` で対応（`claude mcp add --help`で確認済み） |
| claude.aiカスタムコネクタ | ×（既定） | 公式ドキュメント（Request headers, beta）で、送信可能なヘッダ名がAnthropicレビュー済みallowlist（`authorization`/`x-api-key`/`x-auth-token`等）に限定されると明記。独自名`X-Portainer-API-Key`は既定では通らない |
| mcp-portal（実体は`portainer-mcp.vx-xv.com`向けmcp-auth-proxy自身） | ○ | mcp-auth-proxy（`sigbit/mcp-auth-proxy`）はbackendがHTTP URL指定のtransparent modeで動作しており（起動引数`http://portainer-mcp:80`で確認）、ソースコード上クライアントヘッダを`Authorization`と`HEADER_MAPPING`ターゲット名以外は削除せず素通しする設計 |

判定ルール（3経路すべてYesなら案A、1経路でもNoなら案B/C）に従うとclaude.aiがNoのため
本来は案B/Cだが、以下の理由で運用上のみ案B相当の対処をしつつコード上は案Aを維持する
方針にした。

### claude.aiの不可への対処: mcp-auth-proxy側の`PROXY_HEADERS`で共通キーを静的注入

- 実運用は事実上シングルユーザー（ユーザー本人のみ）であることを確認済み。per-userの
  厳密な使い分けは不要と判断。
- mcp-auth-proxyの`PROXY_HEADERS=X-Portainer-API-Key:<共通キー>`設定（このgitリポジトリ外、
  mcp-auth-proxyのデプロイ設定）で、`portainer-mcp.vx-xv.com`を経由する全リクエストに
  共通のPortainer APIキーを注入する。これによりclaude.aiのヘッダallowlist制約を
  回避しつつ、portainer-mcp本体のコードは完全にupstream準拠のままにできる。
- 検討した代替（不採用）:
  - 経路A（外部IdPのカスタムクレームでper-user注入）: 現在のIdPはCloudflare Access。
    Portainer APIキーのような独自シークレットをそのuserinfoクレームに持たせるのは
    非現実的（IdP自体の変更が必要になる可能性が高い）ため不採用。
  - 経路B（`/sub`だけ注入しportainer-mcp側でユーザー→キー解決）: portainer-mcp側に
    実装追加が必要でフォーク差分が増えるため、シングルユーザー運用には過剰と判断し不採用。
  - 経路C（mcp-auth-proxy自体のフォーク改造）: 同上の理由で不採用。
- 副作用: `PROXY_HEADERS`は`Add`（`Set`ではない）ため、クライアントが独自に
  `X-Portainer-API-Key`を送ると2本届く可能性がある。運用上、Claude Code CLIの
  `--header`オプションはこの共通キー注入と併用せず、mcp-portal/直接アクセス経路
  すべてで共通キーのみに統一する（クライアント側でのヘッダ指定はしない）。

### upstreamのpassthrough実装確認（`server.py`との配線）

- **caller key適用層**: `src/portainer_mcp/passthrough.py`の`inject_api_key()`が、
  `httpx.AsyncClient`の`event_hooks={"request": [passthrough.inject_api_key]}`として
  登録されるリクエストフック（`server.py`の`build_server()`内、HTTPトランスポート時）。
  in-flightリクエストのコンテキストから`X-Portainer-API-Key`を読み、上流へ`X-API-KEY`
  として注入する。
- **ハンドライトツールへの明示配線要否**: **不要**。フォークの`swarm.py`は
  `register(mcp, client, ...)`で受け取った`client`インスタンスをそのまま`client.get/post/put`
  で使用しており（`src/portainer_mcp/swarm.py`で確認）、`server.py`が`proxy.register()`と
  同じ`client`を`swarm.register()`にも渡す既存のフォークパターンのままで、上記フックが
  自動的に効く。`proxy.py`/`swarm.py`双方とも改修不要。

### guidance.pyのcaller key導出元

`GuidanceGateMiddleware._caller_key()` = `passthrough.digest(passthrough.key_from_request())`
（`X-Portainer-API-Key`のSHA-256ハッシュ）。共通キー運用のため、全callerが同一ハッシュ
＝1つのguidance bucketを共有することになるが、シングルユーザー運用のため実害なしと判断。
**guidance gateは無効化しない（既定のまま有効）。**

### traefikの`X-Forwarded-Proto`検証結果

- 検証当初: portainer-mcp-http向けのtraefik labelsには`customrequestheaders.X-Forwarded-Proto`
  設定が**無かった**（同スタックの他サービスには設定例あり）。traefik_stack自体にも
  HTTPSエントリポイントの静的定義が無く、TLS終端はCloudflare Tunnel側で行われる構成。
- **対処実施済み（2026-08-09）**: 既存の`portainer-mcp-http-cors`ミドルウェアに
  `headers.customrequestheaders.X-Forwarded-Proto=https`を追加する形でユーザーが
  Swarmスタック定義を変更し、swarm-inspectorで反映を確認済み。
- **TLSポスチャ**: `PORTAINER_MCP_TRUST_PROXY_TLS=1` + `PORTAINER_MCP_FORWARDED_ALLOW_IPS`
  （値=overlayネットワークのCIDR。フェーズ4で設定時に確認済みの値を使う）を採用する。

### `PORTAINER_MCP_ALLOWED_HOSTS`

現行値をユーザーから確認済み（本ファイルには記載しない方針のため変数名のみ記録）。
mcp-auth-proxy→portainer-mcpコンテナ間のHost転送挙動は今回変更していないため、
現行値のまま変更不要と判断。

### 本番に設定する環境変数の最終リスト（変数名と意味）

| 変数名 | 意味 | 備考 |
|---|---|---|
| `PORTAINER_API_KEY` | HTTP起動時は**設定しない**（設定するとSystemExitで起動拒否） | stdioのローカル開発では従来どおり使用 |
| `PORTAINER_MCP_TRUST_PROXY_TLS` | `1`。traefikのX-Forwarded-Protoを信頼するTLSポスチャ | 上記traefik対処により有効化可能になった |
| `PORTAINER_MCP_FORWARDED_ALLOW_IPS` | overlayネットワークのCIDR（信頼するproxy送信元） | 値はフェーズ4で設定時に確認 |
| `PORTAINER_MCP_ALLOWED_HOSTS` | DNS-rebinding対策のHostヘッダallowlist | 現行値のまま変更不要（ユーザー確認済み） |
| （mcp-auth-proxy側）`PROXY_HEADERS` | `X-Portainer-API-Key:<共通キー>`を全リクエストに注入 | このリポジトリ外の設定。フォーク側のコードには影響しない |
| `PORTAINER_MCP_DISABLE_GUIDANCE_GATE` | 設定しない（既定=有効のまま） | 共通キー運用でも実害小と判断 |
