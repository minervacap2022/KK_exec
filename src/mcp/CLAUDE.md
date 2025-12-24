# MCP Module

## Purpose

Model Context Protocol integration for federated MCP server management.

## Architecture

```
mcp/
├── server_registry.py    # MCP server configurations
├── transports.py         # Transport adapters (stdio, http, sse)
└── credential_injector.py # User credential injection
```

## Key Patterns

### Federated Architecture

Each integration has its own MCP server:
- Slack → `mcp.slack.com`
- GitHub → `gitmcp.io`
- Filesystem → Local stdio process

### Transport Types

| Transport | Use Case | Config |
|-----------|----------|--------|
| `stdio` | Local CLI tools | command, args |
| `streamable_http` | Remote servers | url, headers |
| `sse` | Real-time streaming | url, headers |

### Credential Injection

User credentials are injected based on type:
```python
CREDENTIAL_STRATEGIES = {
    "slack_oauth": {"method": "bearer", "token_field": "access_token"},
    "github_token": {"method": "bearer", "token_field": "token"},
    "anthropic_api_key": {"method": "header", "header_name": "x-api-key"},
}
```

## Components

### MCPServerRegistry

Maintains server configurations:
```python
registry = MCPServerRegistry()
slack = registry.get("slack")
available = registry.list_available(user_credentials)
```

### MCPTransport

Abstract transport interface:
- `connect()` - Establish connection
- `disconnect()` - Close connection
- `send(message)` - Send and receive

### CredentialInjector

Prepares credentials for transport:
```python
injector = CredentialInjector()
creds = injector.prepare(server_config, user_credential)
# creds.headers, creds.params, creds.env
```

## Adding New MCP Servers

1. Add configuration to `server_registry.py`
2. Add credential strategy to `credential_injector.py`
3. Add corresponding node in `nodes/mcp/`
4. Test connection and tools

## Testing

```bash
pytest tests/test_integration/test_mcp_gateway.py -v
```

## Error Handling

- `MCPConnectionError` - Connection failed
- `MCPTimeoutError` - Operation timed out
- `MCPToolError` - Tool execution failed
