class DeterministicIdFactory:
    """Generate stable identifiers for run steps and action attempts."""

    def step_id(self, run_id: str, step_index: int) -> str:
        return f"{run_id}:step:{step_index}"

    def action_id(self, run_id: str, step_id: str, attempt: int) -> str:
        return f"{step_id}:attempt:{attempt}:action"
