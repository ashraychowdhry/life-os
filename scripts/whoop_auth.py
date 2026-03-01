"""
Whoop OAuth2 authorization flow.
Run this once to get an access token, which gets saved to .env.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
import secrets
import httpx
import app_config as config

TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".whoop_token.json")
auth_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        print(f"  Callback received: {self.path}")
        params = parse_qs(urlparse(self.path).query)
        print(f"  Params: {params}")
        auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.end_headers()
        if auth_code:
            self.wfile.write(b"<h1>Whoop auth complete. You can close this tab.</h1>")
        else:
            error = params.get("error", ["unknown"])[0]
            self.wfile.write(f"<h1>Error: {error}</h1><p>{params}</p>".encode())

    def log_message(self, format, *args):
        pass  # suppress server logs


def authorize():
    if not config.WHOOP_CLIENT_ID or not config.WHOOP_CLIENT_SECRET:
        print("ERROR: WHOOP_CLIENT_ID and WHOOP_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    state = secrets.token_urlsafe(16)
    params = {
        "client_id": config.WHOOP_CLIENT_ID,
        "redirect_uri": config.WHOOP_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(config.WHOOP_SCOPES),
        "state": state,
    }
    auth_url = f"{config.WHOOP_AUTH_URL}?{urlencode(params)}"

    print(f"\nOpening browser for Whoop authorization...")
    print(f"If it doesn't open, go to:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server = HTTPServer(("localhost", 8080), CallbackHandler)
    server.handle_request()  # handle one request then stop

    if not auth_code:
        print("ERROR: No auth code received.")
        sys.exit(1)

    # Exchange code for token
    resp = httpx.post(
        config.WHOOP_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": config.WHOOP_REDIRECT_URI,
            "client_id": config.WHOOP_CLIENT_ID,
            "client_secret": config.WHOOP_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    print(f"  Token response {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    token_data = resp.json()

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"✅ Token saved to {TOKEN_FILE}")
    print(f"   Access token expires in: {token_data.get('expires_in')}s")
    return token_data


if __name__ == "__main__":
    authorize()
