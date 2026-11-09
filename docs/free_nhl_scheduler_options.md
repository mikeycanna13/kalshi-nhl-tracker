# $0 incremental-cost scheduling options for NHL/Kalshi research

**Current state:** all code lives on `research/nhl-model-benchmarks`. There is
no scheduled Railway research service, no active Cloudflare deployment, and no
automatic Cloudflare-triggered capture yet. No trading or sportsbook purchases.

## Available zero-incremental-cost choices

### A. Cloudflare Workers Free — does not modify `main` (prepared)

Free Worker cron checks the public NHL schedule every 10 minutes and creates
an **append-only** GitHub Contents API trigger in this repository's research
branch only when games reach a 10 AM ET, two-hour, or 15-minute pregame window.
That `push` activates the existing research-branch GitHub Actions workflow,
which builds forecasts and archives Kalshi research evidence.

- GitHub repository is public, so standard GitHub-hosted Actions runner minutes
  are free (subject to GitHub's policies, availability and storage constraints).
- Cloudflare Workers Free includes 100,000 requests/day, five Cron Triggers and
  10 ms CPU per scheduled invocation as of November 2026. Usage above free-plan
  limits may fail rather than execute; monitor CPU/limit errors.
- No Railway service, no paid sportsbook connector and no trading API required.
- The Worker is **not deployed yet**. Account login and adding a secret are
  user actions; the `ENABLE_TRIGGER_WRITES` flag defaults to `false`.

Deployment:

1. Create or select a Cloudflare account on **Workers Free**.
2. In a checked-out copy of this research branch, run
   `npx wrangler login`.
3. Run `npx wrangler deploy --config scheduler/wrangler.toml` while
   `ENABLE_TRIGGER_WRITES = "false"`, and inspect scheduled logs.
4. Create a **fine-grained GitHub PAT** scoped to this repository only, with
   repository Contents **read/write**. Set a short expiration. Protect `main`
   with GitHub branch rules because Contents permissions are not automatically
   confined to the research branch.
5. Run `npx wrangler secret put GITHUB_RESEARCH_TOKEN --config scheduler/wrangler.toml`.
   Never place the token in git, ChatGPT messages, environment files or public
   logs. The Worker code only writes to `research/nhl-model-benchmarks`.
6. After dry-run behavior is verified, set `ENABLE_TRIGGER_WRITES = "true"`
   in `scheduler/wrangler.toml` and redeploy. Confirm the exact free plan and
   usage ceilings before enabling triggers.
7. At the next due pregame window, verify a unique file under
   `scheduler/triggers/YYYY-MM-DD/`, a triggered pregame workflow, frozen
   `scheduler_context`, an operational timestamp audit and a research-only
   `forward_evidence/` archive.

**Security caution:** A PAT with Contents write permission is a significant
credential even when our code is restricted to the research branch. Use branch
protection and a dedicated expiring token. Revoke the token if retiring Worker.

### B. GitHub Actions only — simpler, but changes one file on `main`

Add a minimal, isolated scheduling workflow on `main` which checks out the
research branch and orchestrates the safe research workflow. GitHub native
`schedule` does **not** run solely from a non-default branch. This option
avoids Cloudflare and any external API token, but requires **explicit approval
before changing `main`**, as this project has a strict main-branch exclusion.
No change to production Python code or Railway would be necessary.

### C. Manual GitHub Actions research runs — already possible

Code changes on the research branch currently trigger smoke collections.
These aren't dependable fixed-clock forward samples. Use for development and
troubleshooting only; do not claim this as an unattended daily scheduler.

### D. Railway Cron

It would avoid an external token runner, but might incur Railway charges, so
it remains disabled.

## What has been implemented and tested

- `scheduler/cloudflare_worker.mjs`: purely public NHL schedule GETs plus
  authenticated create-only research trigger PUT when explicitly enabled.
- `scheduler/wrangler.toml`: 10-minute cron, writes **disabled** by default.
- `scheduler/test_cloudflare_worker.mjs`: daylight-saving, puck-drop windows,
  duplicate grouping, dry-run and branch-scoping tests.
- `research_scheduler/resolve_target.py`: validates triggered path, schema,
  branch, game IDs and requested game date from the original push commit.
- `research_scheduler/annotate_capture.py`: stamps collection-window
  provenance on frozen research evidence before archival.
- `research_nhl_pregame_forecast.py`: accepts an Eastern evening game target
  after UTC midnight, while retaining strict UTC pregame prediction checks.
- `research_forward_score.py`: can evaluate the first frozen observation of
  each window independently, but window-specific results remain correlated.

## Limits and warnings

GitHub workflow startup can be delayed, so a 15-minute pregame trigger might
produce no valid pregame quotes; the timestamp audit rejects after-the-fact
observations. More than one same-day window is **not** an independent sporting
outcome: never sum their paper results as though separate observations.
Live market bids are not guaranteed fills; series-level fees may not incorporate
event-level overrides. Using only public NHL/Kalshi prices cannot demonstrate
the model beats independently timestamped sportsbook consensus.

### Sources
- https://docs.github.com/en/actions/concepts/billing-and-usage
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/actions/concepts/security/github_token
- https://developers.cloudflare.com/workers/platform/pricing/
- https://developers.cloudflare.com/workers/configuration/cron-triggers/
