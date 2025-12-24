#!/usr/bin/env python
"""Test script for Notion workflow execution.

This script tests the complete flow:
1. User login
2. Workflow building from natural language
3. Workflow execution with Notion MCP
"""

import asyncio
import sys
from datetime import datetime, timezone

import httpx


BASE_URL = "http://localhost:9000"
USERNAME = "yaodong"
PASSWORD = "yaodong123"
REQUEST_TIMEOUT = 120.0  # Increase timeout for MCP server initialization


async def test_notion_flow():
    """Test complete Notion workflow flow."""

    print("\n" + "=" * 60)
    print(f"Command: Create Notion page Test123")
    print(f"User: {USERNAME}")
    print("=" * 60 + "\n")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=REQUEST_TIMEOUT) as client:
        # 1. Login
        print("1. Logging in...")
        response = await client.post("/api/v1/auth/login", json={
            "username": USERNAME,
            "password": PASSWORD
        })

        if response.status_code != 200:
            print(f"✗ Login failed: {response.status_code} {response.text}")
            return False

        auth_data = response.json()
        token = auth_data["access_token"]
        print(f"✓ Logged in")

        headers = {"Authorization": f"Bearer {token}"}

        # 2. Check credentials
        print("\n2. Checking credentials...")
        response = await client.get("/api/v1/credentials", headers=headers)

        if response.status_code != 200:
            print(f"✗ Failed to get credentials: {response.status_code}")
            return False

        creds = response.json()
        print(f"   Found {len(creds)} credentials:")
        for cred in creds:
            print(f"   - {cred['name']} ({cred['credential_type']})")

        notion_cred = next((c for c in creds if c["credential_type"] == "notion_oauth"), None)
        if not notion_cred:
            print("✗ No Notion credential found")
            return False
        print("✓ Notion credential available")

        # 3. Build workflow
        print("\n3. Building workflow from natural language...")
        response = await client.post("/api/v1/workflows/build", headers=headers, json={
            "prompt": "Create a Notion page called 'Test from KK_exec' with content 'Hello World'"
        })

        if response.status_code not in (200, 201):
            print(f"✗ Failed to build workflow: {response.status_code}")
            print(response.text)
            return False

        workflow = response.json()
        workflow_id = workflow["id"]
        print(f"✓ Workflow built: {workflow_id}")
        print(f"   Name: {workflow['name']}")
        print(f"   Nodes: {len(workflow.get('graph', {}).get('nodes', []))}")

        # 4. Execute workflow
        print("\n4. Executing workflow...")
        response = await client.post("/api/v1/executions", headers=headers, json={
            "workflow_id": workflow_id,
            "input_data": {
                "command": "Create Notion page Test123"
            }
        })

        if response.status_code not in (200, 201):
            print(f"✗ Failed to start execution: {response.status_code}")
            print(response.text)
            return False

        execution = response.json()
        execution_id = execution["id"]
        print(f"✓ Execution started: {execution_id}")

        # 5. Poll for completion
        print("\n5. Waiting for execution to complete...")
        max_polls = 30
        for i in range(max_polls):
            await asyncio.sleep(1)

            response = await client.get(f"/api/v1/executions/{execution_id}", headers=headers)

            if response.status_code != 200:
                print(f"✗ Failed to get execution status: {response.status_code}")
                return False

            execution = response.json()
            status = execution["status"]
            print(f"   [{i+1}/{max_polls}] Status: {status}")

            if status == "completed":
                print("\n" + "=" * 60)
                print("EXECUTION COMPLETED SUCCESSFULLY")
                print("=" * 60)
                print(f"Output: {execution.get('output_data')}")
                return True

            if status == "failed":
                print("\n" + "=" * 60)
                print("EXECUTION FAILED")
                print("=" * 60)
                print(f"Error: {execution.get('error')}")
                print(f"Error code: {execution.get('error_code')}")
                return False

        print("✗ Execution timed out")
        return False


if __name__ == "__main__":
    success = asyncio.run(test_notion_flow())
    sys.exit(0 if success else 1)
