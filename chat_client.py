import argparse
import requests
from urllib.parse import urljoin

def send_message(
    base_url: str,
    custom_client_id: str,
    message: str,
    deployment_token: str = None,
    session_id: str = None,
    lead_name: str = None,
    lead_email: str = None,
    lead_phone: str = None,
    top_k: int = 5,
    return_sources: bool = False,
    use_bearer: bool = False,
):
    endpoint = f"/api/chat/{custom_client_id}/message"
    url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))

    params = {
        "message": message,
        "top_k": top_k,
        "return_sources": str(bool(return_sources)).lower(),
    }
    if session_id:
        params["session_id"] = session_id
    if lead_name:
        params["lead_name"] = lead_name
    if lead_email:
        params["lead_email"] = lead_email
    if lead_phone:
        params["lead_phone"] = lead_phone

    headers = {}
    if deployment_token:
        headers["Authorization" if use_bearer else "x-deployment-token"] = (
            f"Bearer {deployment_token}" if use_bearer else deployment_token
        )

    r = requests.post(url, params=params, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()

def get_history(base_url: str, custom_client_id: str, session_id: str, deployment_token: str = None, use_bearer: bool = False):
    endpoint = f"/api/chat/{custom_client_id}/history/{session_id}"
    url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))
    headers = {}
    if deployment_token:
        headers["Authorization" if use_bearer else "x-deployment-token"] = (
            f"Bearer {deployment_token}" if use_bearer else deployment_token
        )
    r = requests.get(url, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()

def main():
    ap = argparse.ArgumentParser(description="Chat with LeadGenius chatbot")
    ap.add_argument("--base-url", required=True, help="e.g. http://localhost:8000")
    ap.add_argument("--custom-client-id", required=True, help="Custom Client ID from deployment")
    ap.add_argument("--token", help="Deployment token (required if token auth enabled)")
    ap.add_argument("--use-bearer", action="store_true", help="Send token as Authorization: Bearer ... instead of x-deployment-token")
    ap.add_argument("--session-id", help="Existing session_id to continue")
    ap.add_argument("--lead-name")
    ap.add_argument("--lead-email")
    ap.add_argument("--lead-phone")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--return-sources", action="store_true")
    ap.add_argument("--history", action="store_true", help="Fetch and print chat history for the session and exit")
    ap.add_argument("--message", help="Single message to send. If omitted, enters interactive mode.")
    args = ap.parse_args()

    if args.history:
        if not args.session_id:
            ap.error("--history requires --session-id")
        print(get_history(args.base_url, args.custom_client_id, args.session_id, args.token, args.use_bearer))
        return

    session_id = args.session_id
    if args.message:
        resp = send_message(
            args.base_url, args.custom_client_id, args.message, args.token, session_id,
            args.lead_name, args.lead_email, args.lead_phone, args.top_k, args.return_sources, args.use_bearer
        )
        print(resp)
        return

    # Interactive loop
    print("Interactive chat. Ctrl+C to exit.")
    while True:
        try:
            msg = input("You: ").strip()
            if not msg:
                continue
            resp = send_message(
                args.base_url, args.custom_client_id, msg, args.token, session_id,
                args.lead_name, args.lead_email, args.lead_phone, args.top_k, args.return_sources, args.use_bearer
            )
            session_id = resp.get("session_id") or session_id
            print("Bot:", resp.get("response"))
            if resp.get("sources"):
                print(f"[{len(resp['sources'])} sources returned]")
        except KeyboardInterrupt:
            print("\nBye.")
            break
        except requests.HTTPError as e:
            print("HTTP error:", e, getattr(e.response, "text", ""))
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    main()