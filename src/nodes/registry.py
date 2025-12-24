"""Node registry.

Central registry for all available workflow nodes.
"""

from typing import Type

import structlog

from src.nodes.base import BaseNode
from src.models.node import NodeCategory, NodeDefinition

logger = structlog.get_logger()


class NodeRegistryError(Exception):
    """Error in node registry operations."""

    pass


class NodeRegistry:
    """Central registry for workflow nodes.

    Manages node registration, discovery, and instantiation.

    Example usage:
        registry = NodeRegistry()
        registry.register(CalculatorNode)
        registry.register(SlackNode)

        node = registry.get("calculator")
        result = await node.run({"expression": "1+1"}, context)
    """

    def __init__(self) -> None:
        """Initialize empty registry."""
        self._nodes: dict[str, Type[BaseNode]] = {}
        self._instances: dict[str, BaseNode] = {}

    def register(self, node_class: Type[BaseNode]) -> None:
        """Register a node class.

        Args:
            node_class: Node class to register

        Raises:
            NodeRegistryError: If node with same name exists
        """
        # Create instance to get definition
        instance = node_class()
        definition = instance.get_definition()

        if definition.name in self._nodes:
            raise NodeRegistryError(
                f"Node '{definition.name}' already registered"
            )

        self._nodes[definition.name] = node_class
        self._instances[definition.name] = instance

        logger.debug(
            "node_registered",
            name=definition.name,
            category=definition.category.value,
        )

    def unregister(self, name: str) -> None:
        """Remove a node from the registry.

        Args:
            name: Node name to remove
        """
        self._nodes.pop(name, None)
        self._instances.pop(name, None)

    def get(self, name: str) -> BaseNode | None:
        """Get a node instance by name.

        Args:
            name: Node name

        Returns:
            Node instance or None if not found
        """
        return self._instances.get(name)

    def get_class(self, name: str) -> Type[BaseNode] | None:
        """Get a node class by name.

        Args:
            name: Node name

        Returns:
            Node class or None if not found
        """
        return self._nodes.get(name)

    def get_definition(self, name: str) -> NodeDefinition | None:
        """Get node definition by name.

        Args:
            name: Node name

        Returns:
            NodeDefinition or None if not found
        """
        instance = self._instances.get(name)
        if instance is None:
            return None
        return instance.get_definition()

    def list_all(self) -> list[NodeDefinition]:
        """List all registered node definitions.

        Returns:
            List of all node definitions
        """
        return [inst.get_definition() for inst in self._instances.values()]

    def list_by_category(self, category: NodeCategory) -> list[NodeDefinition]:
        """List nodes by category.

        Args:
            category: Node category

        Returns:
            List of matching node definitions
        """
        return [
            inst.get_definition()
            for inst in self._instances.values()
            if inst.category == category
        ]

    def list_by_credential(self, credential_type: str) -> list[NodeDefinition]:
        """List nodes requiring a specific credential type.

        Args:
            credential_type: Credential type

        Returns:
            List of matching node definitions
        """
        return [
            inst.get_definition()
            for inst in self._instances.values()
            if inst.credential_type == credential_type
        ]

    def create_instance(self, name: str) -> BaseNode | None:
        """Create a new instance of a node.

        Args:
            name: Node name

        Returns:
            New node instance or None if not found
        """
        node_class = self._nodes.get(name)
        if node_class is None:
            return None
        return node_class()

    def load_builtin_nodes(self) -> int:
        """Load all built-in nodes.

        Returns:
            Number of nodes loaded
        """
        from src.nodes.tools.calculator import CalculatorNode
        from src.nodes.tools.text_processor import TextProcessorNode
        from src.nodes.tools.json_transformer import JsonTransformerNode
        from src.nodes.apis.openai import OpenAINode
        from src.nodes.apis.anthropic import AnthropicNode
        from src.nodes.apis.weather import WeatherNode
        from src.nodes.mcp.slack import SlackMCPNode
        from src.nodes.mcp.github import GitHubMCPNode
        from src.nodes.mcp.filesystem import FilesystemMCPNode

        builtin_nodes = [
            # Tools
            CalculatorNode,
            TextProcessorNode,
            JsonTransformerNode,
            # APIs
            OpenAINode,
            AnthropicNode,
            WeatherNode,
            # MCP
            SlackMCPNode,
            GitHubMCPNode,
            FilesystemMCPNode,
        ]

        count = 0
        for node_class in builtin_nodes:
            try:
                self.register(node_class)
                count += 1
            except NodeRegistryError as e:
                logger.warning(
                    "builtin_node_registration_failed",
                    error=str(e),
                )

        logger.info("builtin_nodes_loaded", count=count)
        return count


# Singleton instance
_registry: NodeRegistry | None = None


def get_node_registry() -> NodeRegistry:
    """Get or create the singleton node registry.

    Returns:
        NodeRegistry instance with builtin nodes loaded
    """
    global _registry
    if _registry is None:
        _registry = NodeRegistry()
        _registry.load_builtin_nodes()
    return _registry
