#!/usr/bin/env python
"""Test Notion MCP server directly."""

import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DATABASE_URL', 'sqlite+aiosqlite:///kk_exec.db')

async def main():
    import sqlite3
    from src.core.encryption import CredentialEncryption
    from src.config import settings

    # Get token
    conn = sqlite3.connect('kk_exec.db')
    cursor = conn.execute('SELECT encrypted_data FROM credential WHERE credential_type = "notion_oauth"')
    row = cursor.fetchone()
    conn.close()

    enc = CredentialEncryption(settings.encryption_key.get_secret_value())
    data = enc.decrypt(row[0])
    token = data['access_token']
    print(f"Token: {token[:20]}...")

    # Test MCP
    from mcp.client.stdio import stdio_client, StdioServerParameters
    from mcp import ClientSession

    params = StdioServerParameters(
        command='npx',
        args=['-y', '@notionhq/notion-mcp-server'],
        env={'NOTION_TOKEN': token, 'PATH': os.environ.get('PATH', '')},
    )

    print("Starting Notion MCP server...")

    try:
        async with asyncio.timeout(60):
            async with stdio_client(params) as (read, write):
                print("Connected! Initializing session...")
                session = ClientSession(read, write)
                await session.initialize()
                print("Initialized! Listing tools...")

                tools = await session.list_tools()
                print(f"\nAvailable tools ({len(tools.tools)}):")
                for tool in tools.tools:
                    print(f"  - {tool.name}: {tool.description[:60] if tool.description else ''}...")

    except asyncio.TimeoutError:
        print("ERROR: Timed out after 60 seconds")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
