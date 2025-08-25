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
    name = f"LiveTestCo-{uuid.uuid4().hex[:6]}"
    payload = {
        "name": name,
        "website_url": "https://example.com",
        "contact_email": f"{name.lower()}@example.com",
    }
    # This endpoint expects form/query params style, not a JSON body
    res = requests.post(url, headers=auth_header(token), params=payload)
    res.raise_for_status()
    pretty("Create Client", res.json())
    return res.json()["client_id"], name


def add_markdown(token: str, client_id: str):
    url = f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/add-markdown"
    payload = {
        "title": "Getting Started",
        "content": "# Welcome\nThis is a KB doc used in live API tests. It mentions foobar and onboarding steps.",
    }
    res = requests.post(url, headers=auth_header(token), json=payload)
    res.raise_for_status()
    pretty("Add Markdown", res.json())
    return res.json()["document_id"]


def search_kb(token: str, client_id: str, query: str):
    url = f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/search"
    params = {"query": query, "limit": 5}
    res = requests.get(url, headers=auth_header(token), params=params)
    res.raise_for_status()
    pretty("Search KB", res.json())
    return res.json()["results"]


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


def chat(custom_client_id: str, message: str, token: str | None = None):
    url = f"{BASE_URL}/api/chat/{custom_client_id}/message"
    headers = {}
    if token:
        headers.update(auth_header(token))
    params = {"message": message, "return_sources": True}
    res = requests.post(url, headers=headers, params=params)
    res.raise_for_status()
    pretty("Chat Response", res.json())
    return res.json()


def main():
    token = auth_login()
    client_id, name = create_client(token)

    # Give the server a moment if it needs to initialize vector store
    time.sleep(0.5)

    doc_id = add_markdown(token, client_id)

    # Wait a bit for vector indexing (depending on backend latency)
    time.sleep(1.0)

    _ = search_kb(token, client_id, query="foobar onboarding")

    custom_id = configure_and_deploy(token, client_id)

    # Chat
    _ = chat(custom_id, message="Hi! Can you tell me about onboarding?", token=None)

    print("\nLive API test completed successfully.")


if __name__ == "__main__":
    main()
