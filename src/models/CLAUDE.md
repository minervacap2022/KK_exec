# Models Module

## Purpose

SQLModel entities and runtime data models for the workflow automation system.

## Architecture

```
models/
├── user.py          # User authentication entity
├── workflow.py      # Workflow definition with JSON graph
├── credential.py    # Encrypted credential storage
├── execution.py     # Workflow execution tracking
└── node.py          # Runtime node definitions (not persisted)
```

## Key Patterns

### SQLModel Entities

All persisted entities use SQLModel with:
- UUID primary keys (string type for PostgreSQL compatibility)
- Timezone-aware timestamps (UTC)
- Relationships defined with back_populates
- Pydantic validation on all fields

### Schema Pattern

Each entity has multiple schemas:
- `Base`: Shared fields for create/read
- `Entity`: Database table (table=True)
- `Create`: Request schema for creation
- `Update`: Optional fields for updates
- `Read`: Response schema

### Encryption

Credential data uses Fernet encryption:
- `encrypted_data` stores Fernet-encrypted JSON
- Never log decrypted values
- Use `CredentialDecrypted` only when values are needed

## Key Invariants

1. All timestamps must be UTC with timezone info
2. User ID is always a foreign key for multi-tenancy
3. JSON fields (graph, input_data, output_data) stored as Text
4. Status enums are string-backed for database compatibility

## Testing

```bash
pytest tests/test_models/ -v
```

## Changes

When modifying models:
1. Update Alembic migration
2. Update all schema variants
3. Verify serialization/deserialization
4. Run model tests
