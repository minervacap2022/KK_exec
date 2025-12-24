# API Module

## Purpose

FastAPI routes and dependency injection for HTTP API.

## Architecture

```
api/
├── deps.py              # Dependency injection (DB, auth, services)
└── routes/
    ├── workflows.py     # Workflow CRUD + NLP building
    ├── nodes.py         # Node catalog endpoints
    ├── credentials.py   # Credential management
    ├── executions.py    # Execution + SSE streaming
    └── mcp.py           # MCP server management
```

## Key Patterns

### Dependency Injection

```python
@router.get("")
async def list_workflows(
    user: CurrentUser,           # Authenticated user
    service: WorkflowServiceDep, # Injected service
) -> list[WorkflowRead]:
    return await service.list(user_id=user.id)
```

### Authentication

JWT-based authentication:
- `CurrentUser`: Requires valid token
- `OptionalUser`: Token optional (for public endpoints)

### Error Handling

Service exceptions → HTTP responses:
```python
except WorkflowNotFoundError as e:
    raise HTTPException(status_code=404, detail=str(e))
```

### SSE Streaming

Executions stream via SSE:
```python
@router.get("/{id}/stream")
async def stream_execution(...) -> EventSourceResponse:
    async def event_generator():
        async for event in service.execute(id, user.id):
            yield {"event": event.type, "data": json.dumps(event.to_dict())}
    return EventSourceResponse(event_generator())
```

## Endpoints

| Path | Method | Description |
|------|--------|-------------|
| `/api/v1/workflows` | GET | List workflows |
| `/api/v1/workflows` | POST | Create workflow |
| `/api/v1/workflows/build` | POST | Build from NLP |
| `/api/v1/workflows/{id}` | GET/PUT/DELETE | CRUD |
| `/api/v1/nodes` | GET | List nodes |
| `/api/v1/credentials` | GET/POST | CRUD |
| `/api/v1/executions` | POST | Start execution |
| `/api/v1/executions/{id}/stream` | GET | SSE stream |
| `/api/v1/mcp/servers` | GET | List MCP servers |

## Testing

```bash
pytest tests/test_api/ -v
```

## Security

- All endpoints require authentication except:
  - `GET /health`
  - `GET /ready`
  - `GET /api/v1/nodes` (optional auth)
- Rate limiting configured in middleware
- CORS origins from settings
