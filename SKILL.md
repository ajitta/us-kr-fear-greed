---
name: market-sentiment-briefings
description: Use when asked for US/KR fear & greed or a sentiment briefing. Fetch, cross-check, schedule daily.
version: 1.0.0
author: ajitta
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [Fear and Greed, CNN, KOSPI, Korea, Sentiment, Briefing, Cron, Finance]
    homepage: https://github.com/ajitta/us-kr-fear-greed
---

# Market Sentiment Briefings (US CNN + Korea fear & greed)

Use when asked for fear & greed, market sentiment, or a recurring market-index briefing.
`scripts/fear_greed.py` fetches the US CNN index and three Korean indices into a structured data
block; the agent writes the briefing from it. Daily job: weekdays 08:30 KST (see Scheduling).

## Install / share / release

`bash scripts/install.sh [--cron [<deliver>]]` copies the skill to `$HERMES_HOME/skills/research/`,
the collector to `$HERMES_HOME/scripts/fear_greed.py` (cron scripts must live there), smoke-tests every
source, and optionally creates the 08:30 KST weekday job with `references/cron-prompt.md`.
Canonical source: public repo `ajitta/us-kr-fear-greed` (working copy `~/work/us-kr-fear-greed`).
Every change ships as: `git fetch && git status` (rebase if behind) → diff this installed SKILL.md
against the working copy and carry over installed-only edits → edit + test with
`FG_STATE_DIR=<scratch> python3 scripts/fear_greed.py --force` → `bash scripts/install.sh` (under a
Hermes profile also `cp scripts/fear_greed.py ~/.hermes/scripts/`) → bump `version:` → commit → push
main → tag `vX.Y.Z` → push tag → `gh release create` with a one-line Korean changelog. If the cron
prompt changes, update `references/cron-prompt.md` and the live job (`hermes cron edit <id> --prompt`).

## Always-on rules

- **Never invent or interpolate a number.** Every figure comes from this run's data block. A failed
  source is written as "데이터 수집 실패"; analyze the rest.
- **Korea has no official index — report every source side by side, each with its own as-of date.**
  Sources update on different days (siglens often lags kospifgi by one session); compare scores only
  on the same date (the script prints a same-date pair). A single number presented as "the" Korean
  reading is a factual error.
- **Never compare absolute values across differently-computed indices.** US CNN vs any Korean index:
  direction and component structure only. Close with the one-line caveat.
- **Any probability or expected range must come from a back-tested baseline, never from LLM
  judgment alone.** This briefing gives none. If one is ever added, ship a script that fits it on
  history and prints walk-forward skill; let the agent adjust only within a capped band with a named
  reason, and score baseline and final separately. Worked example: `kospi-morning-forecast`.
- Output: Korean, bullets, no tables, ≤1800 chars (15 components with full raws alone take ~1500 — list scores on one line, raws only for the 2–3 key ones). Headline score + rating first, then components,
  then interpretation, then the caveat line.

## Procedure

1. Read the injected block (`fear_greed.py` output). `갱신 상태` says which markets have new data;
   a market marked `직전 브리핑과 같은 세션/기준일` had no session (holiday) — say so, skip its deltas.
2. Write the briefing per `references/cron-prompt.md`: US block, KR block (kospifgi components +
   three sources with dates), US–KR structure / contrarian read / 1–2 threshold signals, caveat.
3. Change since the last briefing comes from section 4 (local state file), not from chat history.

## Sources (verified 2026-10)

- **US — CNN** `production.dataviz.cnn.io/index/fearandgreed/graphdata` (JSON): headline score,
  CNN's comparison points (`previous_close`, 1w, 1m, 1y), 7 components, `fear_and_greed_historical`.
- **KR primary — kospifgi.com**: 8 indicators (KRX Open API + BOK ECOS), previous-close basis,
  publishes from 08:10 KST. The page is a Next.js app; the numbers are in the flight data
  (`self.__next_f.push` chunks): `initialLatest`, `initialHistory` (≈60 sessions),
  `initialComponentCharts` (per component `latest_score`, `latest_regime`, `points[-1]` raw/baseline).
- **KR cross-check — siglens.io/fear-greed/kr**: 5 factors, percentile-ranked, equal-weighted,
  ETF/index closes, realised volatility instead of V-KOSPI. Server-rendered text: score, as-of date
  (`YYYY년 M월 D일 종가 기준`), 1w/1m/1y, factor percentiles.
- **KR cross-check — feargreed.co.kr**: realtime, KIS Open API. JSON at `feargree-api.vercel.app/api`
  (send `Referer: https://feargreed.co.kr/`). 65% of its stated weight is one-day % change
  (momentum 25, strength 15, trend 15, KOSDAQ 10), so it swings with a single big day (10/28 KOSPI
  +6.6% → 84 extreme greed while kospifgi read fear); `kr.vkospi_source` can be `estimated`.

## Pitfalls

- **CNN blocks a default UA** (`I'm a teapot`). Send a desktop browser `User-Agent` plus
  `Referer`/`Origin: https://edition.cnn.com`.
- **CNN history: keep the LAST point per day and drop days after the reading's US session.** Each
  day starts with a carried-forward 00:00 point and gets recomputed after the close; keeping the first
  point showed stale values and a placeholder for "today".
- **CNN `previous_close` ≠ the history value for that day by a few points** (10-26: 27.3 vs 29.8) — the
  history is recomputed after the close. Normal; don't flag it as a data error (the old briefing did so
  every day). It means "close before the reading's ET date": at 08:30 KST that is the prior session,
  but a reading taken before the next ET open (e.g. a 17:00 KST rerun) has `previous_close` = the same
  session, so the script then takes day-over-day change from the history instead.
- **`market_momentum_sp500` is the S&P level, `market_momentum_sp125` its 125-day MA**, same score.
  Print one score with both raws; never label the MA as the index level.
- **Ignore the per-datapoint `rating` inside CNN components' `data[]`.** Use only the component's own
  `score`/`rating`. Never infer a rating from a raw value — scores are long-history percentiles.
- **A text dump of a JS-rendered page yields labels without numbers** (kospifgi showed only "공포",
  feargreed.co.kr "데이터 로딩 중"). Look for the flight data / backing JSON instead of scraping text.
- **Skip no-data days by data change, not a holiday table:** the script compares the CNN session and
  kospifgi date with the state file and prints `{"wakeAgent": false}` when neither moved. A KRX-only
  holiday still runs (US moved) and the KR block is marked unchanged.
- **Prefer the state file over `continuity`** — continuity injects the previous delivered text, so a
  test run or corrected report anchors the next one. State: `~/.hermes/data/fear_greed/state.json`
  (`FG_STATE_DIR` override). Manual `hermes cron run` and `--force` runs update it too.

## Scheduling

- CNN settles after the US close (~06:00 KST); kospifgi publishes from 08:10 KST →
  **`30 8 * * 1-5`** (weekdays 08:30 KST).
- Job = `--script fear_greed.py --skill market-sentiment-briefings`, prompt from
  `references/cron-prompt.md`, toolsets web+terminal, no continuity.
- Cross-check the first delivered report against a news wrap for 2–3 numbers before calling a new
  job done — portal APIs can silently switch price basis.

## Self-refine

When asked to review a delivered analysis, re-fetch and re-verify the numbers rather than rereading
your prose. Errors are almost always in the data layer — misread field, duplicated or stale series
point, mismatched as-of dates, single-source overconfidence. State corrections as errors found, fix
the collector and prompt so they can't recur, keep the conclusions that survived.
