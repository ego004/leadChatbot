#!/usr/bin/env python3
"""
E2E: Create a large markdown KB for a gym, deploy chatbot, chat with it, and verify analytics.

Usage (requires admin auth for deployment + KB steps):
  python scripts/e2e_kb_chat_analytics.py \
    --base-url http://localhost:8000 \
    --client-id 12345678-1234-1234-1234-1234567890ab \
    --jwt-secret-key your-secret-key \
    --admin-token <bearer>

Or let the script create a client for you (will log in as admin):
  python scripts/e2e_kb_chat_analytics.py \
    --base-url http://localhost:8000 \
    --admin-email admin@example.com \
    --admin-password mypass \
    --jwt-secret-key your-secret-key

Optional:
  --custom-client-id <existing_custom_id>  (if already generated)
  --deployment-token <existing_token>      (if already set)
  --messages "Hi" "What are membership options?"

This script will:
- Ensure deployment exists (custom_client_id, token, deployed)
- Add a very large markdown entry to the client's KB (gym info)
- Send a chat message referencing KB content
- Verify analytics totals and daily series reflect the chat
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta
import json
import requests
import uuid

try:
    import jwt  # PyJWT
except Exception:
    jwt = None


# ----------------- Helpers -----------------

def pretty(o):
    return json.dumps(o, indent=2, sort_keys=True, default=str)


def mint_client_jwt(secret_key: str, client_id: str, hours: int = 24) -> str:
    if jwt is None:
        raise RuntimeError("PyJWT not installed. pip install PyJWT")
    payload = {"sub": client_id, "exp": datetime.utcnow() + timedelta(hours=hours)}
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    return token if isinstance(token, str) else token.decode()


def large_gym_markdown() -> str:
    # Generate ~100KB markdown by repeating realistic sections
    header = "# Titan Strength & Fitness — Member Handbook\n\n"
    sections = []
    base_section = (
        "## Membership Options\n\n"
        "- Basic: $29/mo — Access 5am-11pm, cardio + weights.\n"
        "- Plus: $49/mo — Includes classes (HIIT, Yoga, Spin).\n"
        "- Premium: $79/mo — Includes sauna, towel service, guest passes.\n\n"
        "## Hours\n\n"
        "- Staffed: Mon-Fri 6am-9pm, Sat-Sun 7am-7pm\n"
        "- 24/7 Access for Premium via key fob\n\n"
        "## Amenities\n\n"
        "- 40+ cardio machines, free weights to 150 lbs, power racks\n"
        "- Recovery: sauna, massage chairs, cold plunge (Premium)\n"
        "- Classes: HIIT, Yoga, Spin, Mobility, Bootcamp\n\n"
        "## Day Pass\n\n"
        "- $15/day, $40/3-day, apply to membership if you join within 7 days\n\n"
        "## Personal Training\n\n"
        "- Intro pack: 3 sessions for $149\n"
        "- Certified trainers with specialties (strength, fat loss, mobility)\n\n"
        "## Parking\n\n"
        "- 2 hours free with validation in the attached garage\n\n"
        "## Contact\n\n"
        "- Email: join@titanfitness.example\n"
        "- Phone: (555) 123-4567\n\n"
    )
    # Repeat to build size
    for i in range(400):  # adjust multiplier to grow content
        sections.append(f"\n### Section Copy {i+1}\n\n" + base_section)
    return header + "\n".join(sections)


# ----------------- API Calls -----------------
def admin_login(base: str, email: str, password: str) -> str:
    r = requests.post(f"{base}/auth/login", json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("access_token")


def admin_create_client(base: str, admin_token: str, name: str, website_url: str) -> dict:
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Admin router is mounted at /admin; this endpoint expects simple params
    r = requests.post(
        f"{base}/admin/clients",
        headers=headers,
        params={"name": name, "website_url": website_url},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()

def ensure_deployment(base: str, client_id: str, admin_token: str):
    headers = {"Authorization": f"Bearer {admin_token}"}
    # Get or create deployment
    r = requests.get(
        f"{base}/api/admin/client-config/client/{client_id}/deployment",
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    dep = r.json()["deployment"]

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

    # Ensure token
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
        r = requests.post(
            f"{base}/api/admin/client-config/client/{client_id}/deploy",
            headers=headers,
            timeout=30,
        )
        r.raise_for_status()

    return custom_client_id, deployment_token


def add_large_kb(base: str, client_id: str, admin_token: str):
    content = large_gym_markdown()
    # Send as multipart form-data to be robust with large bodies
    files = {
        "title": (None, "Gym Handbook Large"),
        "content": (None, content),
    }
    r = requests.post(
        f"{base}/api/admin/knowledge-base/client/{client_id}/add-markdown",
        headers={"Authorization": f"Bearer {admin_token}"},
        files=files,
        timeout=240,
    )
    r.raise_for_status()
    return r.json()


def send_chat(
    base: str,
    custom_client_id: str,
    text: str,
    deployment_token: str | None,
    *,
    session_id: str | None = None,
    lead_name: str | None = None,
    lead_email: str | None = None,
    lead_phone: str | None = None,
    return_sources: bool = False,
):
    headers = {"x-deployment-token": deployment_token} if deployment_token else {}
    params = {
        "message": text,
        "return_sources": "true" if return_sources else "false",
    }
    if session_id:
        params["session_id"] = session_id
    if lead_name:
        params["lead_name"] = lead_name
    if lead_email:
        params["lead_email"] = lead_email
    if lead_phone:
        params["lead_phone"] = lead_phone
    r = requests.post(
        f"{base}/api/chat/{custom_client_id}/message",
        headers=headers,
        params=params,
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def get_summary(base: str, client_jwt: str, timeframe: str = "today"):
    headers = {"Authorization": f"Bearer {client_jwt}"}
    r = requests.get(f"{base}/api/client/analytics/summary", headers=headers, params={"timeframe": timeframe}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_daily(base: str, client_jwt: str, days: int = 7):
    headers = {"Authorization": f"Bearer {client_jwt}"}
    r = requests.get(f"{base}/api/client/analytics/daily", headers=headers, params={"days": days}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_client_leads(base: str, client_jwt: str):
    headers = {"Authorization": f"Bearer {client_jwt}"}
    r = requests.get(f"{base}/api/client/leads", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def get_lead_details(base: str, client_jwt: str, lead_id: str):
    headers = {"Authorization": f"Bearer {client_jwt}"}
    r = requests.get(f"{base}/api/client/leads/{lead_id}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def get_chat_history_for_session(base: str, custom_client_id: str, session_id: str):
    r = requests.get(f"{base}/api/chat/{custom_client_id}/history/{session_id}", timeout=30)
    r.raise_for_status()
    return r.json()


# ----------------- Main -----------------

def main():
    ap = argparse.ArgumentParser(description="E2E: KB + Chat + Analytics")
    ap.add_argument('--base-url', default=os.getenv('E2E_BASE_URL', 'http://localhost:8000'))
    ap.add_argument('--client-id', default=os.getenv('E2E_CLIENT_ID'))
    ap.add_argument('--custom-client-id', default=os.getenv('E2E_CUSTOM_CLIENT_ID'))
    ap.add_argument('--deployment-token', default=os.getenv('E2E_DEPLOYMENT_TOKEN'))
    ap.add_argument('--jwt-secret-key', default=os.getenv('JWT_SECRET_KEY'))
    ap.add_argument('--client-jwt', default=os.getenv('E2E_CLIENT_JWT'))
    ap.add_argument('--days', type=int, default=7)
    ap.add_argument('--messages', nargs='*', default=[
        "Hi there! What are your membership options?",
        "Do you have classes like HIIT or Yoga?",
        "What are staffed hours and is there 24/7 access?"
    ])
    # Contact info to emulate user providing details to the chatbot
    ap.add_argument('--contact-name', default=os.getenv('E2E_CONTACT_NAME', 'Jane Prospect'))
    ap.add_argument('--contact-email', default=os.getenv('E2E_CONTACT_EMAIL', 'jane.prospect@example.com'))
    ap.add_argument('--contact-phone', default=os.getenv('E2E_CONTACT_PHONE', '(555) 987-6543'))
    # Optional admin inputs to auto-create a client if client_id not supplied
    ap.add_argument('--admin-email', default=os.getenv('ADMIN_EMAIL'))
    ap.add_argument('--admin-password', default=os.getenv('ADMIN_PASSWORD'))
    ap.add_argument('--admin-token', default=os.getenv('E2E_ADMIN_TOKEN'))
    ap.add_argument('--new-client-name', default=os.getenv('E2E_NEW_CLIENT_NAME', 'Titan Fitness E2E'))
    ap.add_argument('--new-client-website', default=os.getenv('E2E_NEW_CLIENT_WEBSITE', 'https://titan-e2e.example'))
    args = ap.parse_args()

    # Obtain admin token for admin-protected endpoints (deployment + KB)
    admin_token = args.admin_token
    if not admin_token:
        if args.admin_email and args.admin_password:
            print("Logging in as admin...")
            admin_token = admin_login(args.base_url, args.admin_email, args.admin_password)
        else:
            print("Admin authentication required. Provide --admin-token or --admin-email/--admin-password.", file=sys.stderr)
            sys.exit(1)

    # If client_id is missing, create one using admin token
    if not args.client_id:
        print("Creating client...")
        created = admin_create_client(
            args.base_url,
            admin_token,
            name=f"{args.new_client_name} {datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            website_url=args.new_client_website,
        )
        args.client_id = str(created.get('client_id'))
        if not args.client_id:
            print("Failed to obtain client_id from creation response:")
            print(pretty(created))
            sys.exit(1)
        print(f"Created client_id={args.client_id}")

    # Ensure deployment details
    print("Ensuring deployment (custom_client_id, token, deployed)...")
    custom_id = args.custom_client_id
    token = args.deployment_token
    if not custom_id or not token:
        custom_id, token = ensure_deployment(args.base_url, args.client_id, admin_token)
    print(f"custom_client_id={custom_id}")

    # Add large markdown to KB
    print("Adding large markdown to KB (this may take a bit)...")
    kb_res = add_large_kb(args.base_url, args.client_id, admin_token)
    print("KB add result:")
    print(pretty(kb_res))

    # Client JWT for analytics
    client_jwt = args.client_jwt
    if not client_jwt:
        if not args.jwt_secret_key:
            print("Provide --client-jwt or --jwt-secret-key to query analytics", file=sys.stderr)
            sys.exit(1)
        client_jwt = mint_client_jwt(args.jwt_secret_key, args.client_id)
        print("Minted client JWT for analytics")

    # Baseline analytics
    print("Fetching baseline analytics (today)...")
    base_sum = get_summary(args.base_url, client_jwt, timeframe="today")
    print(pretty(base_sum))

    # Chat turns
    print("Sending chat messages referencing KB content...")
    session_id = str(uuid.uuid4())
    for i, msg in enumerate(args.messages, start=1):
        res = send_chat(args.base_url, custom_id, msg, token, session_id=session_id)
        print(f"Turn {i} response (truncated):")
        print(pretty({k: res[k] for k in ["session_id", "response", "context_used", "lead_qualified", "contact_captured"] if k in res}))
        time.sleep(1)

    # Emulate providing contact info to the chatbot
    print("Providing contact info to the chatbot (will also pass via query to ensure capture)...")
    contact_text = (
        f"My name is {args.contact_name}. You can reach me at {args.contact_email} or {args.contact_phone}."
    )
    contact_res = send_chat(
        args.base_url,
        custom_id,
        contact_text,
        token,
        session_id=session_id,
        lead_name=args.contact_name,
        lead_email=args.contact_email,
        lead_phone=args.contact_phone,
    )
    print("Contact turn result (truncated):")
    print(pretty({k: contact_res[k] for k in ["session_id", "lead_qualified", "contact_captured"] if k in contact_res}))

    # Post analytics
    print("Fetching analytics after chat (today)...")
    after_sum = get_summary(args.base_url, client_jwt, timeframe="today")
    print(pretty(after_sum))

    # Deltas
    keys = ["sessions_started", "messages_user", "messages_bot", "leads_created", "leads_qualified", "contacts_captured"]
    base_tot = base_sum.get("totals", {})
    after_tot = after_sum.get("totals", {})
    deltas = {k: int(after_tot.get(k, 0)) - int(base_tot.get(k, 0)) for k in keys}
    print("Deltas:")
    print(pretty(deltas))

    # Daily series
    print(f"Fetching daily series (last {args.days} days)...")
    daily = get_daily(args.base_url, client_jwt, days=args.days)
    print(pretty(daily))

    # Fetch leads and identify the one we just updated/created
    print("Fetching client leads...")
    leads_payload = get_client_leads(args.base_url, client_jwt)
    print(pretty({"total_count": leads_payload.get("total_count"), "sample": leads_payload.get("leads", [])[:3]}))

    target_lead = None
    targets = leads_payload.get("leads", [])
    for ld in targets:
        if ld.get("email") == args.contact_email or ld.get("phone_number") == args.contact_phone:
            target_lead = ld
            break
    if not target_lead and targets:
        # fallback to most recently updated
        target_lead = sorted(targets, key=lambda x: x.get("updated_at") or x.get("created_at"), reverse=True)[0]

    if target_lead:
        print(f"Inspecting lead: {target_lead.get('lead_id')} ({target_lead.get('email') or target_lead.get('phone_number')})")
        lead_details = get_lead_details(args.base_url, client_jwt, target_lead.get("lead_id"))
        print("Lead details (truncated):")
        ch = lead_details.get("chat_history", [])
        if isinstance(ch, list):
            ch_count = len(ch)
        else:
            # When API returns chat context as a string, count lines that look like messages
            ch_str = str(ch or "")
            ch_count = sum(1 for ln in ch_str.splitlines() if ln.strip())
        print(pretty({
            "lead": lead_details.get("lead"),
            "chat_history_count": ch_count,
            "email_messages_count": len(lead_details.get("email_messages", [])),
        }))

        # Also fetch the precise chat session history we used
        try:
            sess_hist = get_chat_history_for_session(args.base_url, custom_id, session_id)
            print("Chat session history (first 4 messages):")
            print(pretty({
                "session_id": sess_hist.get("session_id"),
                "messages": sess_hist.get("messages", [])[:4],
            }))
        except Exception as e:
            print(f"Warning: could not fetch chat history for session: {e}")

    print("E2E KB+Chat+Analytics test complete.")


if __name__ == '__main__':
    main()
