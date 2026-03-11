#!/usr/bin/env python3
"""
Ensure incident.bot has ACLs for full incident management (create, write, assignment fields).
Uses admin credentials to create/update ACLs and ensure incident.bot user + roles.

Run this when incident.bot gets 403 on create (especially with assignment_group/assigned_to).

Usage:
    Set in .env: SERVICENOW_INSTANCE_URL, SERVICENOW_ADMIN_USER, SERVICENOW_ADMIN_PASSWORD
    python ensure_incident_bot_acls.py

Then run: python seed_incidents_sop.py --delete-first
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

ROLES = ["itil", "admin"]


def get_session():
    auth = (ADMIN_USER, ADMIN_PASS)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    return auth, headers


def ensure_user_and_roles(auth, headers):
    """Ensure incident.bot exists and has itil + admin. Reuse create_incident_bot_user logic."""
    # Import and run create_incident_bot_user's main logic, or inline
    url = f"{BASE_URL}/api/now/table/sys_user"
    r = requests.get(url, auth=auth, headers=headers, params={"sysparm_query": f"user_name={BOT_USER}", "sysparm_fields": "sys_id"}, timeout=30)
    r.raise_for_status()
    results = r.json().get("result", [])
    if not results:
        print(f"  User {BOT_USER} does not exist. Run first: python create_incident_bot_user.py")
        return None
    return results[0]["sys_id"]


def ensure_roles(user_sys_id, auth, headers):
    """Ensure user has itil and admin."""
    for role_name in ROLES:
        r = requests.get(
            f"{BASE_URL}/api/now/table/sys_user_role",
            auth=auth, headers=headers,
            params={"sysparm_query": f"name={role_name}", "sysparm_fields": "sys_id"},
            timeout=30
        )
        r.raise_for_status()
        roles = r.json().get("result", [])
        if not roles:
            print(f"  Warning: Role '{role_name}' not found")
            continue
        role_sys_id = roles[0]["sys_id"]
        # Check if user has role
        r2 = requests.get(
            f"{BASE_URL}/api/now/table/sys_user_has_role",
            auth=auth, headers=headers,
            params={"sysparm_query": f"user={user_sys_id}^role={role_sys_id}", "sysparm_fields": "sys_id"},
            timeout=30
        )
        r2.raise_for_status()
        if not r2.json().get("result", []):
            payload = {"user": user_sys_id, "role": role_sys_id}
            requests.post(f"{BASE_URL}/api/now/table/sys_user_has_role", auth=auth, headers=headers, json=payload, timeout=30).raise_for_status()
            print(f"  Assigned role: {role_name}")
        else:
            print(f"  Role {role_name}: already assigned")


def query_acl(base_url, auth, name_pattern: str):
    """Query ACLs matching name pattern."""
    url = f"{base_url}/api/now/table/sys_security_acl"
    params = {"sysparm_query": f"nameLIKE{name_pattern}", "sysparm_fields": "sys_id,name,type,operation,active,script"}
    try:
        r = requests.get(url, auth=auth, headers={"Accept": "application/json"}, params=params, timeout=30)
        if r.status_code == 404 or "sys_security_acl" in str(r.text).lower() and "not found" in str(r.text).lower():
            return None
        r.raise_for_status()
        return r.json().get("result", [])
    except Exception as e:
        print(f"  ACL query failed: {e}")
        return None


def create_acl(base_url, auth, headers, name: str, acl_type: str, operation: str, script: str):
    """Create an ACL rule allowing itil (and admin) to perform operation on name."""
    url = f"{base_url}/api/now/table/sys_security_acl"
    payload = {
        "name": name,
        "type": acl_type,
        "operation": operation,
        "active": "true",
        "script": script,
        "description": f"Allow itil/admin for incident.bot - {name} {operation}",
    }
    try:
        r = requests.post(url, auth=auth, headers=headers, json=payload, timeout=30)
        if r.status_code == 409:
            print(f"  ACL {name} ({operation}) already exists")
            return True
        r.raise_for_status()
        print(f"  Created ACL: {name} ({operation})")
        return True
    except requests.HTTPError as e:
        print(f"  Failed to create ACL {name} ({operation}): {e}")
        if e.response is not None and e.response.text:
            print(f"    Response: {e.response.text[:200]}")
        return False


def main():
    if not BASE_URL:
        print("Error: SERVICENOW_INSTANCE_URL not set in .env")
        sys.exit(1)
    if not ADMIN_PASS:
        print("Error: SERVICENOW_ADMIN_PASSWORD not set in .env")
        sys.exit(1)

    auth, headers = get_session()
    print(f"Instance: {BASE_URL}")
    print(f"Ensuring {BOT_USER} and ACLs...\n")

    # 1. Ensure user exists
    user_sys_id = ensure_user_and_roles(auth, headers)
    if not user_sys_id:
        sys.exit(1)
    print(f"  User {BOT_USER}: OK (sys_id={user_sys_id})")

    # 2. Ensure roles
    ensure_roles(user_sys_id, auth, headers)

    # 3. Check if sys_security_acl is accessible
    acls = query_acl(BASE_URL, auth, "incident")
    if acls is None:
        print("\n  sys_security_acl table not accessible via REST (common in PDIs).")
        print("  Manual ACL setup in ServiceNow:")
        print("    1. Navigate to System Security > Access Control (ACL)")
        print("    2. For incident.assignment_group and incident.assigned_to:")
        print("       - Add 'itil' to the required roles, or")
        print("       - Create new ACL: Allow if script returns gs.hasRole('itil')")
        print("\n  Alternative: seed with admin (bypasses ACLs):")
        print("    python seed_incidents_sop.py --delete-first --use-admin")
        sys.exit(0)

    # 4. Create ACLs for incident create/write and assignment fields
    script_allow = "gs.hasRole('itil') || gs.hasRole('admin')"
    created = 0
    rules = [
        ("incident", "record", "create", script_allow),
        ("incident", "record", "write", script_allow),
        ("incident.assignment_group", "field", "write", script_allow),
        ("incident.assigned_to", "field", "write", script_allow),
    ]
    for name, acl_type, op, script in rules:
        if create_acl(BASE_URL, auth, headers, name, acl_type, op, script):
            created += 1

    print(f"\n  ACL setup complete ({created}/{len(rules)} rules).")
    if created == 0:
        print("\n  ACL creation blocked by ServiceNow. Use admin to seed (bypasses ACLs):")
        print("    python seed_incidents_sop.py --delete-first --use-admin")
    else:
        print("\nNext: python seed_incidents_sop.py --delete-first")


if __name__ == "__main__":
    main()
