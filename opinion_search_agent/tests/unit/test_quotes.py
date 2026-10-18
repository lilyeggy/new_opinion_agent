"""Quote provenance: the deterministic half of "can you show me those words?"."""

from __future__ import annotations

from opinion_search.investigation.quotes import (
    locate,
    missing_from_excerpts,
    quoted_spans,
    unbacked_quotes,
)


def test_quoted_spans_reads_both_bracket_styles_and_deduplicates():
    text = "他写道“守护单身狗的胃”，又说「养胃饺饺者」，结尾再提“守护单身狗的胃”。"
    assert quoted_spans(text) == ("守护单身狗的胃", "养胃饺饺者")


def test_quoted_spans_ignores_two_character_scare_quotes():
    assert quoted_spans("所谓“团圆”其实不团圆。") == ()


def test_unbacked_quotes_separates_present_from_absent():
    text = "媒体称“守护单身狗的胃”，并追问“月饼和冷饮不要在胃里团圆了”。"
    documents = ["……守护单身狗的胃……"]
    assert unbacked_quotes(text, documents) == ("月饼和冷饮不要在胃里团圆了",)


def test_missing_from_excerpts_keeps_quotes_the_document_does_contain():
    text = "评论写“反常规就会从记忆点变成冒犯点”。"
    # The excerpt stops before the quote, yet the document does contain it: this
    # is a retrieval miss, not a fabrication, and the two checks must disagree.
    assert missing_from_excerpts(text, ["评论开篇写道，"]) == ("反常规就会从记忆点变成冒犯点",)
    assert unbacked_quotes(text, ["评论开篇写道，反常规就会从记忆点变成冒犯点。"]) == ()


def test_locate_tolerates_wrapped_lines_and_returns_the_exact_span():
    document = "前文\n“可以反节日套路，\n不能反文化共识”后文"
    found = locate("可以反节日套路，不能反文化共识", [("v1", document)])
    assert found is not None
    version_id, start, end, excerpt = found
    assert version_id == "v1"
    assert document[start:end] == excerpt
    assert excerpt.startswith("可以反节日套路")
    assert excerpt.endswith("不能反文化共识")


def test_locate_returns_none_when_no_document_contains_the_quote():
    assert locate("从未出现的一句话", [("v1", "无关正文")]) is None


def test_locate_bridges_the_other_bracket_style() -> None:
    document = [("v1", "品牌本想成为\u201c\u5634\u66ff\u201d\uff0c\u5374\u4e0d\u5c0f\u5fc3\u6210\u4e86\u201c\u6760\u7cbe\u201d\u3002")]
    found = locate("\u54c1\u724c\u672c\u60f3\u6210\u4e3a\u2018\u5634\u66ff\u2019\uff0c\u5374\u4e0d\u5c0f\u5fc3\u6210\u4e86\u2018\u6760\u7cbe\u2019", document)
    assert found is not None
    version_id, start, end, span = found
    assert (version_id, end - start) == ("v1", len(span))
