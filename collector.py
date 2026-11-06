#!/usr/bin/env python3
"""Public Kalshi NHL market snapshot collector; Python standard library only."""
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.elections.kalshi.com/trade-api/v2"
DB = Path(os.getenv("KALSHI_DB", "data/kalshi.sqlite"))
SERIES = [s.strip() for s in os.getenv("KALSHI_SERIES", "KXNHLGAME").split(",") if s.strip()]
MAX_EVENTS = int(os.getenv("MAX_EVENTS_PER_SERIES", "150"))
MAX_MARKETS = int(os.getenv("MAX_MARKETS_PER_RUN", "400"))
DEPTH = int(os.getenv("ORDERBOOK_DEPTH", "10"))
USER_AGENT = "kalshi-nhl-public-research-collector/0.1"

def get(path, params=None):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 401, 403, 404):
                raise
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)

def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

def setup(conn):
    conn.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
        status TEXT NOT NULL, events_seen INTEGER DEFAULT 0,
        markets_seen INTEGER DEFAULT 0, books_saved INTEGER DEFAULT 0,
        errors TEXT
    );
    CREATE TABLE IF NOT EXISTS events (
        event_ticker TEXT PRIMARY KEY, series_ticker TEXT, title TEXT,
        subtitle TEXT, raw_json TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS markets (
        ticker TEXT PRIMARY KEY, event_ticker TEXT, title TEXT, subtitle TEXT,
        status TEXT, close_time TEXT, raw_json TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
        captured_at TEXT NOT NULL, ticker TEXT NOT NULL,
        yes_bid TEXT, yes_ask TEXT, no_bid TEXT, no_ask TEXT,
        volume TEXT, open_interest TEXT, market_json TEXT NOT NULL,
        orderbook_json TEXT, book_error TEXT,
        UNIQUE(run_id, ticker)
    );
    CREATE INDEX IF NOT EXISTS idx_snapshots_ticker_time ON snapshots(ticker,captured_at);
    CREATE TABLE IF NOT EXISTS outcomes (
        ticker TEXT PRIMARY KEY, result TEXT, status TEXT,
        recorded_at TEXT NOT NULL, raw_json TEXT NOT NULL
    );
    """)

def list_events(series):
    cursor = None
    count = 0
    while count < MAX_EVENTS:
        params = {"series_ticker": series, "limit": min(100, MAX_EVENTS-count)}
        if cursor:
            params["cursor"] = cursor
        payload = get("/events", params)
        batch = payload.get("events") or []
        for event in batch:
            yield event
            count += 1
            if count >= MAX_EVENTS:
                break
        next_cursor = payload.get("cursor")
        if not batch or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

def market_list(event_ticker):
    cursor = None
    while True:
        params = {"event_ticker": event_ticker, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        payload = get("/markets", params)
        batch = payload.get("markets") or []
        for market in batch:
            yield market
        next_cursor = payload.get("cursor")
        if not batch or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor

def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    setup(conn)
    started = utc_now()
    run_id = conn.execute("INSERT INTO runs(started_at,status) VALUES (?,?)", (started,"running")).lastrowid
    conn.commit()
    events_seen = markets_seen = books_saved = 0
    errors = []
    seen = set()
    try:
        for series in SERIES:
            for event in list_events(series):
                event_ticker = event.get("event_ticker")
                if not event_ticker:
                    continue
                events_seen += 1
                conn.execute("""INSERT INTO events VALUES (?,?,?,?,?,?)
                    ON CONFLICT(event_ticker) DO UPDATE SET series_ticker=excluded.series_ticker,
                    title=excluded.title, subtitle=excluded.subtitle,
                    raw_json=excluded.raw_json,updated_at=excluded.updated_at""",
                    (event_ticker,series,event.get("title"),event.get("sub_title"),
                     json.dumps(event,separators=(",",":")),started))
                for market in market_list(event_ticker):
                    ticker = market.get("ticker")
                    if not ticker or ticker in seen:
                        continue
                    seen.add(ticker)
                    status = market.get("status","")
                    conn.execute("""INSERT INTO markets VALUES (?,?,?,?,?,?,?,?)
                        ON CONFLICT(ticker) DO UPDATE SET event_ticker=excluded.event_ticker,
                        title=excluded.title,subtitle=excluded.subtitle,status=excluded.status,
                        close_time=excluded.close_time,raw_json=excluded.raw_json,
                        updated_at=excluded.updated_at""",
                        (ticker,event_ticker,market.get("title"),market.get("subtitle"),
                         status,market.get("close_time"),
                         json.dumps(market,separators=(",",":")),started))
                    if status not in ("active","open"):
                        if status in ("settled","finalized") or market.get("result") in ("yes","no"):
                            conn.execute("""INSERT INTO outcomes VALUES (?,?,?,?,?)
                                ON CONFLICT(ticker) DO UPDATE SET result=excluded.result,
                                status=excluded.status,recorded_at=excluded.recorded_at,
                                raw_json=excluded.raw_json""",
                                (ticker,market.get("result"),status,started,json.dumps(market,separators=(",",":"))))
                        continue
                    if markets_seen >= MAX_MARKETS:
                        break
                    markets_seen += 1
                    book_json = None
                    book_error = None
                    try:
                        book = get("/markets/" + urllib.parse.quote(ticker,safe="") + "/orderbook",
                                   {"depth":DEPTH})
                        book_json = json.dumps(book,separators=(",",":"))
                        books_saved += 1
                    except Exception as exc:
                        book_error = str(exc)[:500]
                        errors.append(ticker + ": " + book_error)
                    conn.execute("""INSERT INTO snapshots
                        (run_id,captured_at,ticker,yes_bid,yes_ask,no_bid,no_ask,
                         volume,open_interest,market_json,orderbook_json,book_error)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (run_id,utc_now(),ticker,
                         str(market.get("yes_bid_dollars","")),
                         str(market.get("yes_ask_dollars","")),
                         str(market.get("no_bid_dollars","")),
                         str(market.get("no_ask_dollars","")),
                         str(market.get("volume_fp",market.get("volume",""))),
                         str(market.get("open_interest_fp",market.get("open_interest",""))),
                         json.dumps(market,separators=(",",":")),book_json,book_error))
                if markets_seen >= MAX_MARKETS:
                    break
            if markets_seen >= MAX_MARKETS:
                break
        status = "ok" if books_saved > 0 and not errors else ("partial" if books_saved else "no_active_books")
    except Exception as exc:
        errors.append("FATAL: "+repr(exc))
        status = "failed"
    conn.execute("""UPDATE runs SET finished_at=?,status=?,events_seen=?,markets_seen=?,
        books_saved=?,errors=? WHERE id=?""",
        (utc_now(),status,events_seen,markets_seen,books_saved,json.dumps(errors),run_id))
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print(json.dumps({"run_id":run_id,"status":status,"events":events_seen,
                      "active_markets":markets_seen,"books":books_saved,"errors":errors[:8]}))
    if status == "failed":
        sys.exit(1)

if __name__ == "__main__":
    main()
