from __future__ import annotations
from typing import Dict, Any, Tuple
from pathlib import Path
import yaml
from .schema import OrchestratorRecipe, FixedAgentRecipe, MCPBinding, ToolMethod, Step
from .storage import save_yaml
from core.agents.fixed.registry import FIXED_AGENTS

def _tool_binding_from_call(call: str) -> Tuple[str, str]:
    # "qsys_api.load_snapshot" -> ("qsys_api","load_snapshot")
    tool, method = call.split(".", 1)
    return tool, method

def compile_sop_to_bundle(sop_text: str, ctx: Dict[str, Any]) -> Dict[str, Path]:
    """
    1) Parse SOP (LLM or rule-based) to produce an OrchestratorRecipe (steps_by_agent).
    2) From orchestrator recipe, derive bounded FixedAgentRecipe for each agent mentioned.
    3) Persist orchestrator.yaml and fixed recipes under data/recipes/.
    Returns dict of artifact paths.
    """
    # --- Step 1: Convert SOP prose to a draft orchestrator model (LLM-backed or heuristics).
    orch = _sop_to_orchestrator_model(sop_text, ctx)

    # --- Step 2: Derive fixed agent recipes from orchestrator steps.
    fixed_recipes: Dict[str, FixedAgentRecipe] = {}
    for agent_name, steps in orch.steps_by_agent.items():
        # Gather tool allow-list
        tool_methods: Dict[str, Dict[str, ToolMethod]] = {}
        fixed_steps: list[Step] = []

        for s in steps:
            fixed_steps.append(s)
            if s.call and s.kind in ("call","verify"):
                tool, method = _tool_binding_from_call(s.call) if "." in s.call else (s.call, "")
                if tool not in tool_methods:
                    tool_methods[tool] = {}
                # conservative default risk; approvals from step
                risk = "medium" if s.approvals else "low"
                tool_methods[tool][method or ""] = ToolMethod(
                    name=method or s.call, risk=risk,
                    approval=s.approvals[0] if s.approvals else None,
                )

        mcp = [MCPBinding(tool=t, allow=list(methods.values())) for t, methods in tool_methods.items()]
        fixed = FixedAgentRecipe(
            agent_name=agent_name,
            version=orch.version,
            scope={"profiles": orch.profiles},
            policy_tags=["orchestrated","ipavl"],
            mcp=mcp,
            steps=fixed_steps,
            outcomes={"success": "verify_all_pass", "failure": "halt_and_escalate"}
        )
        fixed_recipes[agent_name] = fixed

    # --- Step 3: Persist artifacts
    out: Dict[str, Path] = {}
    orch_path = save_yaml(orch, subdir="recipes/orchestrator", filename=f"{slugify(orch.name)}.yaml")
    out["orchestrator"] = orch_path
    for agent, rec in fixed_recipes.items():
        p = save_yaml(rec, subdir="recipes/fixed", filename=f"{slugify(orch.name)}__{agent}.yaml")
        out[agent] = p
    return out

# ---- helpers ---------------------------------------------------------------

def _sop_to_orchestrator_model(sop_text: str, ctx: Dict[str, Any]) -> OrchestratorRecipe:
    """
    Minimal, deterministic extractor.
    In production, replace with your LLM routine constrained by JSON schema.
    """
    # toy heuristic example; replace with your current `from_sop` logic wired to schema
    name = ctx.get("name") or "Workflow_From_SOP"
    steps_by_agent = {
        "BaselineAgent": [Step(id="policy_window", kind="call", call="policy_check", args={"windows":["06:00-22:00"]})],
        "EventFormAgent": [Step(id="normalize_form", kind="call", call="parse_form", args={"schema":"event-intake-v2"})],
        "IntakeAgent": [
            Step(id="read_zoom", kind="call", call="zoom_admin.get_room_health", args={"room":"$room"}, evidence=["json:zoom"]),
            Step(id="qsys_rx", kind="call", call="qsys_api.component_state", args={"room":"$room","component":"HDMI_RX_1"})
        ],
        "PlanAgent": [Step(id="choose_triage", kind="call", call="choose_recipe", args={"candidate":"Support_Triage"})],
        "ActAgent": [Step(id="reload_edid", kind="call", call="qsys_api.load_snapshot", args={"room":"$room","snapshot":"HDMI_EDID_Reload"}, approvals=["Support_L2"])],
        "VerifyAgent": [
            Step(id="lock_check", kind="verify", call="assert", args={"hdmi_signal_lock":{"room":"$room","input":"RX1","expect":True}}),
            Step(id="snap", kind="call", call="collect_evidence", args={"target":"MatrixStatus"})
        ],
        "LearnAgent": [Step(id="kb_pub", kind="call", call="kb_publish", args={"template":"HDMI-Lock-Recovery","tags":["HDMI","EDID","QSYS"]})]
    }
    return OrchestratorRecipe(
        name=name,
        description="Derived from SOP",
        agents=[a for a in FIXED_AGENTS if a in steps_by_agent] + [k for k in steps_by_agent if k not in FIXED_AGENTS],
        mcp_required=["zoom_admin","qsys_api","dante_ctrl"],
        profiles={"room_selector": "B12-Conf-*"},
        steps_by_agent=steps_by_agent,
        approvals={"ActAgent": ["Support_L2"]},
    )

def slugify(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")
