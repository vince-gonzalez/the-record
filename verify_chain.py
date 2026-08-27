# ============================================================
# THE RECORD - chain verifier v0.1.0
# Recomputes every hash in ledger.jsonl from genesis. Any edited,
# reordered, or deleted row fails the walk at that row.
# Run: python verify_chain.py [ledger.jsonl]
# F-Keys | www.f-keys.com
# ============================================================

import hashlib
import io
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
GENESIS = "THE-RECORD-GENESIS-2026"


def canonical(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "ledger.jsonl"
    prev = hashlib.sha256(GENESIS.encode()).hexdigest()
    n = 0
    for line in io.open(path, encoding="utf-8"):
        row = json.loads(line)
        n += 1
        if row["seq"] != n:
            raise SystemExit("FAIL at %d: seq says %s" % (n, row["seq"]))
        if row["prev_hash"] != prev:
            raise SystemExit("FAIL at %d: prev_hash broken" % n)
        expect = hashlib.sha256(
            (prev + canonical({k: v for k, v in row.items()
                               if k not in ("prev_hash", "row_hash")})
             ).encode("utf-8")).hexdigest()
        if row["row_hash"] != expect:
            raise SystemExit("FAIL at %d: row_hash mismatch" % n)
        prev = row["row_hash"]
    print("chain VERIFIED: %d rows, head %s" % (n, prev))


if __name__ == "__main__":
    main()
