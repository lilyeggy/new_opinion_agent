import pytest

from opinion_search.runtime.journal import (
    JournalCorruptError,
    JournalError,
    RuntimeJournal,
)


def test_missing_file_reads_as_empty(tmp_path):
    journal = RuntimeJournal(tmp_path / "run.journal")

    assert journal.read() == []


def test_append_then_read_preserves_order_and_content(tmp_path):
    journal = RuntimeJournal(tmp_path / "run.journal")

    journal.append({"step_index": 0, "text": "第一步"})
    journal.append({"step_index": 1, "text": "second"})

    assert journal.read() == [
        {"step_index": 0, "text": "第一步"},
        {"step_index": 1, "text": "second"},
    ]


def test_append_rejects_non_increasing_step_index(tmp_path):
    journal = RuntimeJournal(tmp_path / "run.journal")
    journal.append({"step_index": 3})

    with pytest.raises(JournalCorruptError):
        journal.append({"step_index": 3})
    with pytest.raises(JournalCorruptError):
        journal.append({"step_index": 2})


def test_append_requires_integer_step_index(tmp_path):
    journal = RuntimeJournal(tmp_path / "run.journal")

    with pytest.raises(JournalError):
        journal.append({"text": "no index"})
    with pytest.raises(JournalError):
        journal.append({"step_index": True})


def test_torn_trailing_line_is_ignored_on_read(tmp_path):
    path = tmp_path / "run.journal"
    journal = RuntimeJournal(path)
    journal.append({"step_index": 0})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"step_index":1,"tru')

    assert journal.read() == [{"step_index": 0}]


def test_append_after_torn_tail_repairs_before_writing(tmp_path):
    path = tmp_path / "run.journal"
    journal = RuntimeJournal(path)
    journal.append({"step_index": 0})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"step_index":1,"tru')

    journal.append({"step_index": 1, "ok": True})

    raw = path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert journal.read() == [{"step_index": 0}, {"step_index": 1, "ok": True}]


def test_corrupt_complete_line_raises(tmp_path):
    path = tmp_path / "run.journal"
    path.write_text('{"step_index":0}\nnot-json\n', encoding="utf-8")

    with pytest.raises(JournalCorruptError):
        RuntimeJournal(path).read()


def test_empty_middle_line_raises(tmp_path):
    path = tmp_path / "run.journal"
    path.write_text('{"step_index":0}\n\n{"step_index":1}\n', encoding="utf-8")

    with pytest.raises(JournalCorruptError):
        RuntimeJournal(path).read()


def test_read_rejects_non_monotonic_file(tmp_path):
    path = tmp_path / "run.journal"
    path.write_text('{"step_index":2}\n{"step_index":1}\n', encoding="utf-8")

    with pytest.raises(JournalCorruptError):
        RuntimeJournal(path).read()


def test_truncate_after_drops_later_records(tmp_path):
    journal = RuntimeJournal(tmp_path / "run.journal")
    for index in range(4):
        journal.append({"step_index": index})

    removed = journal.truncate_after(1)

    assert removed == 2
    assert [r["step_index"] for r in journal.read()] == [0, 1]


def test_truncate_after_is_noop_when_nothing_to_drop(tmp_path):
    path = tmp_path / "run.journal"
    journal = RuntimeJournal(path)
    journal.append({"step_index": 0})
    before = path.read_bytes()

    assert journal.truncate_after(5) == 0
    assert path.read_bytes() == before


def test_truncate_after_repairs_torn_tail_even_without_drops(tmp_path):
    path = tmp_path / "run.journal"
    journal = RuntimeJournal(path)
    journal.append({"step_index": 0})
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"step_index":1')

    assert journal.truncate_after(0) == 0
    assert path.read_text(encoding="utf-8") == '{"step_index":0}\n'


def test_non_serializable_payload_is_rejected_without_writing(tmp_path):
    path = tmp_path / "run.journal"
    journal = RuntimeJournal(path)

    with pytest.raises(JournalError):
        journal.append({"step_index": 0, "bad": object()})
    assert not path.exists()
