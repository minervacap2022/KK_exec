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

        llm_kwargs = {
            "model": self.model,
            "temperature": self.temperature,
            "api_key": settings.openai_api_key.get_secret_value(),
            "timeout": settings.llm_timeout,
        }

        # Add base_url if configured
        if settings.openai_base_url:
            llm_kwargs["base_url"] = settings.openai_base_url

        self._llm = ChatOpenAI(**llm_kwargs)

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

            # Execute with streaming and collect final state
            final_state = None
            if stream:
                # Use astream with values mode to get final state
                stream_mode = ["updates", "values"]
                async for chunk in compiled.astream(
                    {"messages": initial_state.messages},
                    stream_mode=stream_mode,
                ):
                    step_count += 1

                    if step_count > self.max_steps:
                        raise ExecutionError(
                            f"Execution exceeded maximum steps ({self.max_steps})",
                            "MAX_STEPS_EXCEEDED",
                        )

                    # chunk is (mode, data) tuple when using multiple stream modes
                    if isinstance(chunk, tuple):
                        mode, data = chunk
                        if mode == "values":
                            # This is the full state, save it
                            final_state = data
                        elif mode == "updates":
                            # This is just the update, emit step event
                            yield ExecutionEvent(
                                type="step",
                                trace_id=trace_id,
                                step_number=step_count,
                                data=self._serialize_chunk(data),
                            )
                    else:
                        # Single stream mode
                        yield ExecutionEvent(
                            type="step",
                            trace_id=trace_id,
                            step_number=step_count,
                            data=self._serialize_chunk(chunk),
                        )

                # If we didn't capture final state from streaming, get it now
                if final_state is None:
                    final_state = await compiled.ainvoke({"messages": initial_state.messages})
            else:
                # Execute without streaming
                final_state = await compiled.ainvoke({"messages": initial_state.messages})
                step_count = 1

            # Extract output from final state
            output_data = self._extract_output(final_state)

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

        from src.nodes.base import NodeContext
        from src.nodes.mcp.notion import NotionCreatePageInput, NotionCreatePageNode
        from src.nodes.registry import get_node_registry

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

        logger.info(
            "building_tools_from_nodes",
            node_count=len(nodes),
            node_types=[n.node_type for n in nodes],
        )

        # Get node registry for dynamic node creation
        registry = get_node_registry()

        # Create tools from nodes
        for node_inst in nodes:
            logger.info(
                "processing_node_for_tool",
                node_type=node_inst.node_type,
                node_id=node_inst.id,
            )

            # Get node from registry
            node = registry.get(node_inst.node_type)
            if node is None:
                logger.warning(
                    "node_type_not_found_in_registry",
                    node_type=node_inst.node_type,
                    node_id=node_inst.id,
                )
                continue

            # Log what we got from registry
            logger.info(
                "node_retrieved_from_registry",
                node_type=node_inst.node_type,
                node_instance_type=type(node).__name__,
                node_definition_name=node.get_definition().name,
            )

            # Get node definition
            definition = node.get_definition()

            # Create a wrapper function that executes the node
            def make_node_wrapper(
                node_obj: BaseNode,
                node_def: NodeDefinition,
                creds: dict[str, Any],
                node_config: dict[str, Any],
            ):
                async def node_wrapper(**kwargs) -> str:
                    """Execute the node with given arguments."""
                    # Log what node is being used
                    import inspect
                    sig = inspect.signature(node_obj.execute)
                    input_param = list(sig.parameters.values())[0]
                    logger.info(
                        "node_wrapper_executing",
                        node_obj_type=type(node_obj).__name__,
                        execute_input_annotation=str(input_param.annotation),
                        kwargs_keys=list(kwargs.keys()),
                    )

                    # Merge config from node instance with runtime arguments
                    input_data = {**node_config, **kwargs}

                    context = NodeContext(
                        user_id="",
                        execution_id="",
                        credentials=creds,
                        variables={},
                    )

                    # Validate input - node's validate_input should return the expected dataclass type
                    validated = node_obj.validate_input(input_data)

                    logger.info(
                        "node_wrapper_after_validation",
                        node_type=node_inst.node_type,
                        validated_type=type(validated).__name__,
                        is_dict=isinstance(validated, dict),
                    )

                    result = await node_obj.execute(validated, context)

                    # Return simple string result
                    if hasattr(result, "__dict__"):
                        return str(result.__dict__)
                    return str(result)

                # Set name and docstring from definition
                node_wrapper.__name__ = node_def.name
                node_wrapper.__doc__ = node_def.description
                return node_wrapper

            wrapper_func = make_node_wrapper(node, definition, cred_map, node_inst.config or {})

            # Create LangChain tool
            tool = StructuredTool.from_function(
                func=wrapper_func,
                name=definition.name,
                description=definition.description,
                coroutine=wrapper_func,
            )
            tools.append(tool)

            logger.info(
                "tool_created_from_node",
                node_type=node_inst.node_type,
                tool_name=definition.name,
                tool_count=len(tools),
            )

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
        from langchain_core.messages import ToolMessage

        messages = result.get("messages", [])
        if not messages:
            return {"result": None}

        # Look for tool messages first - they contain the actual tool results
        for msg in reversed(messages):
            if isinstance(msg, ToolMessage):
                # Tool message contains the raw result from the tool
                return {
                    "result": msg.content,
                    "type": "tool_result",
                }

        # Fall back to last AI message
        last_message = messages[-1]
        if isinstance(last_message, AIMessage):
            # Check if there were tool calls
            has_tool_calls = last_message.tool_calls and len(last_message.tool_calls) > 0
            return {
                "result": last_message.content,
                "tool_calls": [
                    {"name": tc["name"], "args": tc["args"]}
                    for tc in (last_message.tool_calls or [])
                ],
                "type": "ai_response",
                "has_tool_calls": has_tool_calls,
            }
        return {"result": str(last_message)}
