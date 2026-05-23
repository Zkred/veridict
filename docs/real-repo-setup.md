# Wiring this into a real GitHub repo

Goal: a real PR on a real repo can't merge until two anonymous reviewers
approve through your issuer UI. End state:

```
PR opened  ──► "zk-review-gate"  ✗ (0 / 2)
reviewer A signs in, clicks Approve
PR auto-rechecks ──► "zk-review-gate"  ✗ (1 / 2)
reviewer B signs in, clicks Approve
PR auto-rechecks ──► "zk-review-gate"  ✓ (2 / 2)  → Merge button enables
```

You'll need:
- A GitHub account
- A test repo you own (or admin access on one)
- ~20 minutes

---

## 1. Create a GitHub OAuth app

<https://github.com/settings/developers> → **OAuth Apps** → **New OAuth App**

| Field | Value |
|---|---|
| Application name | `Anonymous Review` |
| Homepage URL | `http://localhost:8000` |
| Authorization callback URL | `http://localhost:8000/callback` |

Click **Register**, then **Generate a new client secret**, then copy both
**Client ID** and **Client secret**.

## 2. Pick a GitHub org for membership checks

The issuer only mints credentials for members of `REQUIRED_ORG`. Options:

- Create a free org: <https://github.com/account/organizations/new> → pick "Free"
- Use any existing org you're a member of

Whatever you pick — your account must be a member with at least the
`Member` role.

## 3. Fill in `.env`

```bash
cd /Users/sarkazein./Documents/Personal/Hackathon/secure-program-synthesis-hackathon
$EDITOR .env
```

Set:
```
GITHUB_CLIENT_ID=<the client id>
GITHUB_CLIENT_SECRET=<the client secret>
REQUIRED_ORG=<your org slug>
DEV_MODE=0
```

Restart the issuer (`Ctrl+C` then run again) for the new env to take effect.

## 4. Expose the backend to the public internet

GitHub Actions runs in the cloud and can't reach `localhost:8001`. Use a
tunnel. Easiest is Cloudflare's free anonymous tunnel:

```bash
brew install cloudflared   # one time

# In a new terminal, kept running:
./scripts/expose.sh
```

The script prints a `https://<random>.trycloudflare.com` URL. **Copy it** —
you'll paste it into the GitHub secret in step 6.

> Alternative: `ngrok http 8001` if you already use ngrok.

## 5. Create the test repo (or use an existing one)

```bash
gh repo create my-anon-review-test --public --clone
cd my-anon-review-test
mkdir -p .github/workflows
cp /Users/sarkazein./Documents/Personal/Hackathon/secure-program-synthesis-hackathon/.github/workflows/anonymous-review-check.yml \
   .github/workflows/
git add . && git commit -m "wire anonymous review gate"
git push
```

## 6. Add the backend URL as a repo secret

```bash
gh secret set REVIEW_BACKEND_URL --body "https://<the trycloudflare url from step 4>"
```

(Or in the UI: **Settings → Secrets and variables → Actions → New repository secret**.)

## 7. Make the check required for merge

```bash
# Run a dummy commit so a workflow run exists, otherwise the next step
# won't see the check name yet.
echo "test" > README.md && git add README.md \
  && git commit -m "trigger workflow" && git push
sleep 30   # wait for the action to register

gh api -X PUT "repos/:owner/:repo/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["zk-review-gate"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
```

(Or in the UI: **Settings → Branches → Add branch protection rule** → branch
name pattern `main` → enable "Require status checks to pass" and add
`zk-review-gate`.)

## 8. Open a test PR and watch it fail the gate

```bash
git checkout -b test-pr
echo "change" >> README.md
git add . && git commit -m "test change"
git push -u origin test-pr
gh pr create --title "test the gate" --body "" --base main
```

Open the PR on GitHub — the "Anonymous Review Check / zk-review-gate" check
will run and **fail** with `0 / 2 anonymous reviewers approved`. That's
correct.

## 9. Approve via the UI

In your browser at <http://localhost:8000>:

1. Click **Sign in with GitHub**, authorize the OAuth app
2. Get the PR slug. Either:
   - 3-part form `owner/repo/N` — the issuer resolves the HEAD SHA from
     GitHub, or
   - 4-part form `owner/repo/N/sha` — you provide the SHA explicitly
     (faster, useful when you've just pushed)
3. Click **Generate proof & approve**

Wait ~10 seconds for the proof. The page shows `1 / 2 approvals`.

## 10. Get a second approval

The cheating-fast way for a single-person demo: open an incognito window,
sign in again (yourself counts as a "different" reviewer because each
session mints a fresh credential with a fresh nonce — this is exactly the
"no nullifier" gap noted in the README), approve the same PR.

Or have a teammate do step 9 too.

## 11. Re-run the workflow

```bash
gh pr checks --watch   # or click "Re-run failed jobs" on the PR page
```

The check should now pass: `OK: 2 / 2 anonymous reviewers approved`. The
**Merge** button becomes enabled.

---

## Day-of-demo failure modes

- **Cloudflared tunnel dropped** — restart `./scripts/expose.sh`, update the
  secret with the new URL, re-run the failing job.
- **OAuth callback URL mismatch** — must be exactly `http://localhost:8000/callback`.
  GitHub is strict about port and path.
- **`REQUIRED_ORG` set wrong** — check `gh api orgs/$REQUIRED_ORG/memberships/$YOU`
  returns 200.
- **Force-push to the PR branch** — invalidates all prior approvals (the
  `pr_key` includes the SHA). Reviewers must re-approve. This is a feature.
- **Workflow doesn't show as required** — usually means it never ran on the
  branch. Push a no-op commit, wait, then add the protection rule.
