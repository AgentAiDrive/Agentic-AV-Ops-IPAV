FIXED_AGENTS = [
    "BaselineAgent",        # safety + policy preflight (risk windows, RBAC, secrets)
    "EventFormAgent",       # normalizes event form into canonical intake
    "IntakeAgent",          # gathers & normalizes context/telemetry
    "PlanAgent",            # expands recipe + gates + parameters
    "ActAgent",             # executes bounded MCP calls with audit & rollback
    "VerifyAgent",          # checks outcomes, collects evidence
    "LearnAgent",           # writes SNOW KB, updates dashboards
]

# Static capabilities per fixed agent (non-editable)
CAPS = {
    "BaselineAgent": dict(allows=["policy_check","time_window_check","role_check"]),
    "EventFormAgent": dict(allows=["parse_form","normalize_payload"]),
    "IntakeAgent": dict(allows=["read_zoom","qsys_state","dante_routes","snmp_read"]),
    "PlanAgent": dict(allows=["choose_recipe","insert_approvals","expand_params"]),
    "ActAgent": dict(allows=["mcp_call","rollback","redact"]),
    "VerifyAgent": dict(allows=["assert","collect_evidence","kpi_record"]),
    "LearnAgent": dict(allows=["kb_publish","cmdb_link","dash_update"]),
}
