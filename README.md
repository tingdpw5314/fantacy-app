# Yahoo Fantasy Basketball — Free Daily Collector

Collects **read-only** Yahoo Fantasy NBA leagues, roster, settings, and matchup scoreboard once per day at **8 AM America/Los_Angeles**, without leaving your computer on.

> This is a collector, not yet a ranking/lineup AI optimizer. It does not modify Yahoo rosters, perform trades, or send email. The separate ChatGPT Task cannot read these private GitHub Actions artifacts automatically.

## 1. Create a private GitHub repository

Create a **private** repo, such as `yahoo-fantasy-agent`, and upload all files from this folder. Keep `token_state.enc` in that private repo ONLY. Never upload `.env`.

## 2. Register OAuth local callback

In your authorized Yahoo Developer app, register the **exact** Redirect URI:

`http://127.0.0.1:8765/callback`

If Yahoo rejects loopback/http callback registrations, use an approved HTTPS callback and a different authorization bootstrap; do not try to bypass the redirect URI validation. Yahoo API access must have Fantasy Sports permission.

## 3. First-time setup on a computer (one time)

Python 3.10+ required.

```bash
python -m pip install -r requirements.txt
python agent.py keygen
```

Copy `.env.example` to `.env`. Set Client ID, Client Secret, generated `YAHOO_TOKEN_KEY` and matching callback URI, **only on your own computer**. Do not paste these into ChatGPT.

```bash
python agent.py login
python agent.py collect
```

Your browser will ask to authorize access. The CLI receives the one-time authorization code locally, exchanges it and saves encrypted `token_state.enc`. `collect` outputs `output/<UTC datetime>/my_teams.json` and per-league `league.json`, `settings.json`, `roster.json`, `scoreboard.json`.

## 4. Configure GitHub secrets

In **GitHub repo → Settings → Secrets and variables → Actions**, add three *repository secrets*, copying values from your `.env`:

- `YAHOO_CLIENT_ID`
- `YAHOO_CLIENT_SECRET`
- `YAHOO_TOKEN_KEY`

Commit `token_state.enc` to your **private** repo. This file is encrypted, but still treat it as sensitive. Do not commit `.env`, raw OAuth codes, raw tokens, or output JSON to a public repo. You must securely preserve the encryption key separately: without it the encrypted token cannot be decrypted.

## 5. Enable and test Actions

Repo → **Actions → Yahoo Fantasy Daily Collector → Run workflow**. Check it succeeds and download the private `fantasy-report` artifact. Scheduled runs follow `America/Los_Angeles`, including daylight saving changes. Schedules are best-effort, not guaranteed to start at the exact minute.

The job commits an updated encrypted token file only when Yahoo rotates/renews it. It needs repository **Workflow permissions: Read and write permissions** in GitHub Settings → Actions → General, and branch protection must permit its bot commit.

## Security / practical limitations

- All Fantasy API resource calls use **GET only**. OAuth token exchange uses POST (normal and necessary); this does not change Yahoo Fantasy data.
- Refresh tokens can rotate; the workflow must persist updates. Never reset `token_state.enc` from an older copy. If authentication fails or you lose the key, repeat local `login` and update `token_state.enc`.
- GitHub Actions workers are ephemeral. Encrypted token state in the private repository is a practical low-cost compromise, not ideal for production; use a cloud secret store for stronger separation and rotation.
- Fantasy outputs may contain team names and private league data. Keep artifacts private and apply GitHub access controls.
- The NBA season/team discovery API shape can differ across seasons; if discovery fails inspect `my_teams.json` from a private artifact. A 403 usually indicates missing Yahoo Fantasy API permissions.
- GitHub Free's private Actions minutes are subject to current plan quotas; the workflow does not need paid LLM APIs.
- No AI prediction logic is implemented yet; first verify real Yahoo league data retrieval.

Sources: https://sports.yahoo.com/developer/docs/ ; https://developer.yahoo.com/oauth2/guide/ ; https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
