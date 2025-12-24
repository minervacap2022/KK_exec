"""Node selection from library.

Provides intelligent node selection based on requirements, capabilities,
and user credentials. Used by the workflow builder to select appropriate nodes.
"""

from dataclasses import dataclass
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from src.config import settings
from src.models.node import NodeCategory, NodeDefinition

logger = structlog.get_logger()


class NodeSelectionError(Exception):
    """Error during node selection."""

    pass


@dataclass
class NodeMatch:
    """A matched node with confidence score."""

    node: NodeDefinition
    confidence: float  # 0.0 to 1.0
    reason: str


@dataclass
class SelectionResult:
    """Result of node selection."""

    matches: list[NodeMatch]
    query: str
    filters_applied: dict[str, Any]


class NodeSelector:
    """Intelligent node selector for workflow building.

    Selects appropriate nodes based on:
    - Natural language requirements
    - Available credentials
    - Node category filters
    - Capability matching

    Example usage:
        selector = NodeSelector(node_library)
        result = selector.select(
            query="send a message to slack",
            available_credentials=["slack_oauth"],
            category_filter=NodeCategory.MCP
        )
    """

    def __init__(
        self,
        node_catalog: list[NodeDefinition],
        model: str | None = None,
    ) -> None:
        """Initialize the node selector.

        Args:
            node_catalog: Available nodes
            model: LLM model for semantic matching
        """
        self.node_catalog = node_catalog
        self.model = model or settings.default_model

        self._llm = ChatOpenAI(
            model=self.model,
            temperature=0.0,
            api_key=settings.openai_api_key.get_secret_value(),
        )

    def select(
        self,
        query: str,
        available_credentials: list[str] | None = None,
        category_filter: NodeCategory | None = None,
        max_results: int = 5,
        include_unavailable: bool = False,
    ) -> SelectionResult:
        """Select nodes matching a query.

        Args:
            query: Natural language description of needed capability
            available_credentials: User's available credential types
            category_filter: Only return nodes of this category
            max_results: Maximum number of nodes to return
            include_unavailable: Include nodes requiring missing credentials

        Returns:
            SelectionResult with matched nodes
        """
        available_credentials = available_credentials or []

        # Apply filters
        filtered_nodes = self._apply_filters(
            nodes=self.node_catalog,
            category_filter=category_filter,
            available_credentials=available_credentials,
            include_unavailable=include_unavailable,
        )

        # Score nodes against query
        matches = self._score_nodes(query, filtered_nodes)

        # Sort by confidence and limit
        matches.sort(key=lambda m: m.confidence, reverse=True)
        matches = matches[:max_results]

        logger.debug(
            "node_selection_completed",
            query=query[:50],
            total_nodes=len(self.node_catalog),
            filtered_nodes=len(filtered_nodes),
            matches=len(matches),
        )

        return SelectionResult(
            matches=matches,
            query=query,
            filters_applied={
                "category": category_filter.value if category_filter else None,
                "available_credentials": available_credentials,
                "include_unavailable": include_unavailable,
            },
        )

    def select_by_capability(
        self,
        capability: str,
        available_credentials: list[str] | None = None,
    ) -> NodeDefinition | None:
        """Select a single best node for a capability.

        Args:
            capability: Required capability (e.g., "send_slack_message")
            available_credentials: Available credential types

        Returns:
            Best matching node or None
        """
        result = self.select(
            query=capability,
            available_credentials=available_credentials,
            max_results=1,
        )

        if result.matches and result.matches[0].confidence >= 0.5:
            return result.matches[0].node
        return None

    def get_nodes_by_category(
        self,
        category: NodeCategory,
        available_credentials: list[str] | None = None,
    ) -> list[NodeDefinition]:
        """Get all nodes in a category.

        Args:
            category: Node category
            available_credentials: Filter by available credentials

        Returns:
            List of matching nodes
        """
        nodes = [n for n in self.node_catalog if n.category == category]

        if available_credentials is not None:
            nodes = [
                n
                for n in nodes
                if n.credential_type is None
                or n.credential_type in available_credentials
            ]

        return nodes

    def get_nodes_for_mcp_server(self, mcp_server_id: str) -> list[NodeDefinition]:
        """Get all nodes for a specific MCP server.

        Args:
            mcp_server_id: MCP server identifier

        Returns:
            List of nodes for that server
        """
        return [n for n in self.node_catalog if n.mcp_server_id == mcp_server_id]

    def _apply_filters(
        self,
        nodes: list[NodeDefinition],
        category_filter: NodeCategory | None,
        available_credentials: list[str],
        include_unavailable: bool,
    ) -> list[NodeDefinition]:
        """Apply filters to node list."""
        result = list(nodes)

        # Filter by category
        if category_filter:
            result = [n for n in result if n.category == category_filter]

        # Filter by credential availability
        if not include_unavailable:
            result = [
                n
                for n in result
                if n.credential_type is None
                or n.credential_type in available_credentials
            ]

        # Exclude deprecated nodes
        result = [n for n in result if not n.deprecated]

        return result

    def _score_nodes(
        self,
        query: str,
        nodes: list[NodeDefinition],
    ) -> list[NodeMatch]:
        """Score nodes against a query using keyword matching.

        This is a simple implementation - could be enhanced with
        embeddings or LLM-based scoring for better accuracy.
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        matches = []
        for node in nodes:
            score = 0.0
            reasons = []

            # Name match (highest weight)
            if node.name.lower() in query_lower:
                score += 0.4
                reasons.append("name match")
            elif any(word in node.name.lower() for word in query_words):
                score += 0.2
                reasons.append("partial name match")

            # Description match
            desc_lower = node.description.lower()
            matching_words = sum(1 for word in query_words if word in desc_lower)
            if matching_words > 0:
                desc_score = min(0.3, matching_words * 0.1)
                score += desc_score
                reasons.append(f"description match ({matching_words} words)")

            # Tag match
            if node.tags:
                matching_tags = sum(
                    1 for tag in node.tags if tag.lower() in query_lower
                )
                if matching_tags > 0:
                    score += min(0.2, matching_tags * 0.1)
                    reasons.append(f"tag match ({matching_tags} tags)")

            # Category relevance
            category_keywords = {
                NodeCategory.TOOL: ["calculate", "transform", "process", "convert"],
                NodeCategory.API: ["api", "request", "fetch", "call"],
                NodeCategory.MCP: ["slack", "github", "file", "message"],
            }
            for cat, keywords in category_keywords.items():
                if node.category == cat and any(k in query_lower for k in keywords):
                    score += 0.1
                    reasons.append(f"category relevance ({cat.value})")

            if score > 0:
                matches.append(
                    NodeMatch(
                        node=node,
                        confidence=min(1.0, score),
                        reason="; ".join(reasons),
                    )
                )

        return matches

    async def select_with_llm(
        self,
        query: str,
        available_credentials: list[str] | None = None,
        max_results: int = 5,
    ) -> SelectionResult:
        """Select nodes using LLM for better semantic understanding.

        More accurate but slower than keyword-based selection.

        Args:
            query: Natural language query
            available_credentials: Available credential types
            max_results: Maximum results to return

        Returns:
            SelectionResult with LLM-scored matches
        """
        available_credentials = available_credentials or []

        # Filter available nodes
        filtered_nodes = self._apply_filters(
            nodes=self.node_catalog,
            category_filter=None,
            available_credentials=available_credentials,
            include_unavailable=False,
        )

        if not filtered_nodes:
            return SelectionResult(
                matches=[],
                query=query,
                filters_applied={"available_credentials": available_credentials},
            )

        # Build prompt
        node_list = "\n".join(
            f"- {n.name}: {n.description}" for n in filtered_nodes
        )

        prompt = f"""Given this user request: "{query}"

Select the most relevant nodes from this list (return node names in order of relevance):

{node_list}

Return a JSON array of objects with "name" and "reason" fields, ordered by relevance.
Example: [{{"name": "node_name", "reason": "why this node matches"}}]
"""

        try:
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            import json

            selections = json.loads(response.content)

            matches = []
            for i, sel in enumerate(selections[:max_results]):
                node = next(
                    (n for n in filtered_nodes if n.name == sel["name"]), None
                )
                if node:
                    matches.append(
                        NodeMatch(
                            node=node,
                            confidence=1.0 - (i * 0.1),  # Decreasing confidence
                            reason=sel.get("reason", "LLM selected"),
                        )
                    )

            return SelectionResult(
                matches=matches,
                query=query,
                filters_applied={"available_credentials": available_credentials},
            )

        except Exception as e:
            logger.warning(
                "llm_selection_failed",
                error=str(e),
                falling_back="keyword_selection",
            )
            # Fall back to keyword-based selection
            return self.select(
                query=query,
                available_credentials=available_credentials,
                max_results=max_results,
            )
