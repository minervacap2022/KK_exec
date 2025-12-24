"""Tests for workflow API endpoints."""

import pytest
from httpx import AsyncClient

from src.models.workflow import Workflow, WorkflowStatus


class TestWorkflowEndpoints:
    """Tests for workflow CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_workflows_empty(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Test listing workflows when none exist."""
        response = await client.get("/api/v1/workflows", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_workflows_with_data(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_workflow: Workflow,
    ):
        """Test listing workflows with existing data."""
        response = await client.get("/api/v1/workflows", headers=auth_headers)

        assert response.status_code == 200
        workflows = response.json()
        assert len(workflows) == 1
        assert workflows[0]["id"] == test_workflow.id

    @pytest.mark.asyncio
    async def test_create_workflow(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Test creating a new workflow."""
        workflow_data = {
            "name": "My New Workflow",
            "description": "Test description",
            "graph": {
                "version": "1.0",
                "nodes": [
                    {"id": "node1", "type": "calculator", "config": {}, "position": {"x": 0, "y": 0}}
                ],
                "edges": [],
                "config": {},
            },
        }

        response = await client.post(
            "/api/v1/workflows",
            headers=auth_headers,
            json=workflow_data,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "My New Workflow"
        assert data["status"] == "draft"
        assert len(data["graph"]["nodes"]) == 1

    @pytest.mark.asyncio
    async def test_get_workflow(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_workflow: Workflow,
    ):
        """Test getting a specific workflow."""
        response = await client.get(
            f"/api/v1/workflows/{test_workflow.id}",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_workflow.id
        assert data["name"] == test_workflow.name

    @pytest.mark.asyncio
    async def test_get_workflow_not_found(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
    ):
        """Test getting a non-existent workflow."""
        response = await client.get(
            "/api/v1/workflows/non-existent-id",
            headers=auth_headers,
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_workflow(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_workflow: Workflow,
    ):
        """Test updating a workflow."""
        update_data = {
            "name": "Updated Workflow Name",
            "status": "active",
        }

        response = await client.put(
            f"/api/v1/workflows/{test_workflow.id}",
            headers=auth_headers,
            json=update_data,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Workflow Name"
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_delete_workflow(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        test_workflow: Workflow,
    ):
        """Test deleting a workflow."""
        response = await client.delete(
            f"/api/v1/workflows/{test_workflow.id}",
            headers=auth_headers,
        )

        assert response.status_code == 204

        # Verify deleted
        get_response = await client.get(
            f"/api/v1/workflows/{test_workflow.id}",
            headers=auth_headers,
        )
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_unauthenticated_request(self, client: AsyncClient):
        """Test that unauthenticated requests are rejected."""
        response = await client.get("/api/v1/workflows")

        assert response.status_code == 401
