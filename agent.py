"""Yahoo Fantasy read-only collector; no write requests to Fantasy API."""
import argparse
import base64
import json
import os
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import requests

ROOT = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / "token_state.json"
API = "https://fantasysports.yahooapis.com/fantasy/v2"
AUTH = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN = "https://api.login.yahoo.com/oauth2/get_token"


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def required(name):
    val = os.environ.get(name)
    if not val or val == "replace_me" or val == "generate_with_python":
        raise SystemExit(f"Missing {name}. Set it in .env (local) or GitHub Actions secret.")
    return val


def save_token(token):
    # SECURITY: Plaintext OAuth tokens. Use only in a tightly controlled private repository.
    tmp = TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(token, indent=2), encoding="utf8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, TOKEN_FILE)


def read_token():
    if not TOKEN_FILE.exists():
        raise SystemExit("Missing token_state.json. Run: python agent.py login locally first.")
    return json.loads(TOKEN_FILE.read_text(encoding="utf8"))


def credentials():
    raw = f'{required("YAHOO_CLIENT_ID")}:{required("YAHOO_CLIENT_SECRET")}'
    return {"Authorization": "Basic " + base64.b64encode(raw.encode()).decode()}


def exchange(data):
    response = requests.post(TOKEN, data=data, headers=credentials(), timeout=30)
    response.raise_for_status()
    return response.json()


def login():
    redirect_uri = os.environ.get("YAHOO_REDIRECT_URI", "http://127.0.0.1:8765/callback")
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost") or not parsed.port:
        raise SystemExit("For this CLI use a local http callback with explicit port, registered in Yahoo Developer.")
    state = secrets.token_urlsafe(32)
    result = {}
    event = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            if urlparse(self.path).path != (parsed.path or "/") or query.get("state", [None])[0] != state:
                self.send_error(400, "Invalid callback or state")
                return
            result["code"] = query.get("code", [None])[0]
            result["error"] = query.get("error", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Authorization received. You can close this tab.")
            event.set()
        def log_message(self, *args):
            pass

    server = HTTPServer((parsed.hostname, parsed.port), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = AUTH + "?" + urlencode({"client_id": required("YAHOO_CLIENT_ID"), "redirect_uri": redirect_uri, "response_type": "code", "state": state})
    print("Open Yahoo sign-in URL in your browser (no credentials are printed):")
    print(url)
    webbrowser.open(url)
    if not event.wait(timeout=240):
        server.shutdown()
        raise SystemExit("OAuth timed out after 4 minutes. Try again.")
    server.shutdown()
    if result.get("error") or not result.get("code"):
        raise SystemExit("Yahoo denied authorization or did not return a code.")
    token = exchange({"grant_type": "authorization_code", "code": result["code"], "redirect_uri": redirect_uri})
    token["obtained_at"] = int(time.time())
    save_token(token)
    print("Success: token_state.json saved (PLAINTEXT SENSITIVE). Never upload .env or use a public repo.")


def access_token():
    token = read_token()
    if time.time() < token.get("obtained_at", 0) + int(token.get("expires_in", 3600)) - 180:
        return token["access_token"]
    if not token.get("refresh_token"):
        raise SystemExit("No refresh_token received: run local login again.")
    updated = exchange({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
    if not updated.get("refresh_token"):
        updated["refresh_token"] = token["refresh_token"]
    updated["obtained_at"] = int(time.time())
    save_token(updated)
    return updated["access_token"]


def get(path, token):
    r = requests.get(API + path, headers={"Authorization": "Bearer " + token}, params={"format": "json"}, timeout=40)
    if not r.ok:
        raise RuntimeError(f"Yahoo GET {path}: HTTP {r.status_code}; check your granted Fantasy permissions and keys")
    return r.json()


def iter_objects(node, name):
    if isinstance(node, dict):
        if name in node:
            yield node[name]
        for v in node.values():
            yield from iter_objects(v, name)
    elif isinstance(node, list):
        for v in node:
            yield from iter_objects(v, name)


def get_property(obj, name):
    if isinstance(obj, dict):
        return obj.get(name)
    if isinstance(obj, list):
        for entry in obj:
            ans = get_property(entry, name)
            if ans is not None:
                return ans
    return None


def discover(data):
    found = []
    for team in iter_objects(data, "team"):
        key = get_property(team, "team_key")
        if not isinstance(key, str) or ".l." not in key or ".t." not in key:
            continue
        league = key.rsplit(".t.", 1)[0]
        if (league, key) not in found:
            found.append((league, key))
    return found


def collect():
    token = access_token()
    teams = get("/users;use_login=1/games;game_codes=nba/teams", token)
    matches = discover(teams)
    if not matches:
        print("No NBA teams discovered automatically. Check raw discovery JSON in output/ for details.")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    target = ROOT / "output" / stamp
    target.mkdir(parents=True, exist_ok=True)
    (target / "my_teams.json").write_text(json.dumps(teams, indent=2, ensure_ascii=False), encoding="utf8")
    manifest = []
    for league_key, team_key in matches:
        league_info = get(f"/league/{league_key}", token)
        settings = get(f"/league/{league_key}/settings", token)
        roster = get(f"/team/{team_key}/roster", token)
        scoreboard = get(f"/league/{league_key}/scoreboard", token)
        folder = target / league_key
        folder.mkdir(exist_ok=True)
        for filename, data in (("league", league_info), ("settings", settings), ("roster", roster), ("scoreboard", scoreboard)):
            (folder / f"{filename}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf8")
        manifest.append({"league_key": league_key, "team_key": team_key, "data_path": league_key})
    (target / "manifest.json").write_text(json.dumps({"collected_utc": stamp, "teams": manifest, "source": "Yahoo Fantasy Sports"}, indent=2), encoding="utf8")
    print(f"Collected {len(matches)} team(s) in {target}")
    print("Fantasy data provided by Yahoo Fantasy: https://sports.yahoo.com/fantasy/")


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["login", "collect"])
    args = parser.parse_args()
    if args.command == "login":
        login()
    else:
        collect()


if __name__ == "__main__":
    main()
