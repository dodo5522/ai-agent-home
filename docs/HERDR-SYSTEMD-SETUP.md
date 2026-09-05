# Herdr / Codex user service 運用手順

## 構成

- Herdr: `0.8.2` (`/home/takashi/.local/bin/herdr`)
- Codex CLI: `0.153.2` (`/home/takashi/.local/share/mise/shims/codex`)
- Herdr server: `~/.config/systemd/user/herdr.service`
- Agent 復旧: `~/.config/systemd/user/herdr-agents.service`
- Agent 起動スクリプト: `~/bin/start-herdr-agents.sh`

両 unit はすでに `systemctl --user enable` 済みです。

## 初回切替

現在の Herdr server は systemd 管理外で動作しているため、以下は Herdr 内の
Codex pane ではなく、別の通常 SSH シェルから実行します。`server stop` により
現在の Herdr pane は終了しますが、Codex の会話履歴は Codex 側に保存済みで、
次回起動時に `codex resume --last --all` が選択されます。

```bash
herdr server stop
systemctl --user daemon-reload
systemctl --user enable --now herdr.service
systemctl --user enable --now herdr-agents.service
```

## 初回切替後の確認

```bash
systemctl --user status herdr.service --no-pager
systemctl --user status herdr-agents.service --no-pager
herdr status
herdr agent list
```

ログを確認する場合:

```bash
journalctl --user -u herdr.service -u herdr-agents.service -b --no-pager
```

## 二重起動防止の確認

`herdr-agents.service` を再起動しても、既存の live Codex Agent を検出して
新しい Agent を起動しません。

```bash
herdr agent list
systemctl --user restart herdr-agents.service
systemctl --user status herdr-agents.service --no-pager
herdr agent list
```

前後で Codex Agent の数と pane ID が変わらないことを確認します。

## SSH ログインなしで起動するための linger

現在は `Linger=no` です。VM boot 時に `takashi` の user manager を起動するには、
管理者が一度だけ次を実行する必要があります。この作業では実行していません。

```bash
sudo loginctl enable-linger takashi
loginctl show-user takashi -p Linger
```

期待値:

```text
Linger=yes
```

## VM reboot 後の検証

`Linger=yes` と初回切替後のサービス正常動作を確認してから、利用者自身の判断で
reboot を実行します。この作業では reboot を実行していません。

```bash
sudo reboot
```

VM 起動後に SSH 接続し、次を確認します。

```bash
systemctl --user is-enabled herdr.service herdr-agents.service
systemctl --user is-active herdr.service herdr-agents.service
systemctl --user status herdr.service --no-pager
systemctl --user status herdr-agents.service --no-pager
herdr status
herdr agent list
journalctl --user -u herdr.service -u herdr-agents.service -b --no-pager
```

期待結果:

- 両 unit が `enabled`
- `herdr.service` が `active (running)`
- `herdr-agents.service` が `active (exited)`
- `herdr status` で server が running / compatible
- `herdr agent list` に Codex Agent が1つだけ存在

## 復旧ロジック

1. Herdr server が running / compatible になるまで最大120秒待機
2. live Codex Agent があれば何もせず終了
3. 既存 workspace 内の空いている shell pane を動的に選択
4. 利用可能な pane がなければ workspace を作り、返却 JSON から pane ID を取得
5. Codex session index に保存 session があれば `resume --last --all`
6. resume が失敗した場合は Agent 一覧を再確認し、Agent が出現していなければ新規起動

固定の `w1:p1` などは使用していません。
