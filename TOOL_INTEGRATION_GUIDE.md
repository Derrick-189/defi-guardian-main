# Adding New Verification Tools to DeFi Guardian

This guide explains how to integrate new formal verification tools into the DeFi Guardian system.

## Overview

DeFi Guardian supports multiple verification tools through a unified parser interface. Each tool converts its raw output into standardized `TraceResult` and `TraceStep` objects that the web portal can display.

## Step 1: Create a Parser Class

Create a new parser class in `web_portal/trace_parsers.py` that inherits from `BaseParser`:

```python
class MyToolParser(BaseParser):
    tool_name = "MYTOOL"

    # Define regex patterns for parsing
    _STEP_PATTERN = re.compile(r'...')
    _VAR_PATTERN = re.compile(r'...')
    _ERROR_PATTERN = re.compile(r'...')

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        # Implementation here
        pass

    def parse_rules(self, log_path: str) -> list[dict]:
        # Parse LTL/property results
        pass
```

## Step 2: Implement Trace Parsing

The `parse_trace()` method should:

1. Read tool output from `log_path`
2. Parse execution steps into `TraceStep` objects
3. Extract variable assignments and track before/after states
4. Identify error/violation steps
5. Return a `TraceResult` with all steps and final variables

See `TRACE_SCHEMA.md` for the required `TraceStep` fields.

## Step 3: Implement Rule/Property Parsing

The `parse_rules()` method should:

1. Parse tool output for property verification results
2. Return a list of rule dictionaries with:
   - `name`: Property name
   - `status`: "VERIFIED", "VIOLATED", or "TIMEOUT"
   - `formula`: LTL formula (if applicable)
   - `errors`: Number of counterexamples found

## Step 4: Register the Parser

Add your parser to the parser registry in the main application:

```python
# In web_portal/app.py or wherever parsers are registered
from .trace_parsers import MyToolParser

PARSER_REGISTRY = {
    'spin': SpinParser(),
    'prusti': PrustiParser(),
    'mytool': MyToolParser(),  # Add your parser here
}
```

## Step 5: Update Tool Detection

Update the tool detection logic to recognize your tool's output format:

```python
# In the verification runner or API endpoint
def detect_tool(output: str) -> str:
    if 'mytool' in output.lower():
        return 'mytool'
    # ... other detections
```

## Step 6: Test the Integration

1. Run your tool on a test contract
2. Verify the parser produces valid `TraceResult` JSON
3. Test the web portal displays the trace correctly
4. Check that variable diffs and source locations work

## Best Practices

- **Standardize field names**: Use the exact field names from `TRACE_SCHEMA.md`
- **Handle errors gracefully**: Return partial results rather than failing completely
- **Preserve raw output**: Include original tool output for debugging
- **Test edge cases**: Empty traces, single steps, variable-only changes
- **Follow naming conventions**: Use lowercase tool names, descriptive method names

## Example: Simple Parser

```python
class SimpleParser(BaseParser):
    tool_name = "SIMPLE"

    def parse_trace(self, log_path: str, report_path: str = "") -> Optional[TraceResult]:
        with open(log_path) as f:
            lines = f.readlines()

        steps = []
        for i, line in enumerate(lines):
            step = TraceStep(
                step=i + 1,
                action=line.strip(),
                source=f"line {i + 1}",
                is_error="error" in line.lower()
            )
            steps.append(step)

        return TraceResult(
            steps=steps,
            final_variables={},
            error_message="",
            tool="SIMPLE"
        )
```

## Debugging Tips

- Use the web portal's "Raw Output" tab to see original tool output
- Add debug prints to your parser methods
- Test with small, controlled inputs first
- Check browser console for JavaScript errors in the counterexample viewer