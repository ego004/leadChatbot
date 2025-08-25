#!/usr/bin/env python3
"""
End-to-end test for client analytics + chat flow.

Usage examples:

  python scripts/e2e_client_analytics.py \
    --base-url http://localhost:8000 \
    --custom-client-id your_custom_id \
    --client-id 12345678-1234-1234-1234-1234567890ab \
    --deployment-token YOUR_DEPLOYMENT_TOKEN \
    --jwt-secret-key your-secret-key

If CHAT_REQUIRE_DEPLOYMENT_TOKEN=false on the server, you can omit --deployment-token.
If you already have a client JWT, pass --client-jwt and omit --jwt-secret-key.

What it does:
- Optionally mints a client JWT (if --client-jwt is not provided and --jwt-secret-key is).
- Gets analytics summary for today (baseline).
- Sends one or more chat messages to /api/chat/{custom_client_id}/message.
- Fetches analytics summary for today and daily series (last 7 days).
- Prints totals and deltas to verify increments.
"""
import argparse
import os
import sys
import time
from datetime import timedelta, datetime
import json

import requests

try:
    import jwt  # PyJWT
except Exception:
    jwt = None


def mint_client_jwt(secret_key: str, client_id: str, hours: int = 24) -> str:
    if jwt is None:
        raise RuntimeError("PyJWT not installed. Install with: pip install PyJWT")
    payload = {
        "sub": client_id,
        "exp": datetime.utcnow() + timedelta(hours=hours),
    }
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    # PyJWT>=2 returns str; ensure str
    return token if isinstance(token, str) else token.decode()


def get_analytics_summary(base_url: str, client_jwt: str, timeframe: str = "today") -> dict:
    url = f"{base_url.rstrip('/')}/api/client/analytics/summary"
    headers = {"Authorization": f"Bearer {client_jwt}"}
    resp = requests.get(url, headers=headers, params={"timeframe": timeframe}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_analytics_daily(base_url: str, client_jwt: str, days: int = 7) -> dict:
    url = f"{base_url.rstrip('/')}/api/client/analytics/daily"
    headers = {"Authorization": f"Bearer {client_jwt}"}
    resp = requests.get(url, headers=headers, params={"days": days}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_chat_message(base_url: str, custom_client_id: str, text: str, deployment_token: str | None = None,
                      lead_name: str | None = None, lead_email: str | None = None,
                      lead_phone: str | None = None, session_id: str | None = None,
                      return_sources: bool = False) -> dict:
    url = f"{base_url.rstrip('/')}/api/chat/{custom_client_id}/message"
    headers = {}
    if deployment_token:
        # Server accepts either x-deployment-token or Authorization: Bearer
        headers["x-deployment-token"] = deployment_token
    params = {
        "message": text,
        "return_sources": str(return_sources).lower(),
    }
    if session_id:
        params["session_id"] = session_id
    if lead_name:
        params["lead_name"] = lead_name
    if lead_email:
        params["lead_email"] = lead_email
    if lead_phone:
        params["lead_phone"] = lead_phone

    resp = requests.post(url, headers=headers, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def pretty(o):
    return json.dumps(o, indent=2, sort_keys=True, default=str)


def main():
    parser = argparse.ArgumentParser(description="E2E test: chat + client analytics")
    parser.add_argument('--base-url', default=os.getenv('E2E_BASE_URL', 'http://localhost:8000'))
    parser.add_argument('--custom-client-id', default=os.getenv('E2E_CUSTOM_CLIENT_ID'))
    parser.add_argument('--client-id', default=os.getenv('E2E_CLIENT_ID'))
    parser.add_argument('--deployment-token', default=os.getenv('E2E_DEPLOYMENT_TOKEN'))
    parser.add_argument('--client-jwt', default=os.getenv('E2E_CLIENT_JWT'))
    parser.add_argument('--jwt-secret-key', default=os.getenv('JWT_SECRET_KEY'))
    parser.add_argument('--messages', nargs='*', default=[
        "Hello! I'm interested in your services.",
        "Do you offer demos? My email is e2e.tester@example.com"
    ])
    parser.add_argument('--session-id', default=None)
    parser.add_argument('--lead-name', default=None)
    parser.add_argument('--lead-email', default=None)
    parser.add_argument('--lead-phone', default=None)
    parser.add_argument('--days', type=int, default=7)
    args = parser.parse_args()

    if not args.custom_client_id:
        print("--custom-client-id is required (or E2E_CUSTOM_CLIENT_ID)", file=sys.stderr)
        sys.exit(1)
    if not args.client_id:
        print("--client-id is required (or E2E_CLIENT_ID)", file=sys.stderr)
        sys.exit(1)

    client_jwt = args.client_jwt
    if not client_jwt:
        if not args.jwt_secret_key:
            print("Provide --client-jwt or --jwt-secret-key to mint one", file=sys.stderr)
            sys.exit(1)
        client_jwt = mint_client_jwt(args.jwt_secret_key, args.client_id)
        print("Minted client JWT")

    print("Fetching baseline analytics (today)...")
    baseline = get_analytics_summary(args.base_url, client_jwt, timeframe="today")
    print("Baseline:")
    print(pretty(baseline))

    print("Sending chat messages...")
    session_id = args.session_id
    for i, msg in enumerate(args.messages, start=1):
        # On first message, no session_id -> should create a new session (impression)
        payload = send_chat_message(
            base_url=args.base_url,
            custom_client_id=args.custom_client_id,
            text=msg,
            deployment_token=args.deployment_token,
            lead_name=args.lead_name,
            lead_email=args.lead_email,
            lead_phone=args.lead_phone,
            session_id=session_id,
            return_sources=False,
        )
        print(f"Chat turn {i} response:\n{pretty(payload)}")
        session_id = payload.get("session_id", session_id)
        time.sleep(1)

    print("Fetching post-chat analytics (today)...")
    after = get_analytics_summary(args.base_url, client_jwt, timeframe="today")
    print("After:")
    print(pretty(after))

    print("Deltas (totals after - baseline):")
    base_tot = baseline.get("totals", {})
    after_tot = after.get("totals", {})
    keys = [
        "sessions_started",
        "messages_user",
        "messages_bot",
        "leads_created",
        "leads_qualified",
        "contacts_captured",
    ]
    deltas = {k: int(after_tot.get(k, 0)) - int(base_tot.get(k, 0)) for k in keys}
    print(pretty(deltas))

    print(f"Fetching daily series (last {args.days} days)...")
    series = get_analytics_daily(args.base_url, client_jwt, days=args.days)
    print(pretty(series))

    print("E2E analytics test completed.")


if __name__ == '__main__':
    main()
