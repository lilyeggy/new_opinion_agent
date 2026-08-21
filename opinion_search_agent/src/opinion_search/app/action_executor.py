from opinion_search.domain.opinion.actions import (
    FinishAction,
    OpinionAction,
    ReflectAction,
    ToolAction,
)
from opinion_search.domain.opinion.processor import (
    FinishObservation,
    OpinionObservation,
    ReflectObservation,
    ToolObservation,
)
from opinion_search.runtime.protocols import ActionRequest
from opinion_search.tools.contracts import ToolCall
from opinion_search.tools.executor import ToolExecutor


class OpinionActionExecutor:
    def __init__(self, tool_executor: ToolExecutor) -> None:
        self._tool_executor = tool_executor

    async def execute(
        self,
        request: ActionRequest[OpinionAction],
    ) -> OpinionObservation:
        action = request.action
        if isinstance(action, ToolAction):
            outcome = await self._tool_executor.execute(
                ToolCall(
                    action_id=request.action_id,
                    tool_name=action.tool_name,
                    arguments=action.arguments,
                )
            )
            return ToolObservation(
                action=action.decision_action,
                outcome=outcome,
            )

        if isinstance(action, ReflectAction):
            return ReflectObservation(
                assessment=action.assessment,
                assessed_gap_ids=action.assessed_gap_ids,
            )

        if isinstance(action, FinishAction):
            return FinishObservation(completion_verdict=action.completion_verdict)

        raise TypeError(f"unsupported OpinionSearch action: {type(action)}")
