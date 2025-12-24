#!/usr/bin/env python3
"""
Test Notion OAuth flow via terminal.

Usage:
1. Start backend: uvicorn src.main:app --reload
2. Run this script: python test_notion_oauth.py
3. Open the URL in browser and authorize
4. Check the terminal for success
"""

import asyncio
import httpx
import json
from urllib.parse import parse_qs, urlparse


BASE_URL = "http://localhost:8000/api/v1"


async def main():
    print("=" * 60)
    print("Notion OAuth Flow - Terminal Test")
    print("=" * 60)
    print()

    async with httpx.AsyncClient() as client:
        # Step 1: Register or login
        print("Step 1: Register/Login User")
        print("-" * 60)

        # Try to register
        email = input("Enter email for test user: ").strip()
        password = input("Enter password: ").strip()

        try:
            response = await client.post(
                f"{BASE_URL}/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "full_name": "Test User"
                }
            )
            if response.status_code == 201:
                data = response.json()
                token = data["access_token"]
                print(f"✓ User registered successfully")
            else:
                # Try login instead
                response = await client.post(
                    f"{BASE_URL}/auth/login",
                    json={
                        "email": email,
                        "password": password
                    }
                )
                if response.status_code == 200:
                    data = response.json()
                    token = data["access_token"]
                    print(f"✓ User logged in successfully")
                else:
                    print(f"✗ Error: {response.text}")
                    return
        except Exception as e:
            print(f"✗ Error: {e}")
            return

        print(f"  Token: {token[:20]}...")
        print()

        # Step 2: Get authorization URL
        print("Step 2: Get Notion Authorization URL")
        print("-" * 60)

        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(
            f"{BASE_URL}/oauth/notion/authorize",
            headers=headers
        )

        if response.status_code != 200:
            print(f"✗ Error getting auth URL: {response.text}")
            return

        auth_data = response.json()
        auth_url = auth_data["authorization_url"]
        state = auth_data["state"]

        print(f"✓ Authorization URL generated")
        print(f"  State: {state}")
        print()

        # Step 3: User authorizes in browser
        print("Step 3: Authorize in Browser")
        print("-" * 60)
        print("Open this URL in your browser:")
        print()
        print(auth_url)
        print()
        print("After authorizing, Notion will redirect to:")
        print("https://hiklik.ai/api/v1/oauth/notion/callback?code=XXX&state=YYY")
        print()
        print("Since you're testing locally, the redirect will fail.")
        print("Copy the FULL redirect URL from browser address bar and paste here:")
        print()

        callback_url = input("Paste redirect URL: ").strip()

        # Parse the callback URL
        parsed = urlparse(callback_url)
        params = parse_qs(parsed.query)

        if "code" not in params:
            print("✗ No code found in URL")
            return

        code = params["code"][0]
        callback_state = params["state"][0]

        print(f"✓ Code extracted: {code[:20]}...")
        print()

        # Step 4: Manually call callback endpoint
        print("Step 4: Exchange Code for Tokens")
        print("-" * 60)

        # Call callback endpoint (simulating what Notion redirect does)
        response = await client.get(
            f"{BASE_URL}/oauth/notion/callback",
            params={
                "code": code,
                "state": callback_state
            },
            follow_redirects=False
        )

        print(f"  Response status: {response.status_code}")

        if response.status_code == 302:
            redirect_url = response.headers.get("location", "")
            if "success=true" in redirect_url:
                print("✓ OAuth flow completed successfully!")
                print(f"  Redirect: {redirect_url}")
            else:
                print(f"✗ OAuth failed")
                print(f"  Redirect: {redirect_url}")
                return
        else:
            print(f"✗ Unexpected response: {response.text}")
            return

        print()

        # Step 5: Verify credential saved
        print("Step 5: Verify Credential Saved")
        print("-" * 60)

        response = await client.get(
            f"{BASE_URL}/oauth/notion/status",
            headers=headers
        )

        if response.status_code == 200:
            status = response.json()
            print(f"✓ Connection status:")
            print(f"  Provider: {status['provider']}")
            print(f"  Connected: {status['connected']}")
            if status['connected']:
                print(f"  Credential ID: {status['credential']['id']}")
                print(f"  Credential Name: {status['credential']['name']}")
                print(f"  Created: {status['credential']['created_at']}")
        else:
            print(f"✗ Error checking status: {response.text}")
            return

        print()

        # Step 6: List all credentials
        print("Step 6: List All Credentials")
        print("-" * 60)

        response = await client.get(
            f"{BASE_URL}/credentials",
            headers=headers
        )

        if response.status_code == 200:
            credentials = response.json()
            print(f"✓ Total credentials: {len(credentials)}")
            for cred in credentials:
                print(f"  - {cred['name']} ({cred['credential_type']})")

        print()
        print("=" * 60)
        print("Test Complete!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
