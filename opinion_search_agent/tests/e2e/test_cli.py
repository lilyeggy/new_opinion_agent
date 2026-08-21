from opinion_search.__main__ import main


def test_offline_and_resume_cli_share_the_checkpoint(tmp_path, capsys) -> None:
    checkpoint = tmp_path / "cli.json"

    exit_code = main(
        [
            "offline",
            "--question",
            "What happened?",
            "--run-id",
            "cli-demo",
            "--checkpoint",
            str(checkpoint),
        ]
    )
    first_output = capsys.readouterr()

    assert exit_code == 0
    assert "# OpinionSearch Brief" in first_output.out
    assert checkpoint.exists()
    report_md = checkpoint.parent / "report.md"
    assert report_md.exists()
    first_report_bytes = report_md.read_bytes()

    exit_code = main(
        [
            "resume",
            "--mode",
            "offline",
            "--checkpoint",
            str(checkpoint),
        ]
    )
    resumed_output = capsys.readouterr()

    assert exit_code == 0
    assert resumed_output.out == first_output.out
    assert report_md.read_bytes() == first_report_bytes
    assert "Report written to" in resumed_output.err


def test_live_cli_reports_missing_environment_without_network(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPINION_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    exit_code = main(
        [
            "live",
            "--question",
            "What happened?",
            "--checkpoint",
            str(tmp_path / "live.json"),
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert "OPINION_MODEL_API_KEY" in output.err
    assert "BRAVE_SEARCH_API_KEY" in output.err


def test_resume_rejects_a_different_execution_mode_before_network(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    checkpoint = tmp_path / "profile.json"
    assert (
        main(
            [
                "offline",
                "--question",
                "What happened?",
                "--checkpoint",
                str(checkpoint),
            ]
        )
        == 0
    )
    capsys.readouterr()
    monkeypatch.setenv("OPINION_MODEL_API_KEY", "model-test-key")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-test-key")

    exit_code = main(
        [
            "resume",
            "--mode",
            "live",
            "--checkpoint",
            str(checkpoint),
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 2
    assert "execution profile" in output.err
