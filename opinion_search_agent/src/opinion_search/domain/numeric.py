"""Cross-source numeric consistency checking.

The provenance guard asks "does this number have a source?".  It cannot ask
"do the sources that report this metric agree?" - so a value inflated by a
factor of ten can sit next to the accurate one without anything noticing.

This module adds the second question.  It extracts money quantities, keys each
one by the metric phrase that precedes it, groups the keys that share a common
suffix ("公司销售费用" and "年销售费用" share "销售费用"), and reports groups
whose values differ by a power of ten across different documents.

The scope is deliberately narrow.  Only currency magnitudes (元 / 万 / 万元 /
亿 / 亿元) are compared, and only a ten-fold or hundred-fold gap counts as a
conflict, so growth rates, counts and unrelated metrics cannot collide through
a shared suffix.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import math
import re
from decimal import Decimal, InvalidOperation

_UNIT_SCALE: dict[str, Decimal] = {
    "元": Decimal(1),
    "万": Decimal(10_000),
    "万元": Decimal(10_000),
    "亿": Decimal(100_000_000),
    "亿元": Decimal(100_000_000),
}

_QUANTITY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(亿元|万元|亿|万|元)")
_YEAR = re.compile(r"\d{4}\s*年")
_BREAK = re.compile(r"[，。；、：:（）()\[\]【】\s%]")

_PARTICLES = (
    "高达", "达到", "约为", "超过", "共计", "合计", "实现", "接近",
    "达", "约", "超", "逾", "近", "为", "是", "共", "计", "仅",
)

_MIN_KEY = 3
_MIN_SHARED_SUFFIX = 3
_LOG_TOLERANCE = 0.02


@dataclass(frozen=True)
class Quantity:
    """One money value found in one document."""

    document_id: str
    metric: str
    value: Decimal
    literal: str
    span: tuple[int, int]


@dataclass(frozen=True)
class NumericConflict:
    """Two documents that disagree about the same metric by a power of ten."""

    metric: str
    lower: Quantity
    higher: Quantity
    magnitude: int

    @property
    def document_ids(self) -> tuple[str, str]:
        return self.lower.document_id, self.higher.document_id

    @property
    def factor(self) -> int:
        return 10**self.magnitude


def _metric_key(text: str, start: int) -> str:
    window = _BREAK.split(text[max(0, start - 18) : start])[-1]
    window = _YEAR.sub("", window)
    changed = True
    while changed:
        changed = False
        for particle in _PARTICLES:
            if window.endswith(particle) and len(window) > len(particle):
                window = window[: -len(particle)]
                changed = True
                break
    return window.strip()


def extract_quantities(document_id: str, text: str) -> list[Quantity]:
    """Return every money quantity in ``text`` that carries a usable metric key."""

    found: list[Quantity] = []
    for match in _QUANTITY.finditer(text):
        start = match.start(1)
        if start and (text[start - 1].isdigit() or text[start - 1] == "."):
            continue
        literal_number, unit = match.group(1), match.group(2)
        try:
            amount = Decimal(literal_number.replace(",", ""))
        except InvalidOperation:
            continue
        metric = _metric_key(text, start)
        if len(metric) < _MIN_KEY:
            continue
        found.append(
            Quantity(
                document_id=document_id,
                metric=metric,
                value=amount * _UNIT_SCALE[unit],
                literal=f"{literal_number}{unit}",
                span=(start, match.end(2)),
            )
        )
    return found


def _common_suffix(left: str, right: str) -> str:
    length = 0
    while length < min(len(left), len(right)) and left[-1 - length] == right[-1 - length]:
        length += 1
    return left[len(left) - length :]


def _cluster_keys(keys: Iterable[str]) -> dict[str, str]:
    """Map each metric key to the shared suffix of its cluster.

    Two keys join the same cluster when their longest common suffix is at least
    ``_MIN_SHARED_SUFFIX`` characters, so "公司销售费用", "年销售费用" and
    "销售费用" all land on "销售费用" while "营业收入" and "归母净利润" stay
    apart.
    """

    ordered = sorted(set(keys))
    parent: dict[str, str] = {key: key for key in ordered}

    def find(key: str) -> str:
        while parent[key] != key:
            key = parent[key]
        return key

    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if len(_common_suffix(left, right)) < _MIN_SHARED_SUFFIX:
                continue
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

    members: dict[str, list[str]] = {}
    for key in ordered:
        members.setdefault(find(key), []).append(key)

    label_of: dict[str, str] = {}
    for group in members.values():
        shared = group[0]
        for other in group[1:]:
            shared = _common_suffix(shared, other)
        if len(shared) < _MIN_SHARED_SUFFIX:
            shared = group[0]
        for key in group:
            label_of[key] = shared
    return label_of


def _magnitude(lower: Decimal, higher: Decimal) -> int | None:
    if lower <= 0 or higher <= lower:
        return None
    order = math.log10(float(higher / lower))
    nearest = round(order)
    if nearest < 1 or abs(order - nearest) > _LOG_TOLERANCE:
        return None
    return nearest


def find_conflicts(documents: Sequence[tuple[str, str]]) -> tuple[NumericConflict, ...]:
    """Report metrics whose value differs by a power of ten across documents."""

    return conflicts_from_quantities(
        [
            quantity
            for document_id, text in documents
            for quantity in extract_quantities(document_id, text)
        ]
    )


def conflicts_from_quantities(
    quantities: Sequence[Quantity],
) -> tuple[NumericConflict, ...]:
    """Same clustering and threshold, applied to quantities that were already extracted.

    The investigation runtime records a numeric ledger while it reads, so the
    audit does not have to re-read (or even keep) the source text.
    """

    if not quantities:
        return ()

    label_of = _cluster_keys(quantity.metric for quantity in quantities)
    grouped: dict[str, list[Quantity]] = {}
    for quantity in quantities:
        grouped.setdefault(label_of[quantity.metric], []).append(quantity)

    conflicts: list[NumericConflict] = []
    seen: set[tuple[str, str, str]] = set()
    for label, members in sorted(grouped.items()):
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                if left.document_id == right.document_id:
                    continue
                low, high = (left, right) if left.value <= right.value else (right, left)
                magnitude = _magnitude(low.value, high.value)
                if magnitude is None:
                    continue
                key = (label, low.document_id, high.document_id)
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append(
                    NumericConflict(metric=label, lower=low, higher=high, magnitude=magnitude)
                )
    return tuple(conflicts)
