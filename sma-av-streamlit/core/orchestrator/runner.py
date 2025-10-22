from pathlib import Path
import yaml

def load_orchestrator(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))

def bound_fixed_recipes(orch: dict) -> dict[str, dict]:
    name_slug = orch["name"].lower().replace(" ", "-")
    out = {}
    for agent in orch["agents"]:
        fp = Path(f"data/recipes/fixed/{name_slug}__{agent}.yaml")
        out[agent] = yaml.safe_load(fp.read_text(encoding="utf-8"))
    return out

def run_orchestrated_workflow(orch_path: Path, context: dict):
    orch = load_orchestrator(orch_path)
    fixed = bound_fixed_recipes(orch)

    # Sequence: Baseline → EventForm → Intake → Plan → Act → Verify → Learn
    order = ["BaselineAgent","EventFormAgent","IntakeAgent","PlanAgent","ActAgent","VerifyAgent","LearnAgent"]
    state = {"context": context, "evidence": [], "verdicts": []}

    for agent in order:
        if agent not in fixed: 
            continue
        state = _execute_fixed_agent(fixed[agent], state)
        if agent == "VerifyAgent" and state.get("failed"):
            break  # stop early if verify fails

    return state
