"""
Unified event schemas for real-time verification status broadcasts.
These events flow from desktop_app.py → /api/events/emit → WebSocket → dashboards.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from datetime import datetime
from enum import Enum
import json


class ToolStatus(Enum):
    """Verification result status"""
    PASS = "PASS"
    FAIL = "FAIL"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    RUNNING = "RUNNING"

    def to_dict(self):
        return {"status": self.value}


class ToolName(Enum):
    """All supported verification tools"""
    SPIN = "SPIN"
    COQ = "COQ"
    LEAN = "LEAN"
    CERTORA = "CERTORA"
    KANI = "KANI"
    PRUSTI = "PRUSTI"
    CREUSOT = "CREUSOT"
    VERUS = "VERUS"

    @staticmethod
    def all_tools() -> List[str]:
        return [t.value for t in ToolName]

    @staticmethod
    def is_rust_tool(tool: str) -> bool:
        return tool.upper() in ("KANI", "PRUSTI", "CREUSOT", "VERUS")


@dataclass
class LTLProperty:
    """Represents a single LTL property or theorem"""
    name: str
    status: str  # "PASS", "FAIL", "TIMEOUT"
    formula: str
    errors: int = 0
    tool_specific: Optional[Dict] = None

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict) -> "LTLProperty":
        return LTLProperty(**data)


@dataclass
class TraceStep:
    """Single step in an execution trace"""
    step_num: int
    proc: str  # Process/thread name
    action: str  # Action taken (e.g., "amount=10")
    state: str  # State ID
    line: str  # Source line number
    file: str  # Source file
    variables: Dict = field(default_factory=dict)  # All variables at this step
    variables_before: Dict = field(default_factory=dict)  # Variables before the step
    variables_after: Dict = field(default_factory=dict)  # Variables after the step
    updates: Dict = field(default_factory=dict)  # Which variables changed
    is_error: bool = False

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(data: Dict) -> "TraceStep":
        return TraceStep(**data)


@dataclass
class ExecutionTrace:
    """Complete execution trace from verification run"""
    steps: List[TraceStep] = field(default_factory=list)
    final_variables: Dict = field(default_factory=dict)
    final_state: str = ""
    error_line: int = -1
    error_message: Optional[str] = None

    def to_dict(self):
        return {
            "steps": [s.to_dict() for s in self.steps],
            "final_variables": self.final_variables,
            "final_state": self.final_state,
            "error_line": self.error_line,
            "error_message": self.error_message,
        }

    @staticmethod
    def from_dict(data: Dict) -> "ExecutionTrace":
        steps = [TraceStep.from_dict(s) for s in data.get("steps", [])]
        return ExecutionTrace(
            steps=steps,
            final_variables=data.get("final_variables", {}),
            final_state=data.get("final_state", ""),
            error_line=data.get("error_line", -1),
            error_message=data.get("error_message"),
        )


@dataclass
class VerificationCompleteEvent:
    """
    Unified event emitted by desktop app when tool completes verification.
    Broadcast via WebSocket to all connected dashboards.
    """
    audit_id: str  # Unique run ID
    tool: str  # Tool name (SPIN, COQ, LEAN, etc.)
    filename: str  # Contract/file being verified
    timestamp: datetime  # When verification completed
    status: str  # PASS, FAIL, TIMEOUT, ERROR

    # Verification results
    ltl_properties: List[LTLProperty] = field(default_factory=list)
    trace_data: Optional[ExecutionTrace] = None
    state_graph: Optional[Dict] = None

    # Diagnostic info
    recommendations: Optional[List[str]] = None
    error_msg: Optional[str] = None
    log_path: Optional[str] = None
    trace_path: Optional[str] = None

    # Statistics
    states_explored: int = 0
    transitions: int = 0
    depth: int = 0

    def to_json(self) -> str:
        """Serialize to JSON for WebSocket transmission"""
        data = {
            "audit_id": self.audit_id,
            "tool": self.tool,
            "filename": self.filename,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "ltl_properties": [p.to_dict() for p in self.ltl_properties],
            "trace_data": self.trace_data.to_dict() if self.trace_data else None,
            "state_graph": self.state_graph,
            "recommendations": self.recommendations,
            "error_msg": self.error_msg,
            "log_path": self.log_path,
            "trace_path": self.trace_path,
            "states_explored": self.states_explored,
            "transitions": self.transitions,
            "depth": self.depth,
        }
        return json.dumps(data, default=str)

    @staticmethod
    def from_json(json_str: str) -> "VerificationCompleteEvent":
        """Deserialize from JSON"""
        data = json.loads(json_str)
        return VerificationCompleteEvent(
            audit_id=data["audit_id"],
            tool=data["tool"],
            filename=data["filename"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            status=data["status"],
            ltl_properties=[
                LTLProperty.from_dict(p) for p in data.get("ltl_properties", [])
            ],
            trace_data=(
                ExecutionTrace.from_dict(data["trace_data"])
                if data.get("trace_data")
                else None
            ),
            state_graph=data.get("state_graph"),
            recommendations=data.get("recommendations"),
            error_msg=data.get("error_msg"),
            log_path=data.get("log_path"),
            trace_path=data.get("trace_path"),
            states_explored=data.get("states_explored", 0),
            transitions=data.get("transitions", 0),
            depth=data.get("depth", 0),
        )


@dataclass
class VerificationProgressEvent:
    """Event emitted as verification is running (optional, for future use)"""
    audit_id: str
    tool: str
    filename: str
    timestamp: datetime
    status: str = "RUNNING"
    progress_percent: int = 0
    current_step: Optional[str] = None

    def to_json(self) -> str:
        data = {
            "audit_id": self.audit_id,
            "tool": self.tool,
            "filename": self.filename,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "progress_percent": self.progress_percent,
            "current_step": self.current_step,
        }
        return json.dumps(data, default=str)
