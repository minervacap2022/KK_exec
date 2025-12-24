"""NLP-driven workflow builder.

Converts natural language prompts into workflow graph definitions.
Uses LLM with ReAct-style prompting for workflow generation.
"""

import json
from dataclasses import dataclass
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.config import settings
from src.models.node import NodeCategory, NodeDefinition
from src.models.workflow import WorkflowGraph, WorkflowGraphEdge, WorkflowGraphNode

logger = structlog.get_logger()


class WorkflowBuilderError(Exception):
    """Error during workflow building."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class GeneratedWorkflow(BaseModel):
    """Schema for LLM-generated workflow."""

    name: str = Field(description="Workflow name")
    description: str = Field(description="Workflow description")
    nodes: list[dict[str, Any]] = Field(description="List of workflow nodes")
    edges: list[dict[str, Any]] = Field(description="List of workflow edges")
    explanation: str = Field(description="Explanation of the workflow")
    warnings: list[str] = Field(default_factory=list, description="Any warnings")


@dataclass
class BuildResult:
    """Result of workflow building."""

    workflow_graph: WorkflowGraph
    name: str
    description: str
    explanation: str
    warnings: list[str]


SYSTEM_PROMPT = """You are a workflow automation expert. Your task is to convert natural language descriptions into executable workflow graphs.

## Available Nodes

{node_catalog}

## User's Available Credentials

{user_credentials}

## Workflow Graph Schema

Each workflow has:
- nodes: Array of node objects with id, type, config, position
- edges: Array of edge objects connecting nodes with source, target, sourceHandle, targetHandle

## Rules

1. Only use nodes from the provided catalog
2. Only use nodes requiring credentials if the user has those credentials
3. Each node must have a unique id (use descriptive names like "fetch_weather", "send_slack")
4. Connect nodes with edges - data flows from source to target
5. Position nodes logically (x increases left-to-right, y increases top-to-bottom)
6. Include clear explanation of what the workflow does
7. Add warnings for any potential issues or missing credentials

## Output Format

Return a JSON object with:
- name: Short workflow name
- description: One-line description
- nodes: Array of node objects
- edges: Array of edge objects
- explanation: Detailed explanation
- warnings: Array of warning strings

Example node:
{{
  "id": "fetch_data",
  "type": "http_request",
  "config": {{"url": "https://api.example.com/data", "method": "GET"}},
  "position": {{"x": 100, "y": 100}}
}}

Example edge:
{{
  "source": "fetch_data",
  "target": "process_data",
  "sourceHandle": "output",
  "targetHandle": "input"
}}
"""


class WorkflowBuilder:
    """Builds workflow graphs from natural language prompts.

    Uses LLM with structured output to generate valid workflow definitions.
    Validates node availability and credential requirements.

    Example usage:
        builder = WorkflowBuilder(node_library)
        result = await builder.build(
            prompt="Send weather to Slack every morning",
            available_credentials=["slack_oauth", "weather_api_key"]
        )
    """

    def __init__(
        self,
        node_catalog: list[NodeDefinition],
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        """Initialize the workflow builder.

        Args:
            node_catalog: Available nodes for workflow building
            model: LLM model to use (defaults to settings.default_model)
            temperature: LLM temperature (0.0 for deterministic output)
        """
        self.node_catalog = node_catalog
        self.model = model or settings.default_model
        self.temperature = temperature

        self._llm = ChatOpenAI(
            model=self.model,
            temperature=self.temperature,
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_timeout,
        )
        self._parser = JsonOutputParser(pydantic_object=GeneratedWorkflow)

    async def build(
        self,
        prompt: str,
        available_credentials: list[str] | None = None,
    ) -> BuildResult:
        """Build a workflow from a natural language prompt.

        Args:
            prompt: Natural language description of desired workflow
            available_credentials: List of credential types the user has

        Returns:
            BuildResult with workflow graph and metadata

        Raises:
            WorkflowBuilderError: If building fails
        """
        available_credentials = available_credentials or []

        logger.info(
            "workflow_build_starting",
            prompt_length=len(prompt),
            available_credentials=available_credentials,
        )

        try:
            # Format node catalog for prompt
            node_catalog_text = self._format_node_catalog()
            credentials_text = self._format_credentials(available_credentials)

            # Build system prompt
            system_prompt = SYSTEM_PROMPT.format(
                node_catalog=node_catalog_text,
                user_credentials=credentials_text,
            )

            # Call LLM
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Create a workflow for: {prompt}"),
            ]

            response = await self._llm.ainvoke(messages)
            result = self._parser.parse(response.content)

            # Validate and convert to WorkflowGraph
            workflow_graph = self._convert_to_graph(result)

            # Additional validation
            warnings = list(result.get("warnings", []))
            validation_warnings = self._validate_workflow(
                workflow_graph, available_credentials
            )
            warnings.extend(validation_warnings)

            logger.info(
                "workflow_build_completed",
                node_count=len(workflow_graph.nodes),
                edge_count=len(workflow_graph.edges),
                warning_count=len(warnings),
            )

            return BuildResult(
                workflow_graph=workflow_graph,
                name=result["name"],
                description=result["description"],
                explanation=result["explanation"],
                warnings=warnings,
            )

        except Exception as e:
            logger.exception("workflow_build_failed", error_type=type(e).__name__)
            raise WorkflowBuilderError(
                f"Failed to build workflow: {str(e)}",
                details={"prompt": prompt[:100]},
            ) from e

    def _format_node_catalog(self) -> str:
        """Format node catalog for LLM prompt."""
        lines = []
        for category in NodeCategory:
            category_nodes = [n for n in self.node_catalog if n.category == category]
            if category_nodes:
                lines.append(f"\n### {category.value.upper()} Nodes\n")
                for node in category_nodes:
                    cred_info = (
                        f" (requires: {node.credential_type})"
                        if node.credential_type
                        else ""
                    )
                    lines.append(f"- **{node.name}**: {node.description}{cred_info}")
                    if node.inputs:
                        inputs_str = ", ".join(
                            f"{i.name}:{i.type.value}" for i in node.inputs
                        )
                        lines.append(f"  - Inputs: {inputs_str}")
                    if node.outputs:
                        outputs_str = ", ".join(
                            f"{o.name}:{o.type.value}" for o in node.outputs
                        )
                        lines.append(f"  - Outputs: {outputs_str}")

        return "\n".join(lines) if lines else "No nodes available."

    def _format_credentials(self, available_credentials: list[str]) -> str:
        """Format available credentials for LLM prompt."""
        if not available_credentials:
            return "No credentials configured. Only use nodes that don't require authentication."
        return "Available credential types:\n" + "\n".join(
            f"- {cred}" for cred in available_credentials
        )

    def _convert_to_graph(self, result: dict[str, Any]) -> WorkflowGraph:
        """Convert LLM result to WorkflowGraph."""
        nodes = []
        for node_data in result.get("nodes", []):
            nodes.append(
                WorkflowGraphNode(
                    id=node_data["id"],
                    type=node_data["type"],
                    config=node_data.get("config", {}),
                    position=node_data.get("position", {"x": 0, "y": 0}),
                )
            )

        edges = []
        for edge_data in result.get("edges", []):
            edges.append(
                WorkflowGraphEdge(
                    source=edge_data["source"],
                    target=edge_data["target"],
                    sourceHandle=edge_data.get("sourceHandle", "output"),
                    targetHandle=edge_data.get("targetHandle", "input"),
                )
            )

        return WorkflowGraph(
            version="1.0",
            nodes=nodes,
            edges=edges,
            config={},
        )

    def _validate_workflow(
        self,
        graph: WorkflowGraph,
        available_credentials: list[str],
    ) -> list[str]:
        """Validate workflow and return warnings."""
        warnings = []

        # Check for unknown node types
        known_types = {n.name for n in self.node_catalog}
        for node in graph.nodes:
            if node.type not in known_types:
                warnings.append(f"Unknown node type: {node.type}")

        # Check credential requirements
        for node in graph.nodes:
            node_def = next(
                (n for n in self.node_catalog if n.name == node.type), None
            )
            if node_def and node_def.credential_type:
                if node_def.credential_type not in available_credentials:
                    warnings.append(
                        f"Node '{node.id}' requires credential '{node_def.credential_type}' "
                        "which is not available"
                    )

        # Check for disconnected nodes
        connected_nodes = set()
        for edge in graph.edges:
            connected_nodes.add(edge.source)
            connected_nodes.add(edge.target)

        for node in graph.nodes:
            if node.id not in connected_nodes and len(graph.nodes) > 1:
                warnings.append(f"Node '{node.id}' is not connected to any other node")

        # Check for cycles (basic check)
        # A proper cycle detection would use DFS
        edge_pairs = [(e.source, e.target) for e in graph.edges]
        for source, target in edge_pairs:
            if (target, source) in edge_pairs:
                warnings.append(f"Potential cycle detected between '{source}' and '{target}'")

        return warnings
