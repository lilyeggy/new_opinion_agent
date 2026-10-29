from tests.support.opinion.actions import (
    FinishAction,
    OpinionAction,
    ReflectAction,
    ToolAction,
)
from tests.support.opinion.decisions import (
    AgentDecision,
    FinishDecision,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from tests.support.opinion.state import OpinionSearchState
from opinion_search.runtime.completion import CompletionPolicy
from opinion_search.tools.capabilities.web import (
    ReaderArguments,
    SearchArguments,
)


def _search_arguments(
    state: OpinionSearchState,
    query: str,
) -> dict[str, object]:
    """Project the persisted TaskFrame onto provider search options.

    Only the time window and language come from the frame. Domain scope is
    enforced after acquisition by the candidate filter, and `country` and
    `offset` stay unset, so the payload carries no unintended provider filter.
    """
    options: dict[str, str] = {}
    frame = state.task_frame
    if frame is not None:
        scope = frame.temporal_scope
        if scope.is_bounded:
            options["freshness"] = f"{scope.start_date}to{scope.end_date}"
        options["search_lang"] = (
            "zh-hans" if frame.language.startswith("zh") else "en"
        )
    arguments = SearchArguments(query=query, **options)
    return arguments.model_dump(
        mode="json",
        exclude={"country", "offset"},
        exclude_none=True,
    )


class OpinionSearchActionResolver:
    def __init__(
        self,
        completion_policy: CompletionPolicy[
            OpinionSearchState,
            FinishDecision,
        ],
    ) -> None:
        self._completion_policy = completion_policy

    def resolve(
        self,
        state: OpinionSearchState,
        decision: AgentDecision,
    ) -> OpinionAction:
        if isinstance(decision, SearchDecision):
            return ToolAction(
                decision_action="search",
                tool_name="search.web",
                arguments=_search_arguments(state, decision.query),
            )

        if isinstance(decision, ReadDecision):
            arguments = ReaderArguments(url=decision.candidate_source_id)
            return ToolAction(
                decision_action="read",
                tool_name="read.web",
                arguments=arguments.model_dump(mode="json"),
            )

        if isinstance(decision, ReflectDecision):
            return ReflectAction(
                assessment=decision.assessment,
                next_focus=decision.next_focus,
                assessed_gap_ids=tuple(
                    item.gap_id for item in decision.gap_assessments
                ),
            )

        return FinishAction(
            completion_verdict=self._completion_policy.evaluate(
                state,
                decision,
            )
        )
