# ai-agent-home

Ubuntu Server VM 上で Herdr を常時稼働させ、VM の再起動後に Herdr と
Codex セッションを自動復旧するためのホームディレクトリテンプレートです。

## 対応環境

- Ubuntu Server
- ユーザー名 `takashi`、配置先 `/home/takashi`
- `takashi` ユーザーが `sudo` を利用可能（root での実行は非対応）
- インターネット接続

インストーラは Ubuntu 専用です。認証情報や秘密鍵は安全のため自動生成・配置しません。

## 自動インストールされるもの

[`install.sh`](install.sh) は次の依存関係をまとめてインストールします。

- Ubuntu パッケージ: `build-essential`、`ca-certificates`、`curl`、`git`、
  `jq`、`util-linux`（`flock` を含む）
- Tailscale
- mise
- `.config/mise/config.toml` に固定された Codex CLI、Herdr、Node.js、Python
- `bin/github-app-token.py` が使用する Python パッケージ `PyJWT[crypto]`

既に存在する Tailscale と mise は再インストールしません。`apt-get`、
`mise install`、`pip install` は再実行しても安全な形で呼び出します。

## インストール方法

リポジトリのルートで、通常のログインユーザーとして実行します。スクリプト全体を
`sudo` で実行する必要はありません。必要なシステム操作だけが `sudo` を使用します。

```bash
./install.sh
```

実際に変更する前に処理内容を確認するには、dry-run を使用します。

```bash
./install.sh --dry-run
```

mise を現在の Bash セッションで有効化します。

```bash
eval "$(~/.local/bin/mise activate bash)"
```

新しいシェルでも自動的に有効化する場合は、同じ行を `~/.bashrc` に追加してください。

## 手動設定

### Tailscale の接続

```bash
sudo tailscale up
```

表示された URL を開き、対象の tailnet に端末を登録します。

### Codex と Herdr の認証・連携

```bash
codex login
herdr integration install codex
```

各コマンドの案内に従って認証してください。

### GitHub App の設定

`.config/github-app/config` に GitHub App の Client ID と Installation ID を設定し、
秘密鍵を `.config/github-app/private-key.pem` に配置します。その後、設定ディレクトリと
秘密鍵の権限を制限します。

```bash
chmod 700 ~/.config/github-app
chmod 600 ~/.config/github-app/config ~/.config/github-app/private-key.pem
```

秘密鍵は Git に追加しないでください。

```text
GITHUB_APP_CLIENT_ID=<client-id>
GITHUB_APP_INSTALLATION_ID=<installation-id>
```

### user service の有効化

```bash
systemctl --user daemon-reload
systemctl --user enable --now herdr.service herdr-agents.service
```

詳細は [`docs/HERDR-SYSTEMD-SETUP.md`](docs/HERDR-SYSTEMD-SETUP.md) を参照してください。

## インストール確認

```bash
jq --version
flock --version
tailscale version
mise current
mise exec python -- python -c 'import jwt; print(jwt.__version__)'
```

Herdr の稼働状態は次のコマンドで確認できます。

```bash
systemctl --user status herdr.service herdr-agents.service
```

## 更新と再実行

`.config/mise/config.toml` のバージョンを変更した後は、`./install.sh` を再実行して
ください。固定済みツールと Python パッケージが現在の定義に合わせて更新されます。

## トラブルシューティング

- `unsupported operating system` と表示される場合、Ubuntu 上で実行してください。
- `sudo is required` と表示される場合、`sudo` を導入してログインユーザーで実行してください。
- mise のコマンドが見つからない場合、上記の `mise activate bash` を実行するか、
  `~/.local/bin` を `PATH` に追加してください。
- インストール前の確認には `./install.sh --dry-run` を使用してください。

## テスト

インストーラの非破壊モードと CLI 契約は次のコマンドで検証できます。

```bash
./tests/install_test.sh
```
