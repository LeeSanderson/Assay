"""`InstrumentedClaudeCode` with no model: for the slow job-file check.

It keeps `setup()` (instrument upload, seed fire, `instruments.json`) and drops
the parts that need the network or a model: the Claude Code install and the
agent run. Harbor loads it through `import_path`, like the real class.
"""

from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from instruments.agent import InstrumentedClaudeCode


class NoModelInstrumentedClaudeCode(InstrumentedClaudeCode):
    async def install(self, environment: BaseEnvironment) -> None:
        pass

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        pass
