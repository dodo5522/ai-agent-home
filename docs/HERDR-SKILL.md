# Herdr Skill 運用手順

## 配置と発火条件

upstream の [`herdr` Skill](https://github.com/herdrdev/herdr/blob/master/skills/herdr/SKILL.md)
を Codex 用の `.codex/skills/herdr/SKILL.md` に配置しています。リポジトリを
`/home/takashi` に展開すると `~/.codex/skills/herdr/SKILL.md` となり、Codex は次回の
turn から Skill を利用できます。

Skill は、利用者が Herdr を明示した場合、または Herdr で workspace、tab、pane、
command、別 Agent を確認・操作するよう依頼した場合だけ発火します。単に並列処理が
便利という理由では発火させません。

操作前に、現在の Codex が Herdr 管理下にいることを確認します。

```bash
test "${HERDR_ENV:-}" = 1
```

`HERDR_ENV=1` でなければ、別 client の focused pane を外部から操作せず停止します。
Skill を新規配置または更新した後は、新しい Codex turn で利用してください。

## Agent 管理の標準手順

インストール済み CLI の構文を正とし、最初に `herdr --help` と `herdr agent` で確認
します。bare `herdr` は TUI を起動するため discovery には使いません。

1. `herdr agent list` で live Agent と状態を取得する。
2. 必要なら `herdr pane split --current ... --no-focus` を実行し、応答の
   `.result.pane.pane_id` を保存する。
3. 固有名と明示 pane ID で `herdr agent start <name> --kind codex --pane <pane-id>`
   を実行する。
4. `herdr agent prompt <name> "<instruction>" --wait --timeout <ms>` で指示と待機を
   行う。
5. 追加の待機には `herdr agent wait <name>`、状態確認には
   `herdr agent get <name>` を使う。
6. `herdr agent read <name> --source recent-unwrapped --lines <n>` で出力を取得する。

workspace、tab、pane、Agent の ID は例や表示順から推測せず、必ず Herdr CLI の
JSON 応答から取得します。pane 操作は `--current` または明示的な pane ID、Agent 操作は
固有の Agent 名または Agent を収容する pane ID で対象を指定します。terminal ID、
bare Agent kind、別 client の focused pane には依存しません。

background 操作では原則 `--no-focus` を使い、利用者の focus を維持します。明示的な
依頼なしに workspace、tab、pane、session を閉じたり、異なる workspace や worktree
を作成したりしません。

## Agent 状態の扱い

| 状態 | 扱い |
| --- | --- |
| `idle` | 入力可能。必要な指示を `agent prompt` で送る。 |
| `working` | 実行中。重複 prompt を送らず `agent wait` または `agent get` で追跡する。 |
| `blocked` | 承認または質問 UI を `agent get` と `agent read` で確認し、人間へ判断を求める。承認や回答を自動送信しない。 |
| `done` | 未確認の background 作業が完了。`agent read` で結果を取得する。 |
| `unknown` | 状態を確定できない。完了とみなさず `agent get` と `agent read` で確認する。 |

`agent prompt --wait` または `agent wait` が失敗した場合も、再送前に `agent get` と
`agent read` で実状態を確認します。`blocked` への応答が必要なら、画面の内容と必要な
判断を利用者へ提示し、利用者の明示回答を待ちます。

## upstream 更新手順

Herdr のバージョン更新時に upstream Skill と vendored copy の差分を確認します。
`.codex/skills/herdr/UPSTREAM.md` に、確認済みの upstream commit と SHA-256 を記録
します。`master` の最新 commit を確認してから、その immutable revision を取得します。

```bash
upstream_commit=$(curl -fsSL \
  -H 'Accept: application/vnd.github+json' \
  https://api.github.com/repos/herdrdev/herdr/commits/master | jq -er .sha)
upstream_skill=$(mktemp)
trap 'rm -f "$upstream_skill"' EXIT
curl -fsSL \
  "https://raw.githubusercontent.com/herdrdev/herdr/$upstream_commit/skills/herdr/SKILL.md" \
  -o "$upstream_skill"
diff -u .codex/skills/herdr/SKILL.md "$upstream_skill"
sha256sum "$upstream_skill"
```

変更がある場合は upstream ファイル全体を `.codex/skills/herdr/SKILL.md` に反映し、
`UPSTREAM.md` の commit と checksum を同時に更新します。本書の標準手順との整合性を
確認して `./tests/install_test.sh` を実行します。upstream 固有の内容を vendored copy
内で独自編集せず、この文書にローカル運用を記載します。

## 関連 Issue との役割分担

- [#9](https://github.com/dodo5522/ai-agent-home/issues/9): 固有 Agent 名を使う複数
  Agent の定義、起動、個別復旧を実装する。
- [#11](https://github.com/dodo5522/ai-agent-home/issues/11): Agent ごとの worktree と
  Herdr workspace / pane の所有関係、cleanup を定義する。
- [#12](https://github.com/dodo5522/ai-agent-home/issues/12): 本手順の Agent 操作を使い、
  read-only を原則とする Reviewer Agent の役割と報告先を定義する。
- [#17](https://github.com/dodo5522/ai-agent-home/issues/17): 本手順の `blocked` / `done`
  状態を通知へ接続し、状態変化時だけ通知する。

本 Issue はこれらに共通する安全な Herdr CLI 操作を定義し、個別機能の実装は各 Issue
に委ねます。
