"""Scaffold templates for ``replayt init --template``."""

from __future__ import annotations

TEMPLATE_BASIC = '''\
"""Scaffolded replayt workflow — run with: replayt run workflow.py --inputs-json '{}' """

from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("my_workflow", version="1")
wf.set_initial("hello")


@wf.step("hello")
def hello(ctx):
    ctx.set("message", "ready")
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    r = runner.run(inputs={})
    print(r.run_id, r.status)
'''

TEMPLATE_APPROVAL = '''\
"""Workflow with an approval gate — run, then approve with: replayt resume workflow.py RUN_ID --approval review"""

from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("approval_workflow", version="1")
wf.set_initial("evaluate")
wf.note_transition("evaluate", "finalize")

@wf.step("evaluate")
def evaluate(ctx):
    ctx.set("draft", "Needs human sign-off")
    if ctx.is_approved("review"):
        return "finalize"
    ctx.request_approval("review", summary="Please review the draft before finalising.")

@wf.step("finalize")
def finalize(ctx):
    ctx.set("result", "approved and finalised")
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    r = runner.run(inputs={})
    print(r.run_id, r.status)
'''

TEMPLATE_TOOL_USING = '''\
"""Workflow that registers and uses typed tools — run with: replayt run workflow.py --inputs-json '{}' """

from pathlib import Path

from replayt import LogMode, Runner, Workflow
from replayt.persistence import JSONLStore

wf = Workflow("tool_workflow", version="1")
wf.set_initial("use_tool")


def add(a: int, b: int) -> int:
    return a + b


@wf.step("use_tool")
def use_tool(ctx):
    ctx.tools.register(add)
    result = ctx.tools.call("add", {"a": 2, "b": 3})
    ctx.set("sum", result)
    return None


if __name__ == "__main__":
    runner = Runner(wf, JSONLStore(Path(".replayt/runs")), log_mode=LogMode.redacted)
    r = runner.run(inputs={})
    print(r.run_id, r.status)
'''

TEMPLATE_YAML = '''\
# Declarative YAML workflow — run with: replayt run workflow.yaml
# Requires: pip install replayt[yaml]

name: yaml_workflow
version: "1"
initial: greet

steps:
  greet:
    set:
      message: "Hello from YAML workflow"
    transition: process

  process:
    set:
      status: "processed"
    transition: done

  done:
    set:
      complete: true
'''

TEMPLATES: dict[str, tuple[str, str]] = {
    "basic": (TEMPLATE_BASIC, "workflow.py"),
    "approval": (TEMPLATE_APPROVAL, "workflow.py"),
    "tool-using": (TEMPLATE_TOOL_USING, "workflow.py"),
    "yaml": (TEMPLATE_YAML, "workflow.yaml"),
}
