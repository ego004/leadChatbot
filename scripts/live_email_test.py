import os
import sys
import time
import uuid
import requests

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")

# SMTP/IMAP from environment (global defaults). You can also override per client below.
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME", "LeadGenius AI")
IMAP_SERVER = os.getenv("IMAP_SERVER")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

# Where to send the test manual email (defaults to your EMAIL_USER to create a loopback test)
LEAD_TEST_EMAIL = os.getenv("LEAD_TEST_EMAIL", EMAIL_USER or "test-inbox@example.com")

session = requests.Session()


def log(step: str):
    print(f"\n=== {step} ===")


def require_env(var: str, value: str | None):
    if not value:
        print(f"[!] Missing required env var: {var}")
        return False
    return True


def admin_login() -> str:
    log("Admin Login")
    resp = session.post(
        f"{BASE_URL}/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]
    session.headers.update({"Authorization": f"Bearer {token}"})
    print("OK")
    return token


def create_client(name: str, website_url: str) -> str:
    log("Create Client")
    resp = session.post(
        f"{BASE_URL}/admin/clients",
        params={"name": name, "website_url": website_url, "contact_email": LEAD_TEST_EMAIL},
        timeout=20,
    )
    resp.raise_for_status()
    cid = resp.json()["client_id"]
    print("client_id:", cid)
    return cid


def set_email_config(client_id: str):
    log("Update Client Email Settings (per-client)")
    params = {
        "smtp_server": SMTP_SERVER,
        "smtp_port": SMTP_PORT,
        "smtp_user": EMAIL_USER,
        "smtp_password": EMAIL_PASSWORD,
        "smtp_from_name": EMAIL_FROM_NAME,
        "imap_server": IMAP_SERVER,
        "imap_port": IMAP_PORT,
        "email_enabled": True,
    }
    resp = session.put(f"{BASE_URL}/admin/clients/{client_id}", params=params, timeout=20)
    resp.raise_for_status()
    print("OK")


def prepare_deployment(client_id: str) -> str:
    log("Generate custom_client_id")
    resp = session.post(f"{BASE_URL}/api/admin/client-config/client/{client_id}/generate-custom-id", timeout=20)
    resp.raise_for_status()
    custom_id = resp.json()["custom_client_id"]
    print("custom_client_id:", custom_id)

    log("Deploy chatbot")
    resp = session.post(f"{BASE_URL}/api/admin/client-config/client/{client_id}/deploy", timeout=20)
    resp.raise_for_status()
    print("deployed at:", resp.json().get("deployment_url"))
    return custom_id


def create_lead_via_chat(custom_client_id: str, lead_email: str) -> dict:
    log("Create lead via chat endpoint")
    # minimal message to create a session + lead
    resp = session.post(
        f"{BASE_URL}/api/chat/{custom_client_id}/message",
        params={
            "message": "Hi, I am interested in your services.",
            "lead_email": lead_email,
            "lead_name": "Email Test Lead",
            "return_sources": False,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    print("chat response keys:", list(data.keys()))
    return data


def fetch_lead_id(client_id: str, lead_email: str) -> str:
    log("Fetch client details and locate lead_id")
    resp = session.get(f"{BASE_URL}/admin/clients/{client_id}", timeout=20)
    resp.raise_for_status()
    leads = resp.json().get("leads", [])
    for l in leads:
        if l.get("email") == lead_email:
            print("lead_id:", l["lead_id"])
            return l["lead_id"]
    raise RuntimeError("Lead not found in admin client details")


def send_manual_email(lead_id: str, to_email: str):
    log("Send manual email via admin email-chat API")
    payload = {
        "to_email": to_email,
        "subject": "LeadGenius AI Test Email",
        "message": "This is a test email sent by live_email_test.py",
        "lead_id": lead_id,
    }
    resp = session.post(f"{BASE_URL}/api/admin/email-chat/send-manual-email", json=payload, timeout=30)
    resp.raise_for_status()
    print("message_id:", resp.json().get("message_id"))


def check_monitoring_status():
    log("Get email monitoring status")
    resp = session.get(f"{BASE_URL}/api/admin/email-chat/monitoring-status", timeout=20)
    resp.raise_for_status()
    print(resp.json())


def main():
    print("Live Email Test starting...\n")

    # Validate critical env vars
    ok = True
    ok &= require_env("SMTP_SERVER", SMTP_SERVER)
    ok &= require_env("EMAIL_USER", EMAIL_USER)
    ok &= require_env("EMAIL_PASSWORD", EMAIL_PASSWORD)
    ok &= require_env("IMAP_SERVER", IMAP_SERVER)
    if not ok:
        print("\nPlease set the missing env vars in your .env and restart the server before running this script.")
        sys.exit(1)

    token = admin_login()

    # Create a unique client each run to avoid collisions
    client_name = f"Email Test Client {uuid.uuid4().hex[:6]}"
    website_url = "https://example.com"
    client_id = create_client(client_name, website_url)

    # Configure per-client email
    set_email_config(client_id)

    # Prepare deployment to use chat endpoint
    custom_client_id = prepare_deployment(client_id)

    # Create a lead through chat with our test inbox as the lead email
    create_lead_via_chat(custom_client_id, LEAD_TEST_EMAIL)

    # Resolve lead_id from admin view
    lead_id = fetch_lead_id(client_id, LEAD_TEST_EMAIL)

    # Send a manual email to the lead (your inbox)
    send_manual_email(lead_id, LEAD_TEST_EMAIL)

    # Verify monitoring config
    check_monitoring_status()

    print("\nAll done. Check the inbox:", LEAD_TEST_EMAIL)


if __name__ == "__main__":
    main()
