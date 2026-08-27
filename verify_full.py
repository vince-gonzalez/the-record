# ============================================================
# THE RECORD - full-chain verifier v0.1.0
# Walks the proof slice + every run shard as ONE chain from genesis.
# Run: python verify_full.py
# F-Keys | www.f-keys.com
# ============================================================

import glob
import hashlib
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("RECORD_DATA", r"C:\Users\Admin\the-record-data")
GENESIS = "THE-RECORD-GENESIS-2026"


def canonical(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def main():
    files = [os.path.join(HERE, "ledger.jsonl")] + sorted(
        glob.glob(os.path.join(DATA, "ledger-*.jsonl")))
    prev = hashlib.sha256(GENESIS.encode()).hexdigest()
    n = 0
    jurisdictions = {}
    gsi_seen = 0
    t0 = time.time()
    for path in files:
        for line in io.open(path, encoding="utf-8"):
            row = json.loads(line)
            n += 1
            if row["seq"] != n:
                raise SystemExit("FAIL %s at %d: seq %s"
                                 % (path, n, row["seq"]))
            if row["prev_hash"] != prev:
                raise SystemExit("FAIL at %d: prev_hash broken" % n)
            expect = hashlib.sha256(
                (prev + canonical({k: v for k, v in row.items()
                                   if k not in ("prev_hash", "row_hash")})
                 ).encode("utf-8")).hexdigest()
            if row["row_hash"] != expect:
                raise SystemExit("FAIL at %d: row_hash mismatch" % n)
            prev = row["row_hash"]
            j = row["jurisdiction"] or "?"
            jurisdictions[j] = jurisdictions.get(j, 0) + 1
            gsi_seen += 1
            if n % 200000 == 0:
                print("... %d verified (%.0f/s)"
                      % (n, n / (time.time() - t0)), flush=True)
    print("chain VERIFIED: %d rows in %.1fs" % (n, time.time() - t0))
    print("head:", prev)
    print("jurisdictions:", len(jurisdictions))
    top = sorted(jurisdictions.items(), key=lambda kv: -kv[1])[:8]
    for j, c in top:
        print("  %-22s %d" % (j, c))


if __name__ == "__main__":
    main()
