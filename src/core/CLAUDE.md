# Core Module

## Purpose

Pure business logic and algorithms with no side effects. This is the computational heart of the system.

## Architecture

```
core/
├── encryption.py        # Fernet credential encryption
├── execution_engine.py  # LangGraph workflow executor
├── workflow_builder.py  # NLP → workflow graph
└── node_selector.py     # Intelligent node selection
```

## Key Patterns

### Pure Functions

All core logic should be pure:
- No database access
- No network calls (except LLM via injected clients)
- Explicit inputs and outputs
- Deterministic given same inputs + seed

### Dependency Injection

External dependencies are injected:
```python
class WorkflowExecutionEngine:
    def __init__(self, model: str | None = None):
        self._llm = ChatOpenAI(...)  # Configured from settings
```

### Error Handling

Custom exception hierarchy:
- `EncryptionError` / `DecryptionError`
- `ExecutionError` / `NodeExecutionError`
- `WorkflowBuilderError`

All exceptions include error codes for programmatic handling.

## Key Components

### CredentialEncryption

Fernet-based symmetric encryption for credentials:
- 32-byte url-safe base64 keys
- Authenticated encryption (AES-128-CBC + HMAC-SHA256)
- Key rotation support

### WorkflowExecutionEngine

LangGraph-based executor:
- StateGraph for workflow execution
- Streaming via `astream()` with updates
- Tool execution via ToolNode
- Checkpointing for resume

### WorkflowBuilder

NLP-driven workflow generation:
- Receives: prompt + node catalog + credentials
- Outputs: complete WorkflowGraph
- Uses ReAct-style prompting

## Testing

```bash
pytest tests/test_core/ -v
pytest tests/test_core/test_encryption.py --hypothesis-show-statistics
```

## Performance

- Execution engine uses async throughout
- Streaming reduces latency for long workflows
- Node selection uses keyword matching (O(n) nodes)
