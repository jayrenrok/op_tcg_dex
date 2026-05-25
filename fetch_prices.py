#!/usr/bin/env python3
"""
eBay price fetcher for One Piece TCG cards.

Reads card IDs from the bundled HTML's ALL_CARDS data,
queries eBay Browse API for each, computes price stats,
and writes prices.json to the repo root.

Designed to run as a nightly GitHub Action.

Environment variables required:
  EBAY_APP_ID   — App ID / Client ID
  EBAY_CERT_ID  — Cert ID / Client Secret

Output: prices.json keyed by Bandai card ID
  {
    "OP01-001": {
      "active_low": 4.99,
      "active_median": 8.50,
      "active_count": 12,
      "currency": "USD",
      "updated": "2026-05-25T03:00:00Z"
    },
    ...
  }
"""

import os
import sys
import json
import time
import re
import base64
import statistics
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote
from urllib.error import HTTPError

# ---------- Config ----------
EBAY_APP_ID = os.environ.get("EBAY_APP_ID")
EBAY_CERT_ID = os.environ.get("EBAY_CERT_ID")
if not EBAY_APP_ID or not EBAY_CERT_ID:
    print("ERROR: EBAY_APP_ID and EBAY_CERT_ID env vars are required", file=sys.stderr)
    sys.exit(1)

# Throttle settings — eBay free tier: 5000 calls/day. We have ~3000 cards.
# Run in batches with short delay to be respectful.
DELAY_BETWEEN_CALLS = 0.4   # seconds — ~150 calls/min
MIN_LISTINGS_TO_REPORT = 2  # don't show prices if only 1 listing (unreliable)

# eBay category 183454 = "Trading Card Games > CCG Individual Cards"
EBAY_CATEGORY_ID = "183454"

OUTPUT_PATH = "prices.json"
CARDS_INPUT_PATH = "all_cards.json"  # the source card data

# ---------- OAuth ----------
def get_oauth_token():
    """Get an application access token for the Browse API."""
    creds = base64.b64encode(f"{EBAY_APP_ID}:{EBAY_CERT_ID}".encode()).decode()
    body = urlencode({
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }).encode()
    req = Request(
        "https://api.ebay.com/identity/v1/oauth2/token",
        data=body,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No token in response: {data}")
    print(f"OAuth token acquired (expires in {data.get('expires_in', '?')}s)")
    return token


# ---------- Search ----------
def search_listings(token, card_id, card_name=""):
    """
    Search eBay for active listings of a card.
    Returns list of {price, currency, title} dicts.
    """
    # Query strategy: card ID is highly unique. Just searching the ID
    # (e.g. "OP01-001") is more reliable than including the name which
    # has many spelling variations.
    query = card_id
    params = {
        "q": query,
        "category_ids": EBAY_CATEGORY_ID,
        "limit": "50",
        "filter": "buyingOptions:{FIXED_PRICE},conditionIds:{1000|1500|2000|2500|3000|4000|5000}",
        "sort": "price",
    }
    url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?{urlencode(params)}"
    req = Request(url, headers={
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Accept": "application/json",
    })
    try:
        with urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
    except HTTPError as e:
        # 429 = rate limit; just skip this card and continue
        if e.code in (429, 500, 502, 503, 504):
            return None
        raise

    listings = []
    for item in data.get("itemSummaries", []):
        # Filter out obvious non-matches: only keep titles that contain
        # the card ID (eBay's free-text search can be loose)
        title = item.get("title", "")
        if card_id.lower() not in title.lower():
            continue
        # Skip lots, complete sets, sealed product, etc.
        title_lower = title.lower()
        if any(skip in title_lower for skip in [
            "lot of", "complete set", "playset", "(4x)", "x4 ", "4 x ",
            "booster box", "starter deck", "sealed pack", "case of",
            "graded", "psa ", "bgs ", "cgc ",  # graded cards skew prices
        ]):
            continue
        price_info = item.get("price", {})
        try:
            value = float(price_info.get("value", 0))
            currency = price_info.get("currency", "USD")
            if value > 0:
                listings.append({"price": value, "currency": currency, "title": title})
        except (ValueError, TypeError):
            continue
    return listings


def summarize(listings):
    """Convert raw listings into a compact stats dict."""
    if not listings or len(listings) < MIN_LISTINGS_TO_REPORT:
        return None
    # Group by currency, take the dominant one
    by_currency = {}
    for l in listings:
        by_currency.setdefault(l["currency"], []).append(l["price"])
    currency = max(by_currency.keys(), key=lambda c: len(by_currency[c]))
    prices = sorted(by_currency[currency])
    return {
        "active_low": round(prices[0], 2),
        "active_median": round(statistics.median(prices), 2),
        "active_count": len(prices),
        "currency": currency,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# ---------- Main ----------
def main():
    # Load card list
    with open(CARDS_INPUT_PATH, encoding="utf-8") as f:
        cards = json.load(f)

    # Deduplicate by Bandai ID — we only need to look up each unique ID once
    unique_ids = {}
    for c in cards:
        cid = c.get("id", "")
        if cid and cid not in unique_ids:
            unique_ids[cid] = c.get("name", "")

    print(f"Total cards in dataset: {len(cards)}")
    print(f"Unique IDs to look up: {len(unique_ids)}")

    # Allow LIMIT env var for testing (e.g., LIMIT=20 for a smoke test)
    limit = int(os.environ.get("LIMIT", "0"))
    items = list(unique_ids.items())
    if limit > 0:
        items = items[:limit]
        print(f"LIMIT set: only processing first {limit} cards")

    # Load existing prices.json if it exists, to merge with (preserves
    # cards we didn't fetch this run, useful for incremental updates)
    existing = {}
    if os.path.exists(OUTPUT_PATH):
        try:
            with open(OUTPUT_PATH) as f:
                existing = json.load(f)
            print(f"Merging with existing prices.json ({len(existing)} entries)")
        except Exception:
            pass

    # Get OAuth token
    token = get_oauth_token()

    # Process each card
    results = dict(existing)
    success = 0
    no_match = 0
    failed = 0
    start = time.time()

    for i, (card_id, card_name) in enumerate(items, 1):
        try:
            listings = search_listings(token, card_id, card_name)
            if listings is None:
                # Rate-limit or server error — refresh token and continue
                print(f"  [{i}/{len(items)}] {card_id}: rate-limit; sleeping 5s")
                time.sleep(5)
                token = get_oauth_token()
                continue

            stats = summarize(listings)
            if stats:
                results[card_id] = stats
                success += 1
                if i % 25 == 0 or i <= 5:
                    print(f"  [{i}/{len(items)}] {card_id}: "
                          f"{stats['currency']} {stats['active_low']}-"
                          f"{stats['active_median']} ({stats['active_count']} listings)")
            else:
                no_match += 1
                if i % 100 == 0:
                    print(f"  [{i}/{len(items)}] {card_id}: no listings")
        except Exception as e:
            failed += 1
            print(f"  [{i}/{len(items)}] {card_id}: ERROR {e}")

        time.sleep(DELAY_BETWEEN_CALLS)

    elapsed = time.time() - start
    print(f"\nFinished in {elapsed/60:.1f} min")
    print(f"  Cards with prices: {success}")
    print(f"  No listings found: {no_match}")
    print(f"  Errors: {failed}")

    # Write the merged results
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, separators=(",", ":"))

    size_kb = os.path.getsize(OUTPUT_PATH) / 1024
    print(f"\nWrote {OUTPUT_PATH} ({size_kb:.1f} KB, {len(results)} cards)")


if __name__ == "__main__":
    main()
