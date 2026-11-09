# NHL model research and benchmark protocol

## Public methodological references (reviewed November 2026)

- MoneyPuck: https://www.moneypuck.com/about.htm — separates ability to win, scoring chances, and goaltending; reports component emphasis of 17%, 54%, 29%. Pregame forecasts also use rest and home ice. Its xG model is a separate shot-level gradient-boosted estimator. Do not assume these weights transfer to our data.
- PuckCast: https://puckcast.ai/how-it-works — regularized logistic regression (C=0.02), rolling performance, Elo variants, goaltending, shot quality and schedule context; walk-forward validation. Public pages differ on feature count (98 vs 158), so verify version before attempting replication.
- PuckCast performance: https://puckcast.ai/performance — reported 2025–26 log loss 0.682 on 1,312 games. Not a head-to-head comparison without matching target definitions and game identifiers.
- Independent Poisson/xG methodology: https://www.renenunez.dev/nhl/methodology — opponent-adjusted recent goals/xG, Poisson score grid and frozen pregame predictions.

## Implemented now

Run `python benchmark_models.py --games data/games.csv` after historical games are available locally.
Outputs `results/model_benchmarks.json` with season-by-season comparisons:
- constant training-prevalence probability
- Poisson baseline already in our project
- simple Elo-only logistic
- Elo, rest and form logistic
- broader pregame-feature regularized logistic, inspired by PuckCast (NOT its exact model)

The historical game dataset has five seasons; this first suite tests the last three with expanding training windows. No market prices are used as features.

## Next experiments, not yet implemented

1. Extend data to 10–15 seasons, handling shortened seasons and team changes. First check historical source coverage.
2. Add time-correct xG and scoring-chance data, using data availability timestamps and strictly prior games.
3. Add goalie identity, starter uncertainty, prior GSAx and workload, then ablate each feature family.
4. Evaluate a shot-quality-adjusted goals Poisson model and compare directly with logistic moneyline.
5. Try LightGBM only after simple baselines, with nested temporal tuning and a frozen holdout.
6. Benchmark historical market prices and Kalshi after matching games, market settlement definitions, timestamps, and fees.
7. Compare paired Brier and log-loss differences with date-block bootstrap confidence intervals, and report calibration by season.

## Non-negotiable validation rules

- Never train on data generated after the prediction cutoff; do not use same-game goals, xG, goalie identity learned after puck drop, or closing odds as pregame features.
- Preserve distinct NHL final moneyline and regulation outcomes. A tied regulation score resolved in OT/SO must not be treated as a regulation win.
- Never compare published accuracy or log loss across different seasons as though they were matched experiments.
- Require consistent improvement across seasons, adequate sample sizes, and uncertainty intervals before declaring an upgrade.
- No profitability claim without contemporaneous executable odds, liquidity, fees, and a properly separated test period.

## Deployment safety

All benchmark development is on `research/nhl-model-benchmarks`, not `main`. Do not merge until the persistent Railway historical download finishes and checkpoint recovery is verified.

## Forward paper validation

The research forecast workflow now captures public Kalshi order books after it
builds the pregame forecasts. Save each resulting capture artifact before it
expires. Use one precommitted snapshot per slate when aggregating results.

```sh
python research_kalshi_paper.py capture results/pregame_forecasts.json results/paper_capture.json
python research_kalshi_paper.py score results/paper_capture.json results/paper_score.json
```

Each capture keeps all forecasts and all discovered moneyline and total
contracts for the target slate, including skipped contracts and reasons. The
paper policy selects up to five positive-EV YES positions, one contract each,
using the observed opposite bid for entry and the series taker fee. The
market baseline is the observed YES midpoint. The scorer uses binary
finalized Kalshi settlements and retains unresolved or nonbinary outcomes
in its counts. A paper entry assumes the displayed depth remains available
and carries no slippage. Contract rows within a game are correlated, so
the number of scored contracts is not an independent sample size.
