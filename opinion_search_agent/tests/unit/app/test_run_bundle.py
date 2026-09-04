import asyncio

import pytest

from opinion_search.app.run_bundle import RunBundleError, RunBundleWriter
from opinion_search.domain.opinion.brief import SearchOutcome, SearchReportView
from opinion_search.runtime.lifecycle import RunStatus


def _outcome(*, markdown: str = "# OpinionSearch Brief\n\nDone.") -> SearchOutcome:
    return SearchOutcome(
        status=RunStatus.COMPLETED,
        stop_reason="Accepted.",
        report=SearchReportView(
            question="What happened?",
            scope_limitation="Accessible public-Web sources only.",
        ),
        markdown=markdown,
        source_urls=("https://example.test/a",),
        remaining_gap_ids=(),
    )


def test_write_report_creates_report_md_with_terminal_newline(tmp_path) -> None:
    checkpoint = tmp_path / "run.json"
    outcome = _outcome(markdown="first report")

    writer = RunBundleWriter(checkpoint)
    report_path = asyncio.run(writer.write_report(outcome))

    assert report_path == (tmp_path / "report.md").resolve()
    assert report_path.read_text(encoding="utf-8") == "first report\n"
    persisted = SearchOutcome.model_validate_json(
        (tmp_path / "outcome.json").read_text(encoding="utf-8")
    )
    assert persisted == outcome
    assert not list(tmp_path.glob("*.tmp"))


def test_write_report_resolve_is_absolute_and_normalized(tmp_path) -> None:
    checkpoint = tmp_path / "sub" / "run.json"
    writer = RunBundleWriter(checkpoint)

    assert writer.report_path == (tmp_path / "sub" / "report.md").resolve()
    assert writer.outcome_path == (tmp_path / "sub" / "outcome.json").resolve()
    assert str(writer.report_path).startswith("/")


def test_resume_rewrites_byte_identical_report(tmp_path) -> None:
    checkpoint = tmp_path / "run.json"
    outcome = _outcome(markdown="# OpinionSearch Brief\n\nFinal.")

    writer = RunBundleWriter(checkpoint)
    asyncio.run(writer.write_report(outcome))
    first_bytes = (tmp_path / "report.md").read_bytes()

    asyncio.run(writer.write_report(outcome))
    second_bytes = (tmp_path / "report.md").read_bytes()

    assert second_bytes == first_bytes


def test_existing_reader_artifact_directory_is_not_copied(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "page.txt").write_text("artifact body", encoding="utf-8")

    checkpoint = tmp_path / "run.json"
    asyncio.run(RunBundleWriter(checkpoint).write_report(_outcome()))

    assert (artifacts / "page.txt").read_text(encoding="utf-8") == "artifact body"


def test_write_failure_returns_typed_error_and_keeps_old_report(
    tmp_path,
    monkeypatch,
) -> None:
    checkpoint = tmp_path / "run.json"
    report = tmp_path / "report.md"
    report.write_text("old report", encoding="utf-8")

    writer = RunBundleWriter(checkpoint)
    asyncio.run(writer.write_report(_outcome(markdown="new report")))

    from opinion_search.app import run_bundle

    def fail_replace(source, target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(run_bundle.os, "replace", fail_replace)

    with pytest.raises(RunBundleError):
        asyncio.run(writer.write_report(_outcome(markdown="new report")))

    assert report.read_text(encoding="utf-8") == "new report\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_report_contains_only_the_markdown_without_config_serialization(
    tmp_path,
) -> None:
    # The writer must emit only outcome.markdown; it must not append app
    # configuration, execution profile, or any secret-bearing field.
    checkpoint = tmp_path / "run.json"
    outcome = _outcome(markdown="# OpinionSearch Brief\n\nBody.")

    asyncio.run(RunBundleWriter(checkpoint).write_report(outcome))

    content = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert content == "# OpinionSearch Brief\n\nBody.\n"
    assert "execution" not in content.casefold()
    assert "secret" not in content.casefold()
