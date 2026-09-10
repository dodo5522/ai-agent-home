# Herdr Task Start

Issue の実装開始時に、GitHub IssueとHerdrのWorkspace / Tab / paneを解決し、
状態ファイルへランタイム参照を記録するCLIの運用リファレンスです。

## CLI

Herdr管理下のpaneから次を実行します。

```text
herdr-task-start ISSUE_NUMBER [--cwd PATH]
```

このコマンドは状態管理CLIとは分離した `tools/herdr_task_start` パッケージとして提供され、
`herdr_task_state` のモデルとStateStoreをローカル依存として参照します。`uvx` では次のように実行します。

```bash
uvx --from ./tools/herdr_task_start herdr-task-start 32
```

`HERDR_ENV=1` を要求し、`--cwd`（省略時は現在ディレクトリ）のGit `origin` remoteと
GitHub CLIから `owner/name#issue-number` とIssueタイトルを解決します。Workspace labelは
`owner/name`、Tab labelはIssue番号と短縮タイトルです。

## 安全な再構成

作成・再利用の対象はstateに保存されたHerdr IDからのみ判定します。labelだけが一致する
unmanagedなWorkspace / Tab / paneは取り込まず、rename・移動・削除もしません。保存済みIDが
staleの場合は既存リソースを変更せず、新しい管理対象を作成します。作成時は `--no-focus` と
対象cwdを指定し、Tabのpaneがちょうど1つであることを確認します。

Herdr / GitHub / state更新のいずれかが失敗した場合、stateは成功した結果だけを保存します。
`herdr-task-state get`、`validate`などのread-onlyコマンドはHerdrリソースを作成しません。
作業完了後のTab、worktree、task rootのcleanupはIssue #33のライフサイクル仕様に従います。

状態ファイルのスキーマと低レベルCLIは、[`docs/HERDR-TASK-STATE.md`](HERDR-TASK-STATE.md)を参照してください。
