"""LangGraph-based workflow execution engine.

Executes workflow graphs using LangGraph's StateGraph pattern.
Supports streaming execution with SSE, checkpointing, and MCP integration.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable
from uuid import uuid4

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from src.config import settings
from src.models.credential import CredentialDecrypted
from src.models.execution import ExecutionStatus
from src.models.node import GraphEdge, NodeDefinition, NodeInstance
from src.models.workflow import Workflow

logger = structlog.get_logger()


def utc_now() -> datetime:
    """Get current UTC time with timezone info."""
    return datetime.now(timezone.utc)


class ExecutionError(Exception):
    """Base exception for execution errors."""

    def __init__(self, message: str, error_code: str = "EXECUTION_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code


class NodeExecutionError(ExecutionError):
    """Error during node execution."""

    def __init__(
        self,
        message: str,
        node_id: str,
        node_type: str,
        error_code: str = "NODE_ERROR",
    ) -> None:
        super().__init__(message, error_code)
        self.node_id = node_id
        self.node_type = node_type


class TimeoutError(ExecutionError):
    """Execution timeout."""

    def __init__(self, message: str = "Execution timed out") -> None:
        super().__init__(message, "TIMEOUT")


@dataclass
class ExecutionEvent:
    """Event emitted during workflow execution."""

    type: str  # 'start', 'step', 'update', 'complete', 'error'
    timestamp: datetime = field(default_factory=utc_now)
    data: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    node_id: str | None = None
    step_number: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for SSE streaming."""
        return {
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "trace_id": self.trace_id,
            "node_id": self.node_id,
            "step_number": self.step_number,
        }

    def to_sse(self) -> str:
        """Format as Server-Sent Event."""
        return f"data: {json.dumps(self.to_dict())}\n\n"


@dataclass
class ExecutionState:
    """State maintained during workflow execution."""

    messages: list[BaseMessage] = field(default_factory=list)
    current_step: int = 0
    node_outputs: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    status: ExecutionStatus = ExecutionStatus.RUNNING


class WorkflowExecutionEngine:
    """LangGraph-based workflow execution engine.

    Executes workflow graphs with:
    - Streaming updates via SSE
    - MCP tool integration
    - Checkpointing for resume capability
    - Step-by-step execution tracking

    Example usage:
        engine = WorkflowExecutionEngine()
        async for event in engine.execute(workflow, input_data, credentials):
            print(event.type, event.data)
    """

    def __init__(
        self,
        model: str | None = None,
        temperature: float | None = None,
        max_steps: int | None = None,
        timeout: int | None = None,
    ) -> None:
        """Initialize the execution engine.

        Args:
            model: LLM model to use (defaults to settings.default_model)
            temperature: LLM temperature (defaults to settings.llm_temperature)
            max_steps: Maximum execution steps (defaults to settings.execution_max_steps)
            timeout: Execution timeout in seconds (defaults to settings.execution_timeout)
        """
        self.model = model or settings.default_model
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.max_steps = max_steps or settings.execution_max_steps
        self.timeout = timeout or settings.execution_timeout

        self._llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_timeout,
        )

    async def execute(
        self,
        workflow: Workflow,
        input_data: dict[str, Any],
        user_credentials: list[CredentialDecrypted],
        tools: list[BaseTool] | None = None,
        stream: bool = True,
    ) -> AsyncGenerator[ExecutionEvent, None]:
        """Execute a workflow with streaming events.

        Args:
            workflow: Workflow to execute
            input_data: Input data for the workflow
            user_credentials: User's credentials for MCP/API access
            tools: Pre-configured tools (if None, will build from workflow)
            stream: Whether to stream intermediate events

        Yields:
            ExecutionEvent for each step and the final result

        Raises:
            ExecutionError: If execution fails
        """
        trace_id = str(uuid4())
        step_count = 0

        logger.info(
            "execution_starting",
            workflow_id=workflow.id,
            trace_id=trace_id,
            input_keys=list(input_data.keys()),
        )

        # Emit start event
        yield ExecutionEvent(
            type="start",
            trace_id=trace_id,
            data={
                "workflow_id": workflow.id,
                "workflow_name": workflow.name,
                "input_data": input_data,
            },
        )

        try:
            # Parse workflow graph
            graph_def = workflow.get_graph()
            nodes = [NodeInstance.from_dict(n) for n in graph_def.get("nodes", [])]
            edges = [GraphEdge.from_dict(e) for e in graph_def.get("edges", [])]

            logger.debug(
                "workflow_parsed",
                node_count=len(nodes),
                edge_count=len(edges),
                trace_id=trace_id,
            )

            # Build tools if not provided
            if tools is None:
                tools = await self._build_tools_from_nodes(nodes, user_credentials)

            # Create LangGraph
            state_graph = self._build_state_graph(nodes, edges, tools)
            compiled = state_graph.compile()

            # Prepare initial state
            initial_state = ExecutionState(
                messages=[HumanMessage(content=json.dumps(input_data))],
            )

            # Execute with streaming
            if stream:
                async for chunk in compiled.astream(
                    {"messages": initial_state.messages},
                    stream_mode="updates",
                ):
                    step_count += 1

                    if step_count > self.max_steps:
                        raise ExecutionError(
                            f"Execution exceeded maximum steps ({self.max_steps})",
                            "MAX_STEPS_EXCEEDED",
                        )

                    yield ExecutionEvent(
                        type="step",
                        trace_id=trace_id,
                        step_number=step_count,
                        data=self._serialize_chunk(chunk),
                    )
            else:
                result = await compiled.ainvoke({"messages": initial_state.messages})
                step_count = 1

            # Get final result
            final_result = await compiled.ainvoke({"messages": initial_state.messages})
            output_data = self._extract_output(final_result)

            logger.info(
                "execution_completed",
                workflow_id=workflow.id,
                trace_id=trace_id,
                steps=step_count,
            )

            yield ExecutionEvent(
                type="complete",
                trace_id=trace_id,
                step_number=step_count,
                data={
                    "output": output_data,
                    "steps_completed": step_count,
                },
            )

        except ExecutionError:
            raise
        except Exception as e:
            logger.exception(
                "execution_failed",
                workflow_id=workflow.id,
                trace_id=trace_id,
                error_type=type(e).__name__,
            )

            yield ExecutionEvent(
                type="error",
                trace_id=trace_id,
                step_number=step_count,
                data={
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

            raise ExecutionError(str(e), "EXECUTION_FAILED") from e

    def _build_state_graph(
        self,
        nodes: list[NodeInstance],
        edges: list[GraphEdge],
        tools: list[BaseTool],
    ) -> StateGraph:
        """Build a LangGraph StateGraph from workflow definition.

        Args:
            nodes: Workflow nodes
            edges: Workflow edges
            tools: Available tools

        Returns:
            Compiled StateGraph
        """
        from typing import Annotated, TypedDict
        from langgraph.graph.message import add_messages

        class AgentState(TypedDict):
            messages: Annotated[list[BaseMessage], add_messages]

        # Create the graph
        graph = StateGraph(AgentState)

        # Bind tools to LLM
        llm_with_tools = self._llm.bind_tools(tools) if tools else self._llm

        # Agent node - calls LLM
        def agent_node(state: AgentState) -> dict[str, list[BaseMessage]]:
            response = llm_with_tools.invoke(state["messages"])
            return {"messages": [response]}

        # Add nodes
        graph.add_node("agent", agent_node)

        if tools:
            tool_node = ToolNode(tools)
            graph.add_node("tools", tool_node)

            # Conditional routing
            def should_continue(state: AgentState) -> str:
                last_message = state["messages"][-1]
                if isinstance(last_message, AIMessage) and last_message.tool_calls:
                    return "tools"
                return END

            graph.add_edge(START, "agent")
            graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
            graph.add_edge("tools", "agent")
        else:
            graph.add_edge(START, "agent")
            graph.add_edge("agent", END)

        return graph

    async def _build_tools_from_nodes(
        self,
        nodes: list[NodeInstance],
        credentials: list[CredentialDecrypted],
    ) -> list[BaseTool]:
        """Build LangChain tools from workflow nodes.

        Args:
            nodes: Workflow nodes
            credentials: User credentials

        Returns:
            List of configured tools
        """
        from langchain_core.tools import StructuredTool
        from src.nodes.mcp.notion import NotionCreatePageNode, NotionCreatePageInput
        from src.nodes.base import NodeContext

        tools: list[BaseTool] = []

        # Build credential map
        cred_map = {}
        logger.info(
            "building_tools_credentials_received",
            credential_count=len(credentials),
        )

        for cred in credentials:
            logger.info(
                "loading_credential",
                cred_type=cred.credential_type,
                cred_id=cred.id,
            )
            # CredentialDecrypted objects already have decrypted .data
            cred_map[cred.credential_type] = cred.data
            logger.info(
                "credential_loaded",
                cred_type=cred.credential_type,
                data_keys=list(cred.data.keys()) if isinstance(cred.data, dict) else "not_dict",
            )

        logger.info(
            "credentials_loaded_for_execution",
            credential_types=list(cred_map.keys()),
            cred_map_keys=list(cred_map.keys()),
        )

        # Create tools from nodes
        for node_inst in nodes:
            # For now, only handle Notion nodes explicitly
            # TODO: Expand to use node registry for automatic tool creation
            if node_inst.node_type == "notion_create_page":
                # Create the node instance
                node = NotionCreatePageNode()

                # Create a factory function that captures credentials correctly
                def make_create_page_func(credentials_map: dict[str, Any]):
                    async def create_notion_page(
                        title: str,
                        content: str = "",
                        parent_page_id: str | None = None,
                    ) -> str:
                        """Create a new page in Notion."""
                        context = NodeContext(
                            user_id="",  # Will be filled by execution context
                            execution_id="",
                            credentials=credentials_map,
                            variables={},
                        )

                        input_data = NotionCreatePageInput(
                            title=title,
                            content=content or "",
                            parent_page_id=parent_page_id,
                        )

                        result = await node.execute(input_data, context)
                        return f"Created Notion page: {result.title} (ID: {result.page_id}, URL: {result.url})"

                    return create_notion_page

                create_page_func = make_create_page_func(cred_map)

                tool = StructuredTool.from_function(
                    func=create_page_func,
                    name="create_notion_page",
                    description="Create a new page in Notion workspace",
                    coroutine=create_page_func,
                )
                tools.append(tool)

        logger.debug(
            "tools_built_from_nodes",
            node_count=len(nodes),
            tool_count=len(tools),
        )

        return tools

    def _serialize_chunk(self, chunk: Any) -> dict[str, Any]:
        """Serialize a streaming chunk for SSE.

        Args:
            chunk: Raw chunk from LangGraph

        Returns:
            Serializable dictionary
        """
        if isinstance(chunk, dict):
            result = {}
            for key, value in chunk.items():
                if isinstance(value, dict) and "messages" in value:
                    messages = value["messages"]
                    result[key] = {
                        "messages": [
                            {
                                "type": type(m).__name__,
                                "content": getattr(m, "content", str(m)),
                            }
                            for m in messages
                        ]
                    }
                else:
                    result[key] = str(value)
            return result
        return {"raw": str(chunk)}

    def _extract_output(self, result: dict[str, Any]) -> dict[str, Any]:
        """Extract final output from execution result.

        Args:
            result: Raw result from LangGraph

        Returns:
            Cleaned output dictionary
        """
        messages = result.get("messages", [])
        if not messages:
            return {"result": None}

        last_message = messages[-1]
        if isinstance(last_message, AIMessage):
            return {
                "result": last_message.content,
                "tool_calls": [
                    {"name": tc["name"], "args": tc["args"]}
                    for tc in (last_message.tool_calls or [])
                ],
            }
        return {"result": str(last_message)}
