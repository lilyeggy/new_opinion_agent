from opinion_search.domain.opinion.actions import (
    FinishAction,
    OpinionAction,
    ReflectAction,
    ToolAction,
)
from opinion_search.domain.opinion.decisions import (
    AgentDecision,
    FinishDecision,
    ReadDecision,
    ReflectDecision,
    SearchDecision,
)
from opinion_search.domain.opinion.state import OpinionSearchState
from opinion_search.runtime.completion import CompletionPolicy
from opinion_search.tools.capabilities.web import (
    ReaderArguments,
    SearchArguments,
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
            arguments = SearchArguments(query=decision.query)
            return ToolAction(
                decision_action="search",
                tool_name="search.web",
                arguments=arguments.model_dump(mode="json"),
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
