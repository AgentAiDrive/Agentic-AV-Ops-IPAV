from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Any

Risk = Literal["low", "medium", "high"]

@dataclass
class ToolMethod:
    name: str
    risk: Risk = "low"
    approval: Optional[str] = None
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)

@dataclass
class MCPBinding:
    tool: str
    allow: List[ToolMethod]  # explicit methods allowed

@dataclass
class Step:
    id: str
    kind: Literal["call","verify","pause","note"] = "call"
    call: Optional[str] = None          # e.g., "qsys_api.load_snapshot"
    args: Dict[str, Any] = field(default_factory=dict)
    approvals: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    expect: Dict[str, Any] = field(default_factory=dict)

@dataclass
class FixedAgentRecipe:
    agent_name: str                   # e.g., "IntakeAgent"
    version: str = "1.0"
    scope: Dict[str, Any] = field(default_factory=dict)
    policy_tags: List[str] = field(default_factory=list)
    mcp: List[MCPBinding] = field(default_factory=list)
    steps: List[Step] = field(default_factory=list)
    outcomes: Dict[str, Any] = field(default_factory=dict)

@dataclass
class OrchestratorRecipe:
    name: str
    version: str = "1.0"
    description: str = ""
    roles: Dict[str, str] = field(default_factory=dict)  # role -> description
    agents: List[str] = field(default_factory=list)      # fixed agents participating
    mcp_required: List[str] = field(default_factory=list)
    profiles: Dict[str, Any] = field(default_factory=dict)  # room/event profiles
    steps_by_agent: Dict[str, List[Step]] = field(default_factory=dict)
    approvals: Dict[str, List[str]] = field(default_factory=dict) # phase->roles
