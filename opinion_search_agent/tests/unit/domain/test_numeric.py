"""Numeric conflict detection.

The detector answers one question: do two frozen documents state the same money
metric at values one order of magnitude apart? It is deliberately narrow -- it
only compares cross-document pairs, it only looks at money units, and it only
reports gaps that round to a whole power of ten.
"""

from decimal import Decimal

from opinion_search.domain.numeric import extract_quantities, find_conflicts

YI = Decimal(10) ** 8


def test_extracts_money_quantity_with_unit():
    found = extract_quantities("doc-1", "2025年华润三九实现营业收入316.03亿元，同比增长14.43%")
    assert len(found) == 1
    quantity = found[0]
    assert quantity.metric.endswith("营业收入")
    assert quantity.value == Decimal("316.03") * YI
    assert quantity.literal == "316.03亿元"


def test_ignores_years_percentages_and_bare_counts():
    assert extract_quantities("doc-1", "2025年，同比增长14.43%，共 3 次。") == []


def test_metric_key_drops_leading_year_and_trailing_verb():
    assert extract_quantities("doc", "2025年销售费用高达90.89亿元")[0].metric == "销售费用"
    assert extract_quantities("doc", "2025年销售费用高达908.9亿元")[0].metric == "销售费用"


def test_conflict_across_documents_for_a_tenfold_gap():
    documents = [
        ("real", "2025年华润三九实现营业收入316.03亿元。"),
        ("plant", "华润三九2025年营业收入达3160.3亿元。"),
    ]
    conflicts = find_conflicts(documents)
    assert len(conflicts) == 1
    assert "营业收入" in conflicts[0].metric
    assert conflicts[0].factor == 10
    assert conflicts[0].lower.value == Decimal("316.03") * YI
    assert conflicts[0].higher.document_id == "plant"


def test_same_document_is_never_a_conflict():
    documents = [("doc", "营业收入316.03亿元。营业收入3160.3亿元。")]
    assert not find_conflicts(documents)


def test_small_gap_is_not_a_conflict():
    documents = [("a", "营业收入316.03亿元。"), ("b", "营业收入320.5亿元。")]
    assert not find_conflicts(documents)


def test_different_metrics_are_not_compared():
    documents = [("a", "营业收入316.03亿元。"), ("b", "净利润3160.3亿元。")]
    assert not find_conflicts(documents)


def test_hundredfold_gap_reports_two_orders():
    documents = [("a", "营业收入3.16亿元。"), ("b", "营业收入316.03亿元。")]
    conflicts = find_conflicts(documents)
    assert len(conflicts) == 1
    assert conflicts[0].factor == 100
