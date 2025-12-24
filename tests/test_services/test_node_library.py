"""Tests for node library service."""

import pytest

from src.models.node import NodeCategory
from src.services.node_library import NodeLibrary, NodeLibraryError, get_node_library


class TestNodeLibrary:
    """Tests for NodeLibrary class."""

    def test_load_builtin_nodes(self):
        """Test loading built-in nodes."""
        library = NodeLibrary()
        count = library.load_builtin_nodes()

        assert count > 0
        assert len(library.get_all_nodes()) == count

    def test_get_node_by_name(self):
        """Test getting a node by name."""
        library = get_node_library()

        calculator = library.get("calculator")
        assert calculator is not None
        assert calculator.name == "calculator"
        assert calculator.category == NodeCategory.TOOL

    def test_get_nodes_by_category(self):
        """Test filtering nodes by category."""
        library = get_node_library()

        tools = library.get_nodes_by_category(NodeCategory.TOOL)
        assert len(tools) > 0
        assert all(n.category == NodeCategory.TOOL for n in tools)

        apis = library.get_nodes_by_category(NodeCategory.API)
        assert len(apis) > 0
        assert all(n.category == NodeCategory.API for n in apis)

        mcp = library.get_nodes_by_category(NodeCategory.MCP)
        assert len(mcp) > 0
        assert all(n.category == NodeCategory.MCP for n in mcp)

    def test_get_nodes_for_mcp_server(self):
        """Test getting nodes for an MCP server."""
        library = get_node_library()

        slack_nodes = library.get_nodes_for_mcp_server("slack")
        assert len(slack_nodes) > 0
        assert all(n.mcp_server_id == "slack" for n in slack_nodes)

    def test_get_nodes_by_credential(self):
        """Test getting nodes by credential type."""
        library = get_node_library()

        openai_nodes = library.get_nodes_by_credential("openai_api_key")
        assert len(openai_nodes) > 0
        assert all(n.credential_type == "openai_api_key" for n in openai_nodes)

    def test_get_available_nodes(self):
        """Test getting available nodes based on credentials."""
        library = get_node_library()

        # No credentials - only tool nodes
        available_none = library.get_available_nodes([])
        assert len(available_none) > 0
        for node in available_none:
            # Should only include nodes with no credential requirement
            # or nodes like filesystem that don't need auth
            if node.category == NodeCategory.API:
                assert False, f"API node {node.name} should not be available without credentials"

        # With some credentials
        available_some = library.get_available_nodes(["openai_api_key", "slack_oauth"])
        assert len(available_some) > len(available_none)

    def test_duplicate_registration_raises_error(self):
        """Test that duplicate registration raises error."""
        from src.models.node import NodeDefinition

        library = NodeLibrary()
        library.load_builtin_nodes()

        duplicate = NodeDefinition(
            name="calculator",  # Already exists
            display_name="Duplicate",
            description="Test",
            category=NodeCategory.TOOL,
        )

        with pytest.raises(NodeLibraryError):
            library.register(duplicate)

    def test_get_catalog(self):
        """Test getting full catalog."""
        library = get_node_library()
        catalog = library.get_catalog()

        assert "categories" in catalog
        assert "total_count" in catalog
        assert catalog["total_count"] > 0

        for category in NodeCategory:
            assert category.value in catalog["categories"]
