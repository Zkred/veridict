# GitHub OAuth setup for the reviewer UI

The issuer authenticates reviewers via a GitHub OAuth App. Five-minute setup:

## 1. Create the OAuth App

1. Go to <https://github.com/settings/developers>
2. **OAuth Apps** → **New OAuth App**
3. Fill in:
   - **Application name**: `Anonymous Review (local)`
   - **Homepage URL**: `http://localhost:8000`
   - **Authorization callback URL**: `http://localhost:8000/callback`
4. Click **Register application**
5. On the next page, click **Generate a new client secret**
6. Copy the **Client ID** and **Client secret**

## 2. Pick an org and ensure your account is a member

The issuer only mints credentials for members of `REQUIRED_ORG`. For a demo,
either:

- Create a free GitHub org (Settings → Organizations → New) and invite
  yourself, or
- Use an org you already belong to and set `REQUIRED_ORG` to its slug.

Membership is queried via `GET /orgs/{org}/memberships/{user}` — this needs
the `read:org` scope, which the OAuth app already requests.

## 3. Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Fill in `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and `REQUIRED_ORG`. Leave
the URL and binary path defaults alone unless you've changed them. The file
is git-ignored, so it's safe to commit secrets here.

Both `issuer/server.py` and `backend/main.py` auto-load this file on startup.

## 4. Launch the servers

```bash
# Terminal A — issuer with OAuth + UI
.venv/bin/python issuer/server.py

# Terminal B — backend
.venv/bin/python backend/main.py
```

## 5. Use the UI

1. Open <http://localhost:8000>
2. Click **Sign in with GitHub**
3. Authorize the OAuth app
4. On the dashboard, enter a PR slug as `owner/repo/N`
   (e.g. `octocat/Hello-World/1`) and click **Generate proof & approve**
5. Wait ~10s for circuit compile + proof generation
6. The result page shows the current approval count and whether the merge
   gate has flipped to passing

## What happens server-side on click

1. Server queries GitHub for the PR's HEAD SHA → forms `pr_key`
2. Mints an MDOC credential bound to that `pr_key` (single-use)
3. Runs `prover_cli` locally to produce a 360 KB ZK proof
4. Posts proof + `now` to the backend
5. Backend invokes `verifier_cli`, increments the approval count
6. UI shows the result; nobody downstream (CI, backend admin) ever sees the
   reviewer's identity — only that **a** credentialed reviewer approved

## Trust model recap

- **Issuer**: knows who you are, knows you approved which PR
- **Backend / CI / verifier**: sees only "valid ZK proof of a maintainer in
  $org", linked to a specific commit SHA
- The anonymity guarantee is *toward the verifier*, not the issuer. A
  fellowship-stage hardening would move proving client-side (browser WASM
  or local CLI) so the issuer never sees the device key.
