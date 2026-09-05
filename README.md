# Ubuntu Server VM 上で Herdr を常時稼働させ、VM 再起動後に Herdr と Codex セッションが自動復旧する構成の Home ディレクトリテンプレート

## 前提条件

- mise インストール済み
- Herdr インストール済み
- Codex CLI インストール・認証済み
- herdr integration install codex 実行済み
- Tailscale 導入済み
- Herdr は systemd --user の user service として動かす

