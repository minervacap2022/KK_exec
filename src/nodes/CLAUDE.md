# Nodes Module

## Purpose

Workflow node definitions with a consistent interface for execution.

## Architecture

```
nodes/
├── base.py          # BaseNode abstract class
├── registry.py      # Node registration and discovery
├── tools/           # Tool nodes (no auth)
│   ├── calculator.py
│   ├── text_processor.py
│   └── json_transformer.py
├── apis/            # API nodes (API key auth)
│   ├── openai.py
│   ├── anthropic.py
│   └── weather.py
└── mcp/             # MCP nodes (user OAuth/token)
    ├── slack.py
    ├── github.py
    └── filesystem.py
```

## Key Patterns

### BaseNode Interface

All nodes implement:
```python
class MyNode(BaseNode[InputType, OutputType]):
    def get_definition(self) -> NodeDefinition:
        return NodeDefinition(...)

    async def execute(
        self,
        input_data: InputType,
        context: NodeContext,
    ) -> OutputType:
        # Implementation
```

### Node Categories

| Category | Auth Required | Examples |
|----------|--------------|----------|
| TOOL | None | Calculator, Text Processor |
| API | API Key | OpenAI, Anthropic |
| MCP | User OAuth/Token | Slack, GitHub |

### Execution Lifecycle

1. `validate_input()` - Validate and transform input
2. `pre_execute()` - Setup hook
3. `execute()` - Main logic
4. `post_execute()` - Cleanup hook
5. `validate_output()` - Validate and transform output

### NodeContext

Provides execution context:
```python
@dataclass
class NodeContext:
    user_id: str
    execution_id: str
    credentials: dict[str, Any]
    variables: dict[str, Any]
    trace_id: str | None
```

## Adding New Nodes

1. Create node file in appropriate category folder
2. Implement `BaseNode` interface
3. Register in `registry.py`
4. Add to `node_library.py` builtin nodes
5. Write tests

## Testing

```bash
pytest tests/test_nodes/ -v
```

## Security

- Nodes receive credentials via `NodeContext`
- Never log credential values
- Validate all external inputs
- Use timeouts for network calls
