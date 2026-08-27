# ============================================================
# THE RECORD - pipeline v0.1.0
# CAP caselaw in -> hash-chained Modulign ledger out.
# F-Keys | www.f-keys.com
# ============================================================
#
# WORKFLOW STACK:
#   1. Walk static.case.law volumes of one reporter, newest request first
#      is not needed - volumes are fetched in order until --count reached.
#   2. For each case: fetch its per-case JSON, sha256 the exact bytes
#      retrieved (that hash IS the provenance claim), mint GSI-ID (UUIDv4),
#      mint the Modulign address via addresser.py.
#   3. Chain: row_hash = sha256(prev_hash + canonical row JSON). Row 1
#      chains from the GENESIS string. Any later edit to any row breaks
#      every hash after it - modification is detectable (spec 26.1/26.2).
#   4. Emit ledger.jsonl + insert-NNN.sql batches for Cloudflare D1.
#
# Stdlib only. Run:  python pipeline.py --count 1000 --reporter us
# ============================================================

import argparse
import datetime
import hashlib
import io
import json
import os
import sys
import time
import urllib.request
import uuid

import addresser

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://static.case.law"
HERE = os.path.dirname(os.path.abspath(__file__))
GENESIS = "THE-RECORD-GENESIS-2026"
UA = {"User-Agent": "the-record-pipeline/0.1.0 (hello@f-keys.com)"}


def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retry then surface
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))
    return None


def spec_sha256():
    """SHA-256 of the spec PDF this addresser implements (spec 26.3)."""
    p = os.path.join(HERE, "Modulign-Standard-v3.pdf")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(row):
    """The exact bytes that get hashed: sorted keys, no whitespace drift."""
    return json.dumps(row, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--reporter", default="us")
    ap.add_argument("--start-volume", type=int, default=1)
    args = ap.parse_args()

    spec_hash = spec_sha256()
    out_ledger = io.open(os.path.join(HERE, "ledger.jsonl"), "w",
                         encoding="utf-8")
    node_counters = {}   # locus -> next node int
    prev_hash = hashlib.sha256(GENESIS.encode()).hexdigest()
    seq = 0
    vol = args.start_volume
    t0 = time.time()

    while seq < args.count:
        meta_url = "%s/%s/%d/CasesMetadata.json" % (BASE, args.reporter, vol)
        try:
            cases = json.loads(fetch(meta_url).decode("utf-8"))
        except Exception:
            print("volume %d: no metadata, stopping walk" % vol)
            break
        by_id = {c.get("id"): c for c in cases}

        # The volume's cases/ directory listing is the authority on file
        # names (zero-padded page + ordinal); each file carries its own id,
        # which is matched back to the metadata record.
        import re as _re
        listing = fetch("%s/%s/%d/cases/" % (BASE, args.reporter, vol)
                        ).decode("utf-8", "replace")
        files = _re.findall(r"href='([^']*cases/[0-9]{4}-[0-9]{2}\.json)'",
                            listing)

        for case_url in files:
            if seq >= args.count:
                break
            doc_bytes = fetch(case_url)
            doc = json.loads(doc_bytes.decode("utf-8"))
            case_id = doc.get("id")
            c = by_id.get(case_id, doc)
            doc_url = case_url

            jur_long = (c.get("jurisdiction") or {}).get("name_long") or ""
            locus, _ = addresser.locus_and_jur(jur_long)
            n = node_counters.get(locus, 0)
            node_counters[locus] = n + 1

            classified_at = datetime.datetime.now(
                datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            mgn = addresser.address(jur_long, n, classified_at)
            if not addresser.valid(mgn):
                raise SystemExit("invalid address emitted: " + mgn)

            cites = [x.get("cite") for x in (c.get("citations") or [])
                     if x.get("type") == "official"]
            row = {
                "seq": seq + 1,
                "gsi_id": str(uuid.uuid4()),
                "mgn": mgn,
                "doc_source": "cap-static",
                "doc_id": str(case_id),
                "doc_url": doc_url,
                "doc_sha256": hashlib.sha256(doc_bytes).hexdigest(),
                "doc_title": c.get("name_abbreviation") or c.get("name"),
                "doc_cite": cites[0] if cites else None,
                "doc_date": c.get("decision_date"),
                "court": (c.get("court") or {}).get("name"),
                "jurisdiction": jur_long,
                "classified_at": classified_at,
                "spec_version": addresser.SPEC_VERSION,
                "spec_sha256": spec_hash,
                "classifier": addresser.ADDRESSER_VERSION,
                "prev_hash": prev_hash,
            }
            row["row_hash"] = hashlib.sha256(
                (prev_hash + canonical(
                    {k: v for k, v in row.items() if k != "prev_hash"}
                )).encode("utf-8")).hexdigest()
            prev_hash = row["row_hash"]

            out_ledger.write(json.dumps(row, ensure_ascii=False) + "\n")
            seq += 1
            if seq % 100 == 0:
                print("%d addressed  (%.1f/s)" % (seq, seq / (time.time() - t0)))
        vol += 1

    out_ledger.close()
    print("DONE: %d rows, %.1fs, chain head %s" % (
        seq, time.time() - t0, prev_hash[:16]))

    # D1 insert batches: 50 rows per statement keeps each SQL well under
    # D1's statement size limit.
    rows = [json.loads(l) for l in
            io.open(os.path.join(HERE, "ledger.jsonl"), encoding="utf-8")]
    cols = ["seq", "gsi_id", "mgn", "doc_source", "doc_id", "doc_url",
            "doc_sha256", "doc_title", "doc_cite", "doc_date", "court",
            "jurisdiction", "classified_at", "spec_version", "spec_sha256",
            "classifier", "prev_hash", "row_hash"]

    def sqlval(v):
        if v is None:
            return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    for b in range(0, len(rows), 50):
        chunk = rows[b:b + 50]
        vals = ",\n".join(
            "(" + ",".join(sqlval(r.get(c)) for c in cols) + ")"
            for r in chunk)
        sql = ("INSERT INTO ledger (" + ",".join(cols) + ") VALUES\n"
               + vals + ";")
        io.open(os.path.join(HERE, "insert-%03d.sql" % (b // 50)),
                "w", encoding="utf-8").write(sql)
    print("wrote %d insert batches" % ((len(rows) + 49) // 50))


if __name__ == "__main__":
    main()
