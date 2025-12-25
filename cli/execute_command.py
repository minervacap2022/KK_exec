#!/usr/bin/env python3
"""
Natural language command executor.
LLM decides which MCPs to use based on user intent.
"""

import asyncio
import json
import sys
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


async def execute_natural_command(
    command: str,
    user_id: str,
    auth_token: str,
    api_url: str = "http://localhost:9000/api/v1",
) -> dict[str, Any]:
    """Execute natural language command.

    Args:
        command: Natural language command (e.g., "Create a page in Notion titled 'Meeting Notes'")
        user_id: User ID
        auth_token: JWT token from production auth
        api_url: KK_exec API URL

    Returns:
        Execution result
    """
    async with httpx.AsyncClient(timeout=300.0) as client:
        headers = {"Authorization": f"Bearer {auth_token}"}

        # Step 1: Get user's available credentials (what MCPs they can use)
        logger.info("fetching_user_credentials", user_id=user_id)
        creds_response = await client.get(
            f"{api_url}/credentials",
            headers=headers,
        )
        creds_response.raise_for_status()
        credentials = creds_response.json()

        logger.info(
            "credentials_fetched",
            count=len(credentials),
            types=[c["credential_type"] for c in credentials],
        )

        # Step 2: Build workflow from natural language
        # The LLM will analyze the command and available credentials
        # to decide which MCPs to use
        logger.info("building_workflow", command=command)

        build_payload = {
            "prompt": command,
            "user_context": {
                "user_id": user_id,
                "available_credentials": [
                    {
                        "type": c["credential_type"],
                        "mcp_server": c.get("mcp_server_id"),
                        "name": c["name"],
                    }
                    for c in credentials
                ],
            },
        }

        build_response = await client.post(
            f"{api_url}/workflows/build",
            headers=headers,
            json=build_payload,
        )
        build_response.raise_for_status()
        workflow = build_response.json()

        logger.info(
            "workflow_built",
            workflow_id=workflow.get("id"),
            nodes_count=len(workflow.get("graph", {}).get("nodes", [])),
            mcps_used=[
                node.get("mcp_server_id")
                for node in workflow.get("graph", {}).get("nodes", [])
                if node.get("mcp_server_id")
            ],
        )

        # Step 3: Execute workflow
        logger.info("executing_workflow", workflow_id=workflow.get("id"))

        exec_response = await client.post(
            f"{api_url}/executions",
            headers=headers,
            json={
                "workflow_id": workflow["id"],
                "input_data": {"command": command},
            },
        )
        exec_response.raise_for_status()
        execution = exec_response.json()

        logger.info(
            "execution_started",
            execution_id=execution["id"],
            status=execution["status"],
        )

        # Step 4: Poll for completion (or use streaming in production)
        execution_id = execution["id"]
        while True:
            status_response = await client.get(
                f"{api_url}/executions/{execution_id}",
                headers=headers,
            )
            status_response.raise_for_status()
            execution_status = status_response.json()

            status = execution_status["status"]
            logger.info("execution_status", status=status)

            if status in ["completed", "failed"]:
                return execution_status

            await asyncio.sleep(1)


async def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Execute natural language commands using available MCPs"
    )
    parser.add_argument("command", help="Natural language command")
    parser.add_argument("--user-id", required=True, help="User ID")
    parser.add_argument("--token", required=True, help="Auth token")
    parser.add_argument(
        "--api-url",
        default="http://localhost:9000/api/v1",
        help="API URL",
    )

    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"Command: {args.command}")
    print(f"User: {args.user_id}")
    print(f"{'=' * 60}\n")

    try:
        result = await execute_natural_command(
            command=args.command,
            user_id=args.user_id,
            auth_token=args.token,
            api_url=args.api_url,
        )

        print(f"\n{'=' * 60}")
        print("EXECUTION RESULT")
        print(f"{'=' * 60}")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print()

        if result["status"] == "completed":
            print("✓ Command executed successfully!")
            sys.exit(0)
        else:
            print("✗ Command failed")
            sys.exit(1)

    except Exception as e:
        logger.exception("execution_failed", error=str(e))
        print(f"\n✗ Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
