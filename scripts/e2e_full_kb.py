"""
Full end-to-end validation for Knowledge Base flow:
- Admin login
- Create client (use returned client_id throughout)
- Add markdown -> Update markdown
- Upload markdown file
- Create markdown directly in Supabase Storage (DB + vectors)
- List documents (admin) + fetch a document
- List Storage files (+ optionally fetch one file)
- Rebuild vectors
- Search vectors
- Optional: Trigger website scraping (can be slow; off by default)

Environment variables:
  BASE_URL (default http://localhost:8000)
  ADMIN_EMAIL (default admin@example.com)
  ADMIN_PASSWORD (default ChangeMe123!)
  RUN_SCRAPE=1 to enable /admin/clients/{client_id}/scrape

Run:
  python tests/e2e_full_kb.py
"""
from __future__ import annotations
import os
import sys
import time
import uuid
import json
import io
import requests

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
RUN_SCRAPE = os.getenv("RUN_SCRAPE", "0") == "1"

s = requests.Session()

def must(ok: bool, msg: str):
    if not ok:
        print(f"[FAIL] {msg}")
        sys.exit(1)
    print(f"[OK] {msg}")

def login_admin() -> None:
    r = s.post(f"{BASE_URL}/auth/login", json={
        "email": ADMIN_EMAIL,
        "password": ADMIN_PASSWORD,
    })
    must(r.status_code == 200, f"login status {r.status_code}")
    data = r.json()
    token = data.get("access_token")
    must(bool(token), "received access_token")
    s.headers.update({"Authorization": f"Bearer {token}"})


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
    r = s.post(
        f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/add-markdown",
        data={"title": "Pricing Overview", "content": "This is pricing.\nTier A: $10\nTier B: $20\n"},
    )
    must(r.status_code == 200, f"add markdown status {r.status_code}")
    doc_id = r.json().get("document_id")
    must(bool(doc_id), "received document_id (add)")
    return doc_id


def update_markdown(document_id: str) -> None:
    # Endpoint accepts query params per app/routers/knowledge_base.py
    r = s.put(
        f"{BASE_URL}/api/admin/knowledge-base/entry/{document_id}",
        params={"title": "Pricing v2", "content": "Updated pricing\nTier A: $10\nTier B: $20\nTier C: $30\n"},
    )
    must(r.status_code == 200, f"update markdown status {r.status_code}")


def upload_file(client_id: str) -> str:
    content = b"# FAQ\n\nQ: Hello?\nA: Hi!\n"
    files = {"file": ("faq.md", io.BytesIO(content), "text/markdown")}
    r = s.post(f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/upload-file", files=files)
    must(r.status_code == 200, f"upload file status {r.status_code}")
    doc_id = r.json().get("document_id")
    must(bool(doc_id), "received document_id (upload)")
    return doc_id


def create_direct_in_storage(client_id: str) -> tuple[str, str]:
    r = s.post(
        f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/storage/markdowns",
        data={"title": "Team", "content": "We are ACME team.\n"},
    )
    must(r.status_code == 200, f"create in storage status {r.status_code}")
    payload = r.json()
    return payload.get("document_id"), payload.get("filename")


def list_storage(client_id: str) -> list[str]:
    r = s.get(f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/storage/markdowns")
    must(r.status_code == 200, f"list storage status {r.status_code}")
    data = r.json()
    return data.get("files", [])


def get_storage_file(client_id: str, filename: str) -> str:
    r = s.get(
        f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/storage/markdown",
        params={"filename": filename},
    )
    must(r.status_code == 200, f"get storage file status {r.status_code}")
    return r.json().get("content", "")


def list_documents_kb(client_id: str) -> list[dict]:
    r = s.get(f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}")
    must(r.status_code == 200, f"list KB docs status {r.status_code}")
    data = r.json()
    # returns {"knowledge_base": [ ... ]}
    return data.get("knowledge_base", [])


def get_document_kb(client_id: str, document_id: str) -> dict:
    # Fetch via storage endpoint to retrieve full content; title is not stored in storage
    r = s.get(
        f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/storage/markdown",
        params={"filename": f"{document_id}.md"},
    )
    must(r.status_code == 200, f"get KB doc (storage) status {r.status_code}")
    payload = r.json()
    return {"title": f"doc-{document_id}", "content": payload.get("content", "")}


def rebuild_vectors(client_id: str) -> None:
    r = s.post(f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/rebuild-vectors")
    must(r.status_code == 200, f"rebuild vectors status {r.status_code}")


def search(client_id: str, q: str = "pricing", k: int = 5) -> list[dict]:
    r = s.get(f"{BASE_URL}/api/admin/knowledge-base/client/{client_id}/search", params={"query": q, "limit": k})
    must(r.status_code == 200, f"search status {r.status_code}")
    res = r.json().get("results", [])
    print("search (top):", json.dumps(res[:2], indent=2))
    must(any("pricing" in (r.get("page_content") or r.get("content") or "").lower() for r in res),
         "vector search returns relevant content")
    return res


def trigger_ingestion(client_id: str) -> None:
    r = s.post(f"{BASE_URL}/api/admin/clients/{client_id}/ingest")
    must(r.status_code in (200, 202), f"ingest status {r.status_code}")


def delete_document(document_id: str) -> None:
    r = s.delete(f"{BASE_URL}/api/admin/knowledge-base/entry/{document_id}")
    must(r.status_code == 200, f"delete doc status {r.status_code}")


def main():
    print(f"BASE_URL={BASE_URL}")
    login_admin()
    client_id = create_client()
    print(f"client_id={client_id}")

    # Create + update markdown
    doc_add = add_markdown(client_id)
    print(f"document_id(add)={doc_add}")
    update_markdown(doc_add)

    # Upload file + create directly in Storage
    doc_upload = upload_file(client_id)
    print(f"document_id(upload)={doc_upload}")
    doc_storage, storage_filename = create_direct_in_storage(client_id)
    print(f"document_id(storage)={doc_storage}, filename={storage_filename}")

    # Admin list + fetch
    docs = list_documents_kb(client_id)
    print("docs count:", len(docs))
    if docs:
        some_doc_id = str(docs[0]["document_id"])
        full_doc = get_document_kb(client_id, some_doc_id)
        print("sample title:", full_doc.get("title"))

    # Storage listing and optional read (allow brief eventual consistency)
    time.sleep(1.0)
    files = list_storage(client_id)
    print("storage files:", files)
    if storage_filename and storage_filename in files:
        content_preview = get_storage_file(client_id, storage_filename)[:80]
        print("storage file preview:", content_preview)

    # Rebuild vectors and search
    rebuild_vectors(client_id)
    search(client_id, "pricing", 5)

    # Optional: website scraping (can be slow)
    if RUN_SCRAPE:
        trigger_ingestion(client_id)

    print("\nAll checks passed.")


if __name__ == "__main__":
    main()
