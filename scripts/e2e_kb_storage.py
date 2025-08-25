"""
End-to-end smoke test for admin auth, client creation, KB add, Storage mirror, and vector search.

Usage:
  set BASE_URL=http://localhost:8000
  set ADMIN_EMAIL=admin@example.com
  set ADMIN_PASSWORD=ChangeMe123!
  python -m tests.e2e_kb_storage

Environment:
  - API must be running locally
  - Supabase Postgres pgvector ready (documents table + match_documents)
  - Optional: Supabase Storage bucket "leadgenius-markdowns" exists (private)
"""
from __future__ import annotations
import os
import sys
import time
import uuid
import json
import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")

s = requests.Session()

def must(ok: bool, msg: str):
    if not ok:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[OK] {msg}")


def login_admin() -> str:
    r = s.post(f"{BASE_URL}/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
    })
    must(r.status_code == 200, f"login status {r.status_code}")
    data = r.json()
    token = data.get("access_token")
    must(bool(token), "received access_token")
    s.headers.update({"Authorization": f"Bearer {token}"})
    return token


def create_client() -> str:
    name = f"Acme-{uuid.uuid4().hex[:6]}"
    website_url = "https://example.com"
    r = s.post(f"{BASE_URL}/admin/clients", params={"name": name, "website_url": website_url})
    must(r.status_code in (200, 201), f"create client status {r.status_code}")
    data = r.json()
    client_id = str(data.get("client_id"))
    must(bool(client_id), "received client_id")
    return client_id


def add_markdown(client_id: str) -> str:
    title = "Pricing Overview"
    content = "This is Acme pricing details...\nTier A: $10\nTier B: $20\n"
    r = s.post(f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/add-markdown",
               data={"title": title, "content": content})
    must(r.status_code == 200, f"add markdown status {r.status_code}")
    data = r.json()
    doc_id = data.get("document_id")
    must(bool(doc_id), "received document_id")
    return doc_id


def list_storage(client_id: str) -> list[str]:
    r = s.get(f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/storage/markdowns")
    must(r.status_code == 200, f"list storage status {r.status_code}")
    data = r.json()
    return data.get("files", [])


def search_kb(client_id: str) -> list[dict]:
    r = s.get(f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/search",
              params={"query": "pricing", "limit": 5})
    must(r.status_code == 200, f"search status {r.status_code}")
    return r.json().get("results", [])


def main():
    print(f"BASE_URL={BASE_URL}")
    login_admin()
    client_id = create_client()
    print(f"client_id={client_id}")
    doc_id = add_markdown(client_id)
    print(f"document_id={doc_id}")

    # Allow eventual consistency for Storage
    time.sleep(1.0)

    files = list_storage(client_id)
    print("storage files:", files)

    results = search_kb(client_id)
    print("search results (top):", json.dumps(results[:2], indent=2))

    must(any("pricing" in (r.get("page_content") or r.get("content") or "").lower() for r in results),
         "vector search returns relevant content")

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
