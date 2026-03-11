#!/usr/bin/env python3
"""
Create the incident.bot user in ServiceNow PDI with roles needed for full incident management:
create, read, update, resolve, close incidents via REST API.

Requires admin credentials. Run this ONCE after provisioning a new PDI.

Usage:
    Set in .env or environment:
      SERVICENOW_INSTANCE_URL  (e.g. https://dev362725.service-now.com)
      SERVICENOW_ADMIN_USER    (default: admin)
      SERVICENOW_ADMIN_PASSWORD

    python create_incident_bot_user.py

The script creates user incident.bot with password from SERVICENOW_PASSWORD (or prompts).
Roles assigned: itil, admin (for full incident + API access).
"""

import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

BASE_URL = os.getenv("SERVICENOW_INSTANCE_URL", "").rstrip("/")
ADMIN_USER = os.getenv("SERVICENOW_ADMIN_USER", os.getenv("SERVICENOW_ADMIN_USERNAME", "admin"))
ADMIN_PASS = os.getenv("SERVICENOW_ADMIN_PASSWORD", "")
BOT_USER = os.getenv("SERVICENOW_USERNAME", "incident.bot")
BOT_PASS = os.getenv("SERVICENOW_PASSWORD", "")

# Roles needed: itil (incident CRUD, resolve, close), admin (full API access in PDI)
ROLES_TO_ASSIGN = ["itil", "admin"]


def get_session():
    auth = (ADMIN_USER, ADMIN_PASS)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    return auth, headers


def get_role_sys_id(role_name: str, auth, headers) -> str | None:
    """Look up role sys_id by name."""
    url = f"{BASE_URL}/api/now/table/sys_user_role"
    params = {"sysparm_query": f"name={role_name}", "sysparm_fields": "sys_id,name"}
    resp = requests.get(url, auth=auth, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("result", [])
    return results[0]["sys_id"] if results else None


def user_exists(user_name: str, auth, headers) -> str | None:
    """Check if user exists; return sys_id if so."""
    url = f"{BASE_URL}/api/now/table/sys_user"
    params = {"sysparm_query": f"user_name={user_name}", "sysparm_fields": "sys_id,user_name"}
    resp = requests.get(url, auth=auth, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("result", [])
    return results[0]["sys_id"] if results else None


def create_user(user_name: str, password: str, auth, headers) -> str:
    """Create user; return sys_id."""
    url = f"{BASE_URL}/api/now/table/sys_user"
    payload = {
        "user_name": user_name,
        "first_name": "Incident",
        "last_name": "Bot",
        "email": f"{user_name}@example.com",
        "active": "true",
    }
    resp = requests.post(url, auth=auth, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json().get("result", {})
    return result["sys_id"]


def update_user_password(user_sys_id: str, password: str, auth, headers) -> None:
    """
    Set user password via PATCH. CRITICAL: sysparm_input_display_value=true
    is required so ServiceNow properly encrypts the password. Without it,
    the password is stored incorrectly and the user cannot authenticate (401).
    """
    url = f"{BASE_URL}/api/now/table/sys_user/{user_sys_id}"
    params = {"sysparm_input_display_value": "true"}
    payload = {"user_password": password}
    resp = requests.patch(
        url, auth=auth, headers=headers, json=payload, params=params, timeout=30
    )
    resp.raise_for_status()


def assign_role(user_sys_id: str, role_sys_id: str, auth, headers):
    """Add user to role via sys_user_has_role."""
    url = f"{BASE_URL}/api/now/table/sys_user_has_role"
    payload = {"user": user_sys_id, "role": role_sys_id}
    resp = requests.post(url, auth=auth, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()


def main():
    if not BASE_URL:
        print("Error: SERVICENOW_INSTANCE_URL not set in .env")
        sys.exit(1)
    if not ADMIN_PASS:
        print("Error: SERVICENOW_ADMIN_PASSWORD not set in .env")
        sys.exit(1)
    if not BOT_PASS:
        print("Error: SERVICENOW_PASSWORD not set in .env (used as incident.bot password)")
        sys.exit(1)

    auth, headers = get_session()

    print(f"Instance: {BASE_URL}")
    print(f"Creating user: {BOT_USER}")
    print()

    # Check if user already exists
    existing = user_exists(BOT_USER, auth, headers)
    if existing:
        print(f"User {BOT_USER} already exists (sys_id={existing})")
        print("Resetting password to match .env (required for REST auth)...")
        user_sys_id = existing
        update_user_password(user_sys_id, BOT_PASS, auth, headers)
        print("  Password updated.")
        print("Assigning roles if missing...")
    else:
        user_sys_id = create_user(BOT_USER, BOT_PASS, auth, headers)
        print(f"Created user {BOT_USER} (sys_id={user_sys_id})")
        print("Setting password...")
        update_user_password(user_sys_id, BOT_PASS, auth, headers)
        print("  Password set.")

    # Assign roles
    for role_name in ROLES_TO_ASSIGN:
        role_sys_id = get_role_sys_id(role_name, auth, headers)
        if not role_sys_id:
            print(f"  Warning: Role '{role_name}' not found, skipping")
            continue
        try:
            assign_role(user_sys_id, role_sys_id, auth, headers)
            print(f"  Assigned role: {role_name}")
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 409:
                print(f"  Role {role_name} already assigned")
            else:
                raise

    print()
    print("Done. Update .env with:")
    print(f"  SERVICENOW_INSTANCE_URL={BASE_URL}")
    print(f"  SERVICENOW_USERNAME={BOT_USER}")
    print(f"  SERVICENOW_PASSWORD=<your password>")


if __name__ == "__main__":
    main()
