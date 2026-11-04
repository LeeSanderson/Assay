"""Probe (wayfinder ticket 57): link mounted environment tools onto PATH in setup().

Throwaway; never merged. `ToolsProbeOracle` is Harbor's oracle plus the link
step, at no model cost. `ToolsProbeClaude` is Assay's agent class plus the link
step, after the seed fire, as the proposal puts it.
"""

from pathlib import Path

from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

from instruments.agent import InstrumentedClaudeCode

PROBE = Path(__file__).resolve().parent / "tools-probe.sh"
TOOLS_DIR = "/opt/assay-tools"
# No -f: a tool whose name is already in /usr/local/bin stops setup.
LINK_TOOLS = (
    f'for f in {TOOLS_DIR}/bin/*; do ln -s "$f" /usr/local/bin/ || exit 1; done; '
    f"ls -l /usr/local/bin > /logs/agent/links-after-setup.txt"
)


async def link_tools(environment: BaseEnvironment) -> None:
    result = await environment.exec(command=LINK_TOOLS, user="root")
    if result.return_code != 0:
        raise RuntimeError(f"linking the tools failed: {result.stdout} {result.stderr}")


class ToolsProbeOracle(BaseAgent):
    """No model: link the tools, then run the task's solution/solve.sh probe
    through Harbor's exec (non-login `bash -c`). Harbor gives the task paths
    only to the oracle it builds by name, so this reads solve.sh from a fixed
    copy instead of subclassing `OracleAgent`. The gold solution is not
    applied, so the reward is 0."""

    @staticmethod
    def name() -> str:
        return "tools-probe"

    def version(self) -> str | None:
        return "0"

    async def setup(self, environment: BaseEnvironment) -> None:
        await link_tools(environment)

    async def run(self, instruction: str, environment: BaseEnvironment,
                  context: AgentContext) -> None:
        result = await environment.exec(command=PROBE.read_text(encoding="utf-8"))
        (self.logs_dir / "probe-exec.txt").write_text(
            f"exit {result.return_code}\n{result.stdout}\n{result.stderr}\n", encoding="utf-8")


class ToolsProbeClaude(InstrumentedClaudeCode):
    async def setup(self, environment: BaseEnvironment) -> None:
        await super().setup(environment)  # instruments, then the seed fire
        await link_tools(environment)
