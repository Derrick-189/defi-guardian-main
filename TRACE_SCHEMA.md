# DeFi Guardian Trace Schema
# Standardized JSON schema for verification tool trace data
# Used by web portal counterexample viewer and desktop app

## TraceResult
Top-level container for a verification run's trace data.

```json
{
  "steps": [TraceStep],
  "final_variables": {"var_name": "value"},
  "error_message": "string",
  "tool": "SPIN|Prusti|Kani|etc"
}
```

## TraceStep
Individual step in the execution trace.

```json
{
  "step": 1,
  "step_number": 1,  // Alias for compatibility
  "proc": "process_name",
  "line": 123,
  "file": "contract.sol",
  "source": "contract.sol: line 123",
  "state": "state_description",
  "action": "step_description",
  "variables": {"var_name": "current_value"},
  "variables_before": {"var_name": "previous_value"},
  "variables_after": {"var_name": "new_value"},
  "updates": {"var_name": "changed_value"},
  "is_error": false
}
```

## Field Requirements
- `step`: Required integer step number (1-based)
- `action`: Required string description of the step
- `variables_before`/`variables_after`: Required for diff display
- `source`: Recommended for source location display
- `file`/`line`: Optional but recommended for IDE integration
- `is_error`: Required boolean for error highlighting

## Parser Implementation Guide
1. Extract step number, action, and process name
2. Parse variable assignments and track before/after states
3. Extract file/line information from tool output
4. Build source string as "file: line X"
5. Mark error steps based on tool-specific patterns
6. Return TraceResult with all steps and final variables