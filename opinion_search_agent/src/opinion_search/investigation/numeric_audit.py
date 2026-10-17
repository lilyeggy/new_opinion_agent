"""Turn the numeric ledger into the disagreements a report should show.

The provenance guard answers "does this number have a source?".  It cannot ask
"do the sources that report this metric agree?" - so a figure inflated by a
factor of ten can sit next to the accurate one with nothing noticing.  The
ledger collected while reading (``State.numeric_ledger``) makes that possible
without re-reading or keeping the source text.

The audit is deliberately conservative.  It only compares currency magnitudes,
only across different documents, and only reports a group whose members differ
by a whole power of ten.  It never decides which value is right: the report
lists both values and the documents that carried them, and a human looks.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Sequence

from opinion_search.domain.investigation.models import State
from opinion_search.domain.numeric import NumericConflict, Quantity, conflicts_from_quantities


def quantities(state: State) -> list[Quantity]:
    """Rebuild the quantities the run has seen, skipping values that do not parse."""

    found: list[Quantity] = []
    for item in state.numeric_ledger:
        try:
            value = Decimal(item.value)
        except (InvalidOperation, ValueError):
            continue
        found.append(
            Quantity(
                document_id=item.version_id,
                metric=item.metric,
                value=value,
                literal=item.literal,
                span=(item.start, item.end),
            )
        )
    return found


def conflicts(state: State) -> tuple[NumericConflict, ...]:
    """Return the metrics whose value differs by a power of ten across documents."""

    unique: dict[tuple[str, str, str], NumericConflict] = {}
    for conflict in conflicts_from_quantities(quantities(state)):
        # Two documents can carry the low value and two can carry the high one.
        # The reader only needs one pointer per disagreement.
        unique.setdefault(
            (conflict.metric, conflict.lower.literal, conflict.higher.literal), conflict
        )
    return tuple(unique.values())


def describe(state: State, found: Sequence[NumericConflict]) -> list[dict[str, Any]]:
    """Render conflicts as report rows, naming both documents and both values."""

    sources = {source.version_id: source for source in state.sources}

    def side(quantity: Quantity) -> dict[str, str]:
        source = sources.get(quantity.document_id)
        return {
            "version_id": quantity.document_id,
            "value": quantity.literal,
            "title": source.title if source is not None else "",
            "url": source.url if source is not None else "",
        }

    return [
        {"metric": conflict.metric, "factor": conflict.factor,
         "lower": side(conflict.lower), "higher": side(conflict.higher)}
        for conflict in found
    ]
