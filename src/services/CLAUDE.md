# Services Module

## Purpose

Business logic layer that orchestrates operations between API, core, and data layers.

## Architecture

```
services/
├── node_library.py       # Node discovery and categorization
├── workflow_service.py   # Workflow CRUD and NLP building
├── credential_service.py # Encrypted credential management
├── execution_service.py  # Workflow execution orchestration
└── mcp_gateway.py        # Federated MCP server management
```

## Key Patterns

### Service Classes

Each service:
- Takes database session in constructor
- Provides CRUD operations
- Handles authorization (user_id checks)
- Translates between entities and schemas

### Error Handling

Service-specific exceptions:
```python
class WorkflowNotFoundError(WorkflowServiceError): ...
class WorkflowAccessDeniedError(WorkflowServiceError): ...
```

### Dependency Injection

Services are instantiated via FastAPI dependencies:
```python
def get_workflow_service(session: DBSession) -> WorkflowService:
    return WorkflowService(session)
```

## Key Services

### CredentialService

Manages encrypted credentials:
- Encrypts on create/update
- Decrypts only when needed
- User-scoped access control

### WorkflowService

Workflow lifecycle management:
- CRUD with graph validation
- NLP-based workflow building
- Version tracking
- Status transitions

### ExecutionService

Workflow execution lifecycle:
- Create and start executions
- Stream events via SSE
- Track status and results
- Handle cancellation

### MCPGateway

Federated MCP server management:
- Server registry with multiple transports
- User credential injection
- Tool discovery and execution

## Testing

```bash
pytest tests/test_services/ -v
```

## Logging

All services use structured logging:
```python
logger.info(
    "workflow_created",
    workflow_id=workflow.id,
    user_id=user_id,
    node_count=len(graph.nodes),
)
```
