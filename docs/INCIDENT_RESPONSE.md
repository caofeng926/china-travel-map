# Secret-Incident Response

If an AMap Web Service API key, deploy key, or any other secret is **ever committed to this repository** (even briefly, even in a deleted commit), follow this runbook.

## 0. Do NOT panic-push history rewrites

`git filter-repo` / `git filter-branch` rewrites every clone and every PR branch. That is destructive — it requires every collaborator to re-clone, and it does not remove the secret from forks, GitHub's API cache, or `git log --reflog` on anyone who already fetched it.

**Treat the secret as compromised the moment it lands on `main`, regardless of how quickly you remove it.**

## 1. Immediate containment (within minutes)

1. **Rotate the leaked credential first.** New key from AMap console / GitHub Deploy Keys / wherever the secret came from. Do this before cleanup.
2. **Revoke the old key** (or at minimum, set strict HTTP referrer / IP allowlist on it until rotation completes).
3. **Update deployment**:
   - If using GitHub Actions secrets: update `Settings → Secrets and variables → Actions`.
   - If using `.env` on the server: SSH in, edit `/etc/china-travel-map.env`, restart the service.

## 2. Audit blast radius

```bash
# Search all branches and tags for any other occurrence of the secret value.
git log --all -p -S '<secret_value>' --pretty=format:'%H %an %ad' | head

# Check GitHub API for any pull requests that referenced the secret.
gh pr list --state all --search '<secret_value>'
```

Verify whether the secret was reachable via:
- `https://github.com/<owner>/<repo>/blob/<sha>/<file>` (any past commit)
- forks (`https://github.com/<fork>/<repo>`)
- archive mirrors (e.g., GHArchive, Zenodo)
- GitHub's REST API (`GET /repos/<owner>/<repo>/contents/<path>?ref=<sha>` returns the file content even after the commit is "removed")

If the secret was reachable on github.com for more than a few minutes, **assume it has been scraped**.

## 3. Cleanup options (pick by severity)

### 3a. Quick cleanup (secret was short-lived / never deployed)

Just delete the commit in a follow-up PR or revert. The rotation in step 1 is what actually protects you.

```bash
git revert <bad_sha>
git push origin main
```

### 3b. Full history rewrite (secret was long-lived / widely reachable)

```bash
# Install git-filter-repo if needed:
#   pip install git-filter-repo   OR
#   brew install git-filter-repo

git filter-repo --invert-paths --path <file_with_secret>
git remote add origin git@github.com:<owner>/<repo>.git
git push origin --force --all
git push origin --force --tags
```

**Before running this:**
- Coordinate with all active collaborators — they MUST re-clone.
- Disable branch protection temporarily so the force-push goes through.
- Confirm `GITHUB_TOKEN` and `AMAP_KEY` are available in Actions secrets (they were never in git).
- After the push, file a support request via https://support.github.com/contact to ask GitHub to purge cached views and forks.

## 4. Post-incident

1. Add a CI guard so the same secret shape cannot land again — `.github/workflows/secret-scan.yml` already runs `gitleaks/gitleaks-action@v2` on every push and weekly.
2. Add the offending pattern to `docs/code_review.md` as a "lesson learned" entry.
3. Move any previously-leaked-but-still-valid keys to a new rotated set, and verify no service is still using the old one (check server logs for the old key string).
4. Document the incident in your internal postmortem log.

## Prevention checklist

- [ ] All API keys live in `.env` (gitignored) or GitHub Actions secrets, never in source.
- [ ] Local `.env.example` files contain placeholders only.
- [ ] Pre-commit hook (`lefthook` / `pre-commit`) runs `gitleaks protect --staged`.
- [ ] CI workflow fails the build on any leaked secret — see `.github/workflows/secret-scan.yml`.
