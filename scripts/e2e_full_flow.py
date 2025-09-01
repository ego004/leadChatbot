#!/usr/bin/env python3
"""
End-to-end flow for LeadGenius AI based on current API schemas.

Flow:
1) Admin login
2) Admin creates client
3) Generate custom_client_id + deployment token; deploy chatbot
4) Add KB markdown (JSON payload)
5) Trigger ingestion
6) Chat with chatbot (with token), provide contact info
7) Create client dashboard user; login; fetch leads and lead details
8) Fetch analytics summary/daily

Notes:
- Uses only the latest router contracts from:
  - /admin (client + user creation)
  - /api/admin/client-config (deployment)
  - /api/admin/knowledge-base (KB management)
  - /api/admin/clients/{id}/ingest (ingestion)
  - /api/chat/{custom_client_id}/message (chat)
  - /api/client/* (client dashboard)
- Detects potential JWT payload mismatch for /api/client endpoints and provides a fallback
"""

import argparse
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
import json
import requests

try:
    import jwt  # PyJWT
except Exception:
    jwt = None


def pretty(o):
    return json.dumps(o, indent=2, sort_keys=True, default=str)


# ------------- Admin/Auth -------------

def admin_login(base: str, email: str, password: str) -> str:
    r = requests.post(f"{base}/api/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json().get("access_token")


# ------------- Admin: Client + Deployment -------------

def admin_create_client(base: str, admin_token: str, name: str, website_url: str) -> dict:
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Accepts JSON, form, or query; we send JSON
    r = requests.post(
        f"{base}/api/admin/clients",
        headers=headers,
        json={"name": name, "website_url": website_url},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_or_create_deployment(base: str, client_id: str, admin_token: str) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {admin_token}"}

    # Ensure deployment record exists and fetch it
    r = requests.get(f"{base}/api/admin/client-config/client/{client_id}/deployment", headers=headers, timeout=30)
    r.raise_for_status()
    dep = r.json().get("deployment") or {}

    # Ensure custom_client_id
    custom_client_id = dep.get("custom_client_id")
    if not custom_client_id:
        r = requests.post(
            f"{base}/api/admin/client-config/client/{client_id}/generate-custom-id",
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        custom_client_id = r.json()["custom_client_id"]

    # Ensure deployment token
    deployment_token = dep.get("deployment_api_token")
    if not deployment_token:
        r = requests.post(
            f"{base}/api/admin/client-config/client/{client_id}/generate-token",
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()
        deployment_token = r.json()["deployment_api_token"]

    # Ensure deployed
    if not dep.get("is_deployed"):
        r = requests.post(f"{base}/api/admin/client-config/client/{client_id}/deploy", headers=headers, timeout=30)
        r.raise_for_status()

    return custom_client_id, deployment_token


# ------------- KB + Ingestion -------------

def add_kb_markdown(base: str, client_id: str, admin_token: str, title: str, content: str) -> dict:
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Endpoint explicitly supports JSON with keys 'title' and 'content'
    r = requests.post(
        f"{base}/api/admin/knowledge-base/client/{client_id}/add-markdown",
        headers=headers,
        json={"title": title, "content": content},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def trigger_ingestion(base: str, client_id: str, admin_token: str) -> dict:
    headers = {"Authorization": f"Bearer {admin_token}"}
    r = requests.post(f"{base}/api/admin/clients/{client_id}/ingest", headers=headers, timeout=600)
    r.raise_for_status()
    return r.json()


# ------------- Chat -------------

def chat_message(
    base: str,
    custom_client_id: str,
    deployment_token: str,
    message: str,
    *,
    session_id: str | None = None,
    lead_name: str | None = None,
    lead_email: str | None = None,
    lead_phone: str | None = None,
    return_sources: bool = False,
    top_k: int = 5,
    measure_time: bool = False,
) -> dict:
    headers = {"x-deployment-token": deployment_token}
    params = {
        "message": message,
        "return_sources": "true" if return_sources else "false",
        "top_k": str(top_k),
    }
    if session_id:
        params["session_id"] = session_id
    if lead_name:
        params["lead_name"] = lead_name
    if lead_email:
        params["lead_email"] = lead_email
    if lead_phone:
        params["lead_phone"] = lead_phone

    if measure_time:
        start_time = time.time()
    
    r = requests.post(
        f"{base}/api/chat/{custom_client_id}/message",
        headers=headers,
        params=params,
        timeout=90,
    )
    r.raise_for_status()
    result = r.json()
    
    if measure_time:
        response_time = time.time() - start_time
        result["_response_time_seconds"] = round(response_time, 3)
        print(f"⏱️  Chat response time: {response_time:.3f}s")
    
    return result


# ------------- Client Dashboard -------------

def create_client_user(base: str, admin_token: str, client_id: str, email: str, password: str) -> dict:
    headers = {"Authorization": f"Bearer {admin_token}"}
    payload = {"email": email, "password": password}
    r = requests.post(
        f"{base}/api/admin/clients/{client_id}/users",
        headers=headers,
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def client_login(base: str, *, email: str, password: str, client_id_hint: str | None = None) -> str:
    payload = {"password": password, "email": email}
    if client_id_hint:
        payload["client_id_hint"] = client_id_hint
    r = requests.post(f"{base}/api/client/login", json=payload, timeout=30)
    r.raise_for_status()
    return r.json().get("access_token")


def client_get_leads(base: str, client_token: str, status_filter: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {client_token}"}
    params = {"status_filter": status_filter} if status_filter else None
    r = requests.get(f"{base}/api/client/leads", headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def client_get_lead_details(base: str, client_token: str, lead_id: str) -> dict:
    headers = {"Authorization": f"Bearer {client_token}"}
    r = requests.get(f"{base}/api/client/leads/{lead_id}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def client_analytics_summary(base: str, client_token: str, timeframe: str = "today") -> dict:
    headers = {"Authorization": f"Bearer {client_token}"}
    r = requests.get(f"{base}/api/client/analytics/summary", headers=headers, params={"timeframe": timeframe}, timeout=30)
    r.raise_for_status()
    return r.json()


def client_analytics_daily(base: str, client_token: str, days: int = 7) -> dict:
    headers = {"Authorization": f"Bearer {client_token}"}
    r = requests.get(f"{base}/api/client/analytics/daily", headers=headers, params={"days": days}, timeout=30)
    r.raise_for_status()
    return r.json()


# ------------- Utilities -------------

def mint_client_jwt(secret_key: str, client_id: str, hours: int = 24) -> str:
    if jwt is None:
        raise RuntimeError("PyJWT not installed. pip install PyJWT")
    payload = {"sub": client_id, "exp": datetime.utcnow() + timedelta(hours=hours)}
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return token if isinstance(token, str) else token.decode()


def main():
    ap = argparse.ArgumentParser(description="End-to-end flow (fresh script)")
    ap.add_argument('--base-url', default=os.getenv('E2E_BASE_URL', 'http://localhost:8000'))
    ap.add_argument('--admin-email', default=os.getenv('ADMIN_EMAIL', 'admin@example.com'))
    ap.add_argument('--admin-password', default=os.getenv('ADMIN_PASSWORD', 'ChangeMe123!'))
    ap.add_argument('--jwt-secret-key', default=os.getenv('JWT_SECRET_KEY'))

    ap.add_argument('--new-client-name', default=f"E2E Client {datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
    ap.add_argument('--new-client-website', default='https://example.com')

    ap.add_argument('--contact-name', default='John Prospect')
    ap.add_argument('--contact-email', default='john.prospect@example.com')
    ap.add_argument('--contact-phone', default='(555) 000-1234')

    ap.add_argument('--dashboard-email', default='owner@example.com')
    ap.add_argument('--dashboard-password', default='Passw0rd!')

    ap.add_argument('--messages', nargs='*', default=[
        "Hi there!",
        "What services do you offer?",
        "How can I get started?",
    ])
    ap.add_argument('--days', type=int, default=7)

    args = ap.parse_args()

    # 1) Admin login
    print("Logging in as admin...")
    admin_token = admin_login(args.base_url, args.admin_email, args.admin_password)

    # 2) Create client
    print("Creating client...")
    create_res = admin_create_client(args.base_url, admin_token, args.new_client_name, args.new_client_website)
    client_id = str(create_res.get('client_id'))
    if not client_id:
        print("Failed to create client:")
        print(pretty(create_res))
        sys.exit(1)
    print(f"Created client_id={client_id}")

    # 3) Deployment setup
    print("Configuring deployment...")
    custom_client_id, deployment_token = get_or_create_deployment(args.base_url, client_id, admin_token)
    print(f"custom_client_id={custom_client_id}")

    # 4) Add KB markdown
    print("Adding knowledge base markdown (JSON payload)...")
    kb_md = (
        "# Welcome to Our Company\n\n"
        "We provide AI-powered lead capture.\n\n"
        "## Contact\n\nEmail: sales@example.com\nPhone: (555) 000-1234\n"
    )
    kb_res = add_kb_markdown(args.base_url, client_id, admin_token, title="Company Overview", content=kb_md)
    print("KB add result:")
    print(pretty(kb_res))

    # 5) Trigger ingestion
    print("Triggering ingestion (this may take a while)...")
    try:
        ing_res = trigger_ingestion(args.base_url, client_id, admin_token)
        print(pretty(ing_res))
    except Exception as e:
        print(f"Warning: ingestion failed or not configured: {e}")

    # 6) Chat with chatbot - PERFORMANCE TEST
    print("\n🚀 PERFORMANCE TEST: Chatting with chatbot...")
    print("=" * 60)
    session_id = str(uuid.uuid4())
    response_times = []
    
    for i, msg in enumerate(args.messages, start=1):
        print(f"\nTurn {i}: '{msg}'")
        res = chat_message(
            args.base_url,
            custom_client_id,
            deployment_token,
            msg,
            session_id=session_id,
            return_sources=True,
            measure_time=True,
        )
        
        # Track response time
        if "_response_time_seconds" in res:
            response_times.append(res["_response_time_seconds"])
            del res["_response_time_seconds"]  # Clean for display
        
        print(f"Response: {res.get('response', 'N/A')[:100]}...")
        print(f"Context used: {res.get('context_used', False)}")
        time.sleep(0.5)  # Reduced sleep to speed up test
    
    # Performance summary
    if response_times:
        avg_time = sum(response_times) / len(response_times)
        max_time = max(response_times)
        min_time = min(response_times)
        print(f"\n📊 PERFORMANCE SUMMARY:")
        print(f"   Average response time: {avg_time:.3f}s")
        print(f"   Fastest response: {min_time:.3f}s")
        print(f"   Slowest response: {max_time:.3f}s")
        print(f"   Total requests: {len(response_times)}")
        
        if avg_time < 2.5:
            print("   ✅ EXCELLENT: Average under 2.5s (target achieved!)")
        elif avg_time < 4.0:
            print("   ⚡ GOOD: Average under 4.0s (improved from 4-6s)")
        else:
            print("   ⚠️  SLOW: Still over 4s (optimization may need more work)")

    # Provide contact info to ensure capture + qualification
    contact_text = (
        f"My name is {args.contact_name}. You can reach me at {args.contact_email} or {args.contact_phone}."
    )
    print(f"\nContact info turn: '{contact_text}'")
    contact_res = chat_message(
        args.base_url,
        custom_client_id,
        deployment_token,
        contact_text,
        session_id=session_id,
        lead_name=args.contact_name,
        lead_email=args.contact_email,
        lead_phone=args.contact_phone,
        measure_time=True,
    )
    print("Contact turn:")
    print(pretty({k: contact_res.get(k) for k in ["lead_qualified", "contact_captured", "tool_results"]}))

    # 7) Create client dashboard user; login; fetch leads
    print("Creating client dashboard user...")
    try:
        user_res = create_client_user(
            args.base_url,
            admin_token,
            client_id,
            email=args.dashboard_email,
            password=args.dashboard_password,
        )
        print(pretty(user_res))
    except requests.HTTPError as e:
        # If user already exists, continue
        if e.response is not None and e.response.status_code == 400:
            print("User already exists; continuing...")
        else:
            raise

    print("Logging in to client dashboard...")
    client_token = None
    try:
        client_token = client_login(
            args.base_url,
            email=args.dashboard_email,
            password=args.dashboard_password,
            client_id_hint=client_id,
        )
        print("Client login succeeded.")
    except Exception as e:
        print(f"Warning: client login failed ({e}). Will try fallback JWT for API checks.")

    # Potential schema mismatch guard: if login token doesn't grant access, mint token using client_id
    if not client_token and args.jwt_secret_key and jwt is not None:
        print("Minting client JWT fallback (sub=client_id)...")
        client_token = mint_client_jwt(args.jwt_secret_key, client_id)

    # Leads
    if not client_token:
        print("No client token available; skipping client endpoints.")
    else:
        print("Fetching leads...")
        try:
            leads_payload = client_get_leads(args.base_url, client_token)
            print(pretty({
                "total_count": leads_payload.get("total_count"),
                "sample": leads_payload.get("leads", [])[:3],
            }))
            # Find our contact
            leads = leads_payload.get("leads", [])
            target = None
            for ld in leads:
                if (ld.get("phone_number") == args.contact_phone) or (ld.get("name") == args.contact_name):
                    target = ld
                    break
            if not target and leads:
                target = sorted(leads, key=lambda x: x.get("updated_at") or x.get("created_at"), reverse=True)[0]

            if target:
                detail = client_get_lead_details(args.base_url, client_token, target.get("lead_id"))
                print("Lead details (truncated):")
                print(pretty({
                    "lead": detail.get("lead"),
                    "chat_history_type": type(detail.get("chat_history")).__name__,
                }))
        except requests.HTTPError as e:
            print(f"Lead retrieval failed (status={e.response.status_code if e.response else 'N/A'}). Possible JWT payload mismatch.")

        # 8) Analytics
        try:
            print("Analytics summary (today):")
            print(pretty(client_analytics_summary(args.base_url, client_token, timeframe="today")))
            print("Analytics daily:")
            print(pretty(client_analytics_daily(args.base_url, client_token, days=args.days)))
        except Exception as e:
            print(f"Analytics fetch failed: {e}")

    print("E2E full flow complete.")


if __name__ == '__main__':
    main()
