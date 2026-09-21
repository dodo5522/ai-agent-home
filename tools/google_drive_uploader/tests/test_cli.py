from google_drive_uploader.cli import build_parser


def test_upload_parser_accepts_artifact_folder_name_and_parent() -> None:
    args = build_parser().parse_args(
        [
            "upload",
            "--folder-name",
            "chair-final",
            "--parent-folder-id",
            "artifacts-root",
            "build.py",
        ]
    )

    assert args.folder_name == "chair-final"
    assert args.parent_folder_id == "artifacts-root"
    assert args.paths[0].name == "build.py"
