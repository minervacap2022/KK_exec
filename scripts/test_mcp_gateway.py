#!/usr/bin/env python
"""Test MCP gateway connection and cleanup.

Tests the MCP gateway with proper context manager lifecycle.
"""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.mcp_gateway import MCPGateway


async def test_mcp_gateway():
    """Test MCP gateway connection and cleanup."""

    print("\n" + "=" * 60)
    print("MCP Gateway Test")
    print("=" * 60 + "\n")

    gateway = MCPGateway()

    # List available servers
    servers = gateway.list_servers()
    print(f"Available servers: {len(servers)}")
    for server in servers:
        print(f"  - {server.id}: {server.name} ({server.transport})")

    # Get notion server config
    notion_config = gateway.get_server("notion")
    if not notion_config:
        print("\nNotion server not configured!")
        return False

    print(f"\nNotion server config:")
    print(f"  Transport: {notion_config.transport}")
    print(f"  Command: {notion_config.command}")
    print(f"  Args: {notion_config.args}")
    print(f"  Credential type: {notion_config.credential_type}")

    # Try to connect with dummy credentials
    print("\n1. Testing connection with dummy credentials...")
    print("   (This will verify the MCP server starts and we can get tool list)")

    # Use a test token - this won't work for actual Notion calls
    # but should let us connect to the MCP server and list tools
    test_creds = {
        "access_token": "ntn_test_token_for_connection_test"
    }

    try:
        print("   Connecting to Notion MCP server using context manager...")

        async def connect_and_list():
            async with gateway.connection("notion", test_creds) as connection:
                print(f"   Connected! Tools available: {len(connection.tools)}")
                for tool in connection.tools:
                    desc = tool.description[:50] if tool.description else "(no description)"
                    print(f"     - {tool.name}: {desc}...")
                return True
            # Cleanup happens automatically when exiting context manager
            print("   Disconnected successfully (context manager cleanup)!")

        result = await asyncio.wait_for(connect_and_list(), timeout=60.0)
        return result

    except asyncio.TimeoutError:
        print("   ERROR: Connection timed out (60s)")
        return False

    except Exception as e:
        print(f"   ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_mcp_gateway())
    print("\n" + "=" * 60)
    print(f"Test {'PASSED' if success else 'FAILED'}")
    print("=" * 60 + "\n")
    sys.exit(0 if success else 1)
