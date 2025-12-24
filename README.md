# KK Exec - MCP Workflow Automation

MCP-based workflow automation system with NLP-driven workflow creation, user-specific credential management, and federated MCP server architecture.

## Features

- **NLP Workflow Generation**: Describe workflows in natural language, get executable graphs
- **Federated MCP Architecture**: Per-integration MCP servers with user credential injection
- **Encrypted Credential Storage**: Fernet-encrypted credential management per user
- **Real-time Streaming**: SSE-based execution streaming for live updates
- **LangGraph Execution**: Robust workflow execution with checkpointing

## Quick Start

### Prerequisites

- Python 3.12+
- Redis 7+ (optional, for background tasks)
- Node.js 20+ (optional, for stdio MCP servers)

### Installation

```bash
# Clone repository
cd kk_exec

# Install dependencies
pip install -e ".[dev]"

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Generate encryption key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add to ENCRYPTION_KEY in .env

# Run database migrations (creates kk_exec.db in project directory)
alembic upgrade head

# Start server
uvicorn src.main:app --reload --port 9000
```

### Database

The project uses SQLite by default. The database file `kk_exec.db` is created in the project root directory after running migrations.

### Docker

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api
```

## CLI Usage

Execute natural language commands directly from the command line:

```bash
# Using environment variables
KLIK_USER=username KLIK_PASS=password ./cli/run_command.sh "Create a Notion page titled 'Meeting Notes'"

# Interactive mode (prompts for credentials)
./cli/run_command.sh "Search GitHub for repos about machine learning"
```

The CLI automatically:
1. Authenticates with your credentials
2. Analyzes your command to determine which MCPs to use
3. Builds a workflow from natural language
4. Executes and returns results

## API Overview

| Endpoint | Description |
|----------|-------------|
| `POST /api/v1/auth/login` | Authenticate user |
| `POST /api/v1/workflows/build` | Build workflow from NLP prompt |
| `POST /api/v1/workflows` | Create workflow from graph |
| `POST /api/v1/executions` | Execute a workflow |
| `GET /api/v1/executions/{id}/stream` | Stream execution events |
| `GET /api/v1/nodes` | List available nodes |
| `GET /api/v1/mcp/servers` | List MCP servers |
| `GET /api/v1/credentials` | List user credentials |
| `GET /api/v1/oauth/{provider}/authorize` | Start OAuth flow |

Full API documentation available at `/docs` when running in debug mode.

## Project Structure

```
kk_exec/
├── src/
│   ├── main.py              # FastAPI entry
│   ├── config.py            # Settings
│   ├── api/routes/          # API endpoints
│   ├── models/              # SQLModel entities
│   ├── services/            # Business logic
│   ├── core/                # Pure algorithms
│   ├── nodes/               # Node definitions
│   └── mcp/                 # MCP integration
├── tests/                   # Test suite
├── alembic/                 # Database migrations
└── CLAUDE.md               # Development standards
```

## Development

```bash
# Run tests
pytest tests/ -v

# Type check
mypy src/

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/
```

## Architecture

```
NLP Prompt
    ↓
Get Nodes (Node Library)
    ↓
Select Nodes (Node Selector)
    ↓
Build Workflow (Workflow Builder)
    ↓
Get User Credentials (Credential Service)
    ↓
Execute (LangGraph + MCP Gateway)
    ↓
Stream Results (SSE)
```

## Key Technologies

- **FastAPI**: Async API framework
- **SQLModel**: ORM + validation
- **SQLite**: Local database (file: `kk_exec.db`)
- **LangGraph**: Workflow execution engine
- **MCP**: Model Context Protocol for integrations
- **Fernet**: Credential encryption
- **SSE**: Real-time streaming

## License

MIT
