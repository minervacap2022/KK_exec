# CLAUDE.md - MCP Workflow Automation System

**This document is the authoritative architecture reference and development standards for this project.**

## Project Overview

MCP-based workflow automation system with:
- Python/FastAPI backend
- Federated MCP server architecture
- User-specific credential management
- NLP-driven workflow generation
- LangGraph execution engine

## Hard Requirements

**ABSOLUTE - NO EXCEPTIONS:**
- **No placeholders** - Every piece of code must be complete and functional
- **No simplifications** - Full production-grade implementation only
- **No backward compatibility** - Break old formats freely, roll forward only
- **No hard-coded values** - Everything config-driven via environment/settings

---

## Engineering Quality Rules

### Fail Loudly, Not Silently
- Explicit errors with typed exceptions and clear error codes
- No "best effort" that hides data issues
- Raise exceptions immediately on invalid state

### Deterministic by Default
- Same inputs + same config + same seed = same outputs
- Anything nondeterministic must be explicitly marked and documented
- Use explicit random seeds for any stochastic operations

### Idempotency Everywhere
- All operations must be safe to retry
- Define idempotency keys for mutations
- Document state transitions explicitly

### Time is a First-Class Input
- All timestamps must be timezone-aware (UTC preferred)
- Never use `datetime.now()` inside core logic
- Inject clocks as dependencies for testability

### Config Over Code
- Everything tunable via config files or environment variables
- Config must be versioned
- Defaults must be safe and documented

### Pure Core, Impure Edges
- Core algorithms are pure functions (no side effects)
- IO/network/database operations only at boundaries
- Clear separation between business logic and infrastructure

### Single Source of Truth for Constants
- Central registry/config for all constants
- No scattered magic numbers or strings
- Use enums and typed constants

### No Hidden Side Effects
- Functions must not mutate shared state
- Explicit inputs and outputs only
- Document any unavoidable side effects

---

## Data Correctness Rules

### Define Invariants
- Validate all inputs and outputs (schema, ranges, units)
- Reject bad data early at boundaries
- Use Pydantic models with validators

### Units & Semantics are Explicit
- Never mix units (percent vs bps, ms vs s)
- Use strong typing or wrapper classes for units
- Document units in field names or types

### No Implicit Coercions
- No silent type casting
- No silent truncation or rounding
- Explicit NaN/None handling with documented policy

### Version Schemas and Datasets
- Every payload has a version field
- Database migrations are explicit and tested
- Breaking changes require version bump

### Reproducible Datasets
- Record source, query, and hashes
- Document feature generation config
- Enable exact reproduction of any dataset

### Explicit Missingness Policy
- Define per-field behavior: drop, impute, default, or error
- Log missingness handling decisions
- Never silently drop data

---

## Observability Rules

### Structured Logging Only
```python
# CORRECT
logger.info("workflow_executed", extra={
    "workflow_id": workflow_id,
    "user_id": user_id,
    "duration_ms": duration,
    "trace_id": trace_id
})

# WRONG
logger.info(f"Executed workflow {workflow_id} for user {user_id}")
```

### Metrics are Mandatory
- Latency (p50, p95, p99)
- Throughput (requests/sec)
- Error rate by type
- Queue depth and saturation
- Per-user/per-workflow where applicable

### Audit Trail for Decisions
- Log "why" not just "what"
- Include features, thresholds, rule hits
- Queryable format for debugging

### Feature Flags and Kill-Switches
- Instant disable per workflow/feature
- Circuit breakers for upstream dependencies
- Graceful degradation paths

### SLOs with Alerting
- Define SLOs for all critical paths
- Alerts based on burn rate, not arbitrary thresholds
- Document escalation paths

---

## Testing Rules

### Property-Based Tests for Algorithms
```python
# Use hypothesis for property tests
from hypothesis import given, strategies as st

@given(st.lists(st.integers()))
def test_sort_invariant(xs):
    result = sort(xs)
    assert len(result) == len(xs)
    assert all(result[i] <= result[i+1] for i in range(len(result)-1))
```

### Golden Tests for Regressions
- Store expected outputs for fixed seeds
- Frozen data snapshots for deterministic replay
- Fail on any output drift

### Fault Injection
- Test timeouts and partial failures
- Test duplicate messages
- Test out-of-order events
- Test network partitions

### Performance Budgets
- Tests fail if p95 latency exceeds budget
- Memory limit enforcement
- Define and enforce critical path SLAs

### Replay Tests
- Ability to replay historical inputs end-to-end
- Compare outputs for regression detection
- Store execution traces

---

## Deployment & Ops Rules

### No Mutable Global State
- Stateless services for horizontal scaling
- State in database/cache only
- No module-level mutable variables

### Bounded Resource Usage
- Explicit timeouts on all external calls
- Memory caps and batch limits
- Backpressure and load shedding
- Connection pool limits

### Concurrency Semantics are Explicit
- Document ordering guarantees
- Explicit locking strategy
- Define exactly-once vs at-least-once

### Roll Forward Only
- Migrations designed to move forward
- No "support old behavior" code
- Clean breaks between versions

### Safe Rollout Strategy
- Canary deployments
- Shadow mode testing
- Gradual traffic ramp
- Instant rollback path

---

## Security & Safety Rules

### No Secrets in Code or Logs
```python
# WRONG
api_key = "sk-abc123..."
logger.info(f"Using API key: {api_key}")

# CORRECT
api_key = settings.openai_api_key  # From env/secret manager
logger.info("API key loaded", extra={"key_prefix": api_key[:8] + "..."})
```

### Input is Hostile
- Validate everything from external sources
- Rate limiting on all endpoints
- Authentication and authorization everywhere
- Replay protection where needed

### Least Privilege
- Scoped credentials per service
- Separate credentials per environment
- Minimal database permissions

### Explainability for High-Stakes Outputs
- Emit rationale for important decisions
- Include confidence/uncertainty signals
- Audit log for all credential access

---

## Code Quality Requirements

### Must Run Immediately
- All code must work with all imports present
- No missing dependencies
- No placeholder implementations

### Follow Best Practices
- Design patterns where appropriate
- SOLID principles
- Clean architecture

### Prioritize Performance
- Profile critical paths
- Async where beneficial
- Efficient data structures

### Ensure Readability
- Clear naming conventions
- Single responsibility
- Appropriate abstraction level

### Cleanup After Use
- One-time scripts deleted after execution
- No dead code in repository
- Regular dependency audit

---

## Development Workflow

**Every code change must follow:**

```
1. Make changes (code/config/docs)
       |
2. Validate
   - Type check: mypy src/
   - Lint: ruff check src/
   - Test: pytest tests/
       |
3. Update documentation
   - Module CLAUDE.md if interface changed
   - Root CLAUDE.md if architecture changed
       |
4. Commit with proper format
```

### Commit Format
- `feat:` New feature
- `fix:` Bug fix
- `refactor:` Code refactoring
- `docs:` Documentation update
- `chore:` Maintenance

**Forbidden in commits:**
- "generated by claude" or similar
- Placeholder TODOs
- Commented-out code

---

## Project Structure

```
kk_exec/
├── src/
│   ├── main.py              # FastAPI entry
│   ├── config.py            # Settings (pydantic-settings)
│   ├── api/routes/          # API endpoints
│   ├── models/              # SQLModel entities
│   ├── services/            # Business logic
│   ├── core/                # Algorithms (pure functions)
│   ├── nodes/               # Node definitions
│   └── mcp/                 # MCP integration
├── tests/
├── alembic/                 # Migrations
└── CLAUDE.md               # This file
```

---

## Key Interfaces

### Workflow Graph Schema
```json
{
  "version": "1.0",
  "nodes": [
    {
      "id": "string",
      "type": "string",
      "config": {},
      "position": {"x": 0, "y": 0}
    }
  ],
  "edges": [
    {
      "source": "node_id",
      "target": "node_id",
      "sourceHandle": "output_name",
      "targetHandle": "input_name"
    }
  ],
  "config": {}
}
```

### Execution Event Schema
```json
{
  "type": "update|complete|error",
  "timestamp": "ISO8601",
  "data": {},
  "trace_id": "string"
}
```

### Credential Schema
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "credential_type": "string",
  "encrypted_data": "fernet_encrypted_string",
  "mcp_server_id": "string|null"
}
```

---

## Dependencies

Core:
- `fastapi>=0.115.0` - API framework
- `sqlmodel>=0.0.22` - ORM + validation
- `langgraph>=0.4.0` - Execution engine
- `mcp>=1.11.0` - MCP protocol
- `cryptography>=44.0.0` - Credential encryption

See `pyproject.toml` for full list.

---

## Change Checklist

Every algo/feature change must ship with:
- [ ] Config version bump if schema changed
- [ ] Reproducibility story (seed/data hashes)
- [ ] Regression coverage (golden + property tests)
- [ ] Metrics/dashboard updates
- [ ] Rollout + rollback plan documented

**"If it's not measurable, it's not real."**
