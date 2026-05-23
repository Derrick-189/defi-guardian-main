"""
Base class for all tool-specific trace parsers.
Each tool (SPIN, Coq, Lean, etc.) implements this interface to normalize trace output.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from events import ExecutionTrace, TraceStep, LTLProperty


class TraceParser(ABC):
    """Abstract base class for tool-specific trace parsers"""

    @abstractmethod
    def parse_rules(self, log_path: str) -> List[Dict]:
        """
        Parse rules/properties/theorems from verification log.

        Returns:
            List of dicts with keys: name, status, formula, errors, tool_specific
            Example: [
                {
                    'name': 'safety_no_overflow',
                    'status': 'PASS',
                    'formula': '[] (amount >= 0 && amount <= 1000000)',
                    'errors': 0
                },
                ...
            ]
        """
        pass

    @abstractmethod
    def parse_trace(
        self, log_path: str, trail_path: Optional[str] = None
    ) -> ExecutionTrace:
        """
        Parse execution trace from log or trail file.

        Returns:
            ExecutionTrace object with steps and metadata
        """
        pass

    def get_recommendations(self, status: str) -> List[str]:
        """Override in subclass to provide tool-specific recommendations"""
        return [
            "Review the verification log for specific error messages",
            "Check tool installation and version compatibility",
        ]


def get_parser(tool_name: str) -> Optional[TraceParser]:
    """Factory method to get appropriate parser for a tool"""
    tool = tool_name.upper() if tool_name else ""

    if tool == "SPIN":
        from trace_parsers.spin_parser import SPINParser

        return SPINParser()
    elif tool == "COQ":
        from trace_parsers.coq_parser import CoqParser

        return CoqParser()
    elif tool == "LEAN":
        from trace_parsers.lean_parser import LeanParser

        return LeanParser()
    elif tool == "CERTORA":
        from trace_parsers.certora_parser import CertoraParser

        return CertoraParser()
    elif tool == "KANI":
        from trace_parsers.rust_parser import RustParser

        return RustParser("KANI")
    elif tool == "PRUSTI":
        from trace_parsers.rust_parser import RustParser

        return RustParser("PRUSTI")
    elif tool == "CREUSOT":
        from trace_parsers.rust_parser import RustParser

        return RustParser("CREUSOT")
    elif tool == "VERUS":
        from trace_parsers.verus_parser import VerusParser

        return VerusParser()
    else:
        return None
