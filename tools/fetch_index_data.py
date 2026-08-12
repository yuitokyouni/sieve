"""Fetch daily index closes for single-index suite building.

Downloads (timestamp, close) pairs from the Yahoo Finance chart API into
``data/index_cache/`` (gitignored — raw index data is not redistributed;
suites ship only derived window statistics plus the source hash so anyone
re-fetching the same window can verify they hold the same source, exactly
like financial-daily@1.0.0).

Usage:
    python tools/fetch_index_data.py ^GSPC spx
    python tools/fetch_index_data.py ^N225 nikkei
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CACHE = Path(__file__).resolve().parents[1] / "data" / "index_cache"


def fetch(symbol: str, key: str, range_: str = "30y") -> Path:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(symbol)}?range={range_}&interval=1d")
    req = urllib.request.Request(
        url, headers={"User-Agent": "sieve-suite-builder/0.1 (research)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    res = data["chart"]["result"][0]
    rows = [(dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), c)
            for t, c in zip(res["timestamp"],
                            res["indicators"]["quote"][0]["close"])
            if c is not None]
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{key}_daily.csv"
    with open(out, "w") as f:
        f.write("timestamp,price\n")
        for d, c in rows:
            f.write(f"{d},{c:.6f}\n")
    print(f"{symbol} -> {out}: {len(rows)} rows, {rows[0][0]} .. {rows[-1][0]}")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: fetch_index_data.py SYMBOL KEY   (e.g. ^GSPC spx)")
    fetch(sys.argv[1], sys.argv[2])
