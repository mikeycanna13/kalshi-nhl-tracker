# NHL/Kalshi market-relative research: data contract and validation gates

This is a research-only system. A successful CI run or an estimated positive
EV **does not** establish trading profitability or an executable fill.

## What is implemented

- A reproducible regularized-logistic model over completed historical NHL scores.
- A time-stamped pregame capture of NHL game win and supported goal totals
  compared to Kalshi YES/NO orderbooks, with frozen selection records.
- A provenance audit that rejects after-the-fact forecast/quote timestamps and
  separately labels **operational pregame** versus **historical point-in-time replay**.
- An independent sportsbook comparison based on The Odds API v4 two-way h2h
  **decimal odds**. It removes each bookmaker's proportional overround, then
  takes the median of at least three distinct, fresh bookmakers.
- A strictly **opt-in** live sportsbook ingestion script. Standard CI does not
  use an API key or consume provider quota.

## How the fair-value comparison works

For bookmaker decimal prices D_home and D_away:

    home_fair = (1/D_home) / (1/D_home + 1/D_away)

This method assumes the overround can be allocated proportionally and is NOT
a guarantee of the true price. It is an intentionally simple reference benchmark.
Median consensus does not imply participating sportsbooks are independent.

Join requirements:
1. Market and NHL game must have the identical home and away teams, matched
   from an explicit canonical name table. Start times agree within 30 minutes.
   Duplicate plausible games are rejected, not guessed.
2. UTC forecast generation <= sportsbook snapshot <= Kalshi quote < puck drop.
3. The sportsbook snapshot is within 15 minutes before the Kalshi quote.
4. Individual bookmaker quotes were actually updated <= snapshot and no more
   than 15 minutes before Kalshi quote. Duplicated bookmaker keys count once.
5. Three or more distinct bookmakers offer unambiguous 2-way full-game h2h
   prices. Three-way regulation markets and incomplete data are rejected.
6. No historical sportsbook prices are fabricated or backfilled.

Model quality is evaluated by Brier/log loss against this **same timestamp**
benchmark on finalized game outcomes, not by synthetic unit tests.

## Using a purchased/supplied sportsbook feed

The Odds API supports NHL h2h snapshots (sport icehockey_nhl). Its historical
endpoint requires a paid usage plan. No historical queries are made by this
repository. Historical JSON may be passed separately:

    python research_market_benchmark.py --capture results/paper_capture.json \
      --odds-snapshot path/to/point_in_time_odds.json \
      --output results/sportsbook_benchmark.json

The snapshot must contain source=the_odds_api_historical, timestamp=<real
provider snapshot UTC> and data=<unmodified provider event list>. The original
response, request time and provenance must be preserved; never replace past
data with prices retrieved later. Older screenshots do not retroactively make
a model generated today into a historical pregame model.

For optional **live** benchmark collection only, supply THE_ODDS_API_KEY as a
GitHub Actions secret and explicitly launch the *NHL research pregame forecasts*
workflow via workflow_dispatch with collect_sportsbook=true. That consumes the
provider's API quota. If omitted, the workflow writes an explicit
not_requested record, makes **zero** sportsbook network requests, and reports
no paired sportsbook benchmark. Push-triggered CI never makes paid calls.

## Provenance

Every newly generated forecast records the SHA256 of its completed-game CSV,
its read time, model code commit, latest included game date and generated
timestamp. The audit distinguishes these *operational* safeguards from
historical-replay claims. Source versions of older NHL results, MoneyPuck xG,
goalie news, injuries and official result publication times are NOT yet
documented sufficiently to claim historically reconstructed information sets.

Each frozen capture contains its contract rules, market metadata, sides, quotes,
forecast, timestamps and fee assumptions. Series-level fees are not proof that
event-level overrides or final actual trading charges are captured.

## Next evidence gates

1. Obtain an authorized, point-in-time NHL sportsbook history from a provider.
2. Validate raw sources, event IDs, clock precision, overround, book staleness
   and original market-vs-game settlement semantics.
3. Compare standalone model, sportsbook-only and *candidate* market-anchored
   model on identical, non-leaky forward predictions.
4. Freeze model variants, reference datasets, edge thresholds and timing windows
   before prospective evaluation. Use dates/games as clustered observations;
   YES/NO or correlated total strikes are not independent samples.
5. Score calibration, Brier, log loss, market-improvement uncertainty and
   observable closing-line movement. Distinguish theoretical EV from realistic
   fill simulation, liquidity and net paper PnL.
6. Add Kalshi event-specific fee override checks and live depth/latency
   assumptions before claiming an actionable edge.

**Go/no-go criterion:** a credible, repeatable improvement versus the
contemporaneous sportsbook benchmark after explicit costs, with intervals
excluding no edge in genuinely forward data. Until then, model candidates
remain research observations, not recommended trades.


## Forward evidence and settlement (research branch only)

Every successful pregame run archives a single validated evidence record under
`forward_evidence/YYYY-MM-DD/<GITHUB_RUN_ID>.json` on the research branch.
The archive includes the per-game forecast, source hash, contract-selection
metadata, both sides of observed Kalshi quotes, fee assumption, candidate flags,
and a point-in-time audit. To keep Git history manageable, redundant raw market
responses are omitted from **new** archive records; the full original capture
remains in the 90-day GitHub Actions artifact.

Archive records are append-only by path, checksummed, and checked by
`test_research_forward_ledger.py`. The archive is not a complete immutable
external data vault or a guarantee that repository administrators cannot rewrite
Git history. No paid sportsbook raw responses, API keys, or third-party private
data are intentionally persisted to Git.

The forward ledger summary selects the **earliest validated capture for each
NHL target date** and records how many eligible snapshots and selected paper
positions were retained. This is not yet a fixed-clock capture policy:
development commits can trigger irregularly timed captures. Future conclusions
must disclose this selection rule.

Once Kalshi contracts finalize, use the research-only scorer:

    python research_forward_score.py --base forward_evidence \
      --out results/forward_paper_score.json

Or run the **NHL multi-date forward paper-score research** workflow manually.
It checks the public Kalshi market status for each distinct ticker, ignores
unfinalized/void results, and scores one selected paper portfolio per game date.
Moneyline calibration is one observation per NHL game (not one per YES/NO side).
It never records actual fills.

### Automation constraint

GitHub Actions `schedule` workflows execute from the repository's default
branch, not a research-only branch. To respect the explicit restriction against
changing production/main, **no unattended daily capture schedule has been
activated**. Code-push research runs and manually dispatched research-branch
runs can archive evidence. A daily fixed-time schedule would require a separate
authorized scheduling mechanism; never assume it is active.

### What this cannot prove

The archive does not make unversioned injury/xG history point-in-time correct,
nor can it substitute for historical sportsbook snapshots. Positive modeled EV
and positive paper ROI based on inferred best asks remain hypothetical until
actual quote fillability, fee overrides and statistically credible out-of-sample
performance are established.
