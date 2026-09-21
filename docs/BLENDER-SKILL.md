# Blender batch modeling Skill

Blender標準CLIと既存のGoogle Drive uploaderを使用します。
MCPサーバー、仮想ディスプレイ、専用ランナーは不要です。

## 配置と実行

[Skill](../.codex/skills/blender-modeling/SKILL.md) はホームディレクトリの
`.codex/skills/blender-modeling/` に配置されます。feature worktreeへの配置だけでは、
利用中のホームディレクトリには反映されません。マージ・反映後、新しいCodex
セッションで `$blender-modeling` を指定してください。

`install.sh` はmise管理のBlenderと起動に必要なOSライブラリを導入します。
作品ごとの `build.py` はBlender内蔵Pythonで実行します。実行例：

```bash
mise exec blender -- blender --background --factory-startup --python-exit-code 1 --python /absolute/path/build.py -- /absolute/path/output
```

末尾の出力先はスクリプト側で `--` 以降の引数から読み取ります。
これは新規シーン用の例です。既存作品は元の `.blend` を読み込み、別名保存します。
バックグラウンド処理はGUIで未保存の編集を取得できません。
既存ファイルを読む場合はファイル引数より前に `--disable-autoexec` を指定します。
CLI引数は順番に処理されるため、エラー終了コード指定はPython実行より前に置きます。
[Blender CLI資料](https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html)

## 作品の保持

作品ごとに最終形だけを一組として保持します。

- `build.py`：最終版の生成・編集スクリプト
- `model.blend`：完成シーン
- `preview.png`：確認画像
- `RUN.md`：Blenderバージョン、実行コマンド、入力素材、成果物一覧
- 必要な入力素材、および依頼されたGLB/FBXなどの出力

GUIで手直しした場合は `.blend` を正とし、再生成で失われる変更を `RUN.md`
に記録します。作品のGit履歴管理は不要です。リポジトリ自体の変更には引き続き
通常のGit/PR運用を適用します。

作業中はIssueのtask rootを使用できますが、cleanup前に最終一式を永続保存先へ
退避してください。保存・アップロードが失敗した状態で唯一のコピーを削除しません。

## Google Drive

作品タスクで明示的にアップロードを依頼された場合のみ、既存entrypointを使います。
成果物固有のフォルダ名と任意の親フォルダIDを確認して、最終ファイルを一回の呼び出しで
新規フォルダへ送れます。

```bash
bin/google-drive-uploader status
bin/google-drive-uploader upload --folder-name ARTIFACT_NAME --parent-folder-id PARENT_FOLDER_ID /absolute/path/build.py /absolute/path/model.blend /absolute/path/preview.png /absolute/path/RUN.md
```

`DRIVE_FOLDER_ID` と各パスは実際の値へ置き換えます。必要な素材やexportも
明示的なファイル一覧に追加します。ディレクトリの再帰uploadは対応していません。
Pythonやメモに秘密情報がないことを確認し、認証ファイルは含めません。

現行uploaderは成果物名の新規フォルダを作り、その中に新規ファイルを作成して
名前・サイズ照合を行います。同名フォルダやファイルを再利用・上書きしません。
「最終形のみ」はアップロード対象の選別方針であり、過去のDriveファイルを自動削除する
機能ではありません。部分成功時は表示されたフォルダIDを使い、未送信ファイルだけを
既存の `--folder-id` で再送します。

## 利用例と確認

「高さ45 cm、座面直径30 cm、4本脚の木製スツールを作り、
最終Python・blend・確認画像・実行メモを指定Driveフォルダに保存してください」

寸法と出力先を確認し、Python作成、バッチ実行、寸法確認、レンダリングと画像確認、
必要な修正、最終成果物の保存・転送を行います。
読取専用の依頼では保存や生成を行いません。
終了コード0だけで成功とせず、生成ファイルと内容を確認します。
レンダリングや転送の失敗時は、その段階と未完了の成果物を報告します。

## 旧MCP構成からの移行

Blender MCP設定、`tools/blender_mcp` の依存定義、アドオン自動導入は廃止します。
既存OSランタイムライブラリとBlender本体はバッチ起動にも必要なため保持します。
更新した設定はCodexセッション再起動後に利用してください。
既に手動で有効化したアドオンや起動済みサーバーがある場合は、停止・無効化の
対象を確認して個別に処理します。インストーラはユーザー設定を一括削除しません。

上流MCPは `blender -b` でのサーバー起動を拒否します。
[上流PR #272](https://github.com/ahujasid/mcp-for-blender/pull/272) と
固定版2.0.0の同梱addonで確認しました。標準バッチ処理への変更理由です。

## 公開ツールの採用判断

2026-09-20にREADMEとGitHubのrepository license metadataを確認しました。
以下の4候補はMIT表記でした。依存ライブラリ・配布素材のライセンスまで
監査したものではありません。Skill本文やコードのコピーはありません。

| 候補 | 判断 |
| --- | --- |
| [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) | 仮想画面・常駐プロセスを増やすため今回の通常経路から除外。 |
| [newo-ether/blender-mcp](https://github.com/newo-ether/blender-mcp) | MCP/Skill構成の候補だがバッチ方針では導入しない。 |
| [RobLe3/cc-blender-skill](https://github.com/RobLe3/cc-blender-skill) | Claude向けツール規約の評価が必要。現時点でvendorしない。 |
| [ifBars/blender-agent-studio](https://github.com/ifBars/blender-agent-studio) | より広いworkflow/validationが必要になった時に再評価。 |

標準CLIと [Blender Python API](https://docs.blender.org/api/current/) を優先します。
ドキュメントは実行中のBlenderバージョンと照合してください。
#45のworkflow、#43の自動検証、#44のモデルルーティングは別途検討します。
