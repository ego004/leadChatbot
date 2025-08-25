import os
import sys
import time
import uuid
import requests

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not ADMIN_EMAIL or not ADMIN_PASSWORD:
    print("ERROR: Set ADMIN_EMAIL and ADMIN_PASSWORD environment variables to run this script.")
    sys.exit(1)


def pretty(title: str, data):
    print(f"\n=== {title} ===")
    try:
        import json
        print(json.dumps(data, indent=2, default=str))
    except Exception:
        print(data)


def auth_login():
    url = f"{BASE_URL}/auth/login"
    res = requests.post(url, json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    res.raise_for_status()
    token = res.json()["access_token"]
    pretty("Login", res.json())
    return token


def auth_header(token: str):
    return {"Authorization": f"Bearer {token}"}


def create_client(token: str):
    url = f"{BASE_URL}/admin/clients"
    name = f"GymCo-{uuid.uuid4().hex[:6]}"
    payload = {
        "name": name,
        "website_url": "https://gym.example.com",
        "contact_email": f"hello@{name.lower()}.com",
    }
    res = requests.post(url, headers=auth_header(token), params=payload)
    res.raise_for_status()
    pretty("Create Client", res.json())
    return res.json()["client_id"], name


def add_gym_markdown(token: str, client_id: str):
    url = f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/add-markdown"
    content = (
        "# Peak Performance Gym\n"
        "Welcome to Peak Performance Gym in San Francisco. We offer flexible memberships and premium amenities.\n\n"
        "## Memberships\n"
        "- Month-to-month: $79/month, cancel anytime.\n"
        "- 12-month commitment: $69/month.\n"
        "- Day pass: $15.\n\n"
        "## Hours\n"
        "- Mon-Fri: 5:30am - 10:00pm\n"
        "- Sat-Sun: 7:00am - 8:00pm\n\n"
        "## Classes\n"
        "- HIIT, Yoga, Spin, Strength Conditioning.\n"
        "- Small group training and 1:1 personal training.\n\n"
        "## Amenities\n"
        "- Sauna, locker rooms, showers, towel service, free parking.\n\n"
        "## Contact\n"
        "- Phone: (415) 555-0100\n"
        "- Email: info@peakgym.example.com\n"
    )
    payload = {"title": "Gym Overview", "content": content}
    res = requests.post(url, headers=auth_header(token), json=payload)
    res.raise_for_status()
    pretty("Add Gym Markdown", res.json())
    return res.json()["document_id"]


def set_custom_system_prompt(token: str, client_id: str):
    url = f"{BASE_URL}/api/admin/client-config/client/{client_id}/system-prompts"
    payload = {
        "website_system_prompt": (
            "You are a friendly, concise front-desk assistant for Peak Performance Gym in San Francisco. "
            "Answer naturally, use info from the knowledge base exactly, and invite prospects to tour. "
            "If buying signals or contact details are present, use tools to qualify the lead and capture contact info."
        ),
        "welcome_message": "Welcome to Peak Performance Gym! How can I help you today?",
    }
    # Endpoint expects query params
    res = requests.put(url, headers=auth_header(token), params=payload)
    res.raise_for_status()
    pretty("Set Custom System Prompt", res.json())


def configure_and_deploy(token: str, client_id: str):
    # Generate custom client id
    gen_url = f"{BASE_URL}/api/admin/client-config/client/{client_id}/generate-custom-id"
    res = requests.post(gen_url, headers=auth_header(token))
    res.raise_for_status()
    custom_id = res.json()["custom_client_id"]
    pretty("Generate Custom ID", res.json())

    # Deploy
    dep_url = f"{BASE_URL}/api/admin/client-config/client/{client_id}/deploy"
    res = requests.post(dep_url, headers=auth_header(token))
    res.raise_for_status()
    pretty("Deploy Chatbot", res.json())
    return custom_id


def chat(custom_client_id: str, message: str, token: str | None = None, session_id: str | None = None):
    url = f"{BASE_URL}/api/chat/{custom_client_id}/message"
    headers = {}
    if token:
        headers.update(auth_header(token))
    params = {"message": message, "return_sources": True}
    if session_id:
        params["session_id"] = session_id
    res = requests.post(url, headers=headers, params=params)
    res.raise_for_status()
    pretty("Chat Response", res.json())
    return res.json()


def main():
    token = auth_login()
    client_id, name = create_client(token)

    # Allow any initialization
    time.sleep(0.5)

    _ = add_gym_markdown(token, client_id)

    # Wait for vector indexing
    time.sleep(1.0)

    set_custom_system_prompt(token, client_id)

    custom_id = configure_and_deploy(token, client_id)

    # Turn 1: Natural inquiry
    r1 = chat(
        custom_id,
        message=(
            "Hi! Do you have month-to-month memberships and what do they cost? "
            "Also, what are your staffed hours on weekends?"
        ),
        token=None,
    )

    session_id = r1.get("session_id")

    # Turn 2: Provide contact details
    r2 = chat(
        custom_id,
        message=(
            "Great, thanks! My name is Alex Chen. You can reach me at alex.chen@example.com "
            "and my phone is 415-555-1212."
        ),
        token=None,
        session_id=session_id,
    )

    # Quick validations
    print("\n--- Validations ---")
    print("Context used (turn 1):", r1.get("context_used"))
    print("Lead qualified (either turn):", r1.get("lead_qualified"), r2.get("lead_qualified"))
    print("Contact captured (turn 2):", r2.get("contact_captured"))
    print("Parsed contact (turn 2):", r2.get("tool_results", {}).get("contact_info"))

    print("\nGym natural chat test completed.")


if __name__ == "__main__":
    main()
