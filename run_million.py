# ============================================================
# THE RECORD - run_million v0.2.0
# The record run: CAP volume zips -> one continuous hash chain.
# F-Keys | www.f-keys.com
# ============================================================
#
# WORKFLOW STACK:
#   1. Reporter slugs from the static.case.law root listing; per-reporter
#      volume zip URLs from each reporter's listing page.
#   2. Download pool (THREADS workers) fetches volume zips to run-data.
#   3. ONE chain thread consumes finished volumes in completion order:
#      every json/*.json entry (sorted) is hashed AS STORED IN THE ZIP
#      (verified byte-identical to the per-case URL), addressed, chained.
#   4. Continues the existing chain: seq/prev_hash/node counters resume
#      from the tail of the committed proof slice.
#   5. Checkpoint after every volume (volume manifest carries the zip's
#      own sha256). Ledger shards of 100,000 rows. Every ANCHOR_EVERY
#      rows: anchors.jsonl appended, committed, pushed - the public repo
#      timestamps the chain head while the run is still going.
#   6. Zip deleted after processing; disk stays bounded.
#
# Run:   python run_million.py --target 1000000
# Resume is automatic: state lives in run-data/checkpoint.json.
# Stdlib only.
# ============================================================

import argparse
import datetime
import hashlib
import io
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import zipfile

import addresser

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://static.case.law"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("RECORD_DATA", r"C:\Users\Admin\the-record-data")
UA = {"User-Agent": "the-record-pipeline/0.2.0 (hello@f-keys.com)"}
THREADS = 12
SHARD_ROWS = 100000
ANCHOR_EVERY = 100000
GENESIS = "THE-RECORD-GENESIS-2026"


def fetch(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(3 * (i + 1))


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def canonical(row):
    return json.dumps(row, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def spec_sha256():
    h = hashlib.sha256()
    with open(os.path.join(HERE, "Modulign-Standard-v3.pdf"), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def reporters():
    html = fetch(BASE + "/").decode("utf-8", "replace")
    return re.findall(r"href='https://static\.case\.law/([a-z0-9-]+)/'", html)


def volume_zips(rep):
    html = fetch("%s/%s/" % (BASE, rep)).decode("utf-8", "replace")
    vols = re.findall(
        r"href='https://static\.case\.law/%s/(\d+)\.zip'" % re.escape(rep),
        html)
    return sorted(set(int(v) for v in vols))


def repair_shards(good_seq):
    """Drop shard rows past the checkpoint. A crash between a shard flush
    and a checkpoint save leaves orphan rows; resuming would fork the
    chain into duplicate seq numbers with different hashes."""
    import glob
    for path in sorted(glob.glob(os.path.join(DATA, "ledger-*.jsonl"))):
        lines = io.open(path, encoding="utf-8").readlines()
        keep = [l for l in lines
                if json.loads(l)["seq"] <= good_seq]
        if len(keep) != len(lines):
            io.open(path, "w", encoding="utf-8").writelines(keep)
            print("repair: %s truncated %d orphan rows"
                  % (os.path.basename(path), len(lines) - len(keep)),
                  flush=True)


def tail_state():
    """Resume point: checkpoint if present, else derived from the proof
    slice's committed ledger."""
    cp = os.path.join(DATA, "checkpoint.json")
    if os.path.isfile(cp):
        state = json.load(io.open(cp, encoding="utf-8"))
        repair_shards(state["seq"])
        return state
    seq, prev, counters = 0, hashlib.sha256(GENESIS.encode()).hexdigest(), {}
    slice_path = os.path.join(HERE, "ledger.jsonl")
    if os.path.isfile(slice_path):
        for line in io.open(slice_path, encoding="utf-8"):
            row = json.loads(line)
            seq = row["seq"]
            prev = row["row_hash"]
            locus = row["mgn"].split("·:TXT")[0]
            locus = locus.split("·")[3]
            counters[locus] = counters.get(locus, 0) + 1
    return {"seq": seq, "prev_hash": prev, "node_counters": counters,
            "done_volumes": [], "run_started_at": None}


def save_state(state):
    # os.replace on Windows fails with WinError 5 while a scanner
    # (Defender, indexer) briefly holds the target. Retry; the atomic
    # swap is worth waiting a few seconds for. This exact failure killed
    # a run at seq 113563.
    tmp = os.path.join(DATA, "checkpoint.tmp")
    dst = os.path.join(DATA, "checkpoint.json")
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(state))
    for i in range(8):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            time.sleep(0.5 * (i + 1))
    os.replace(tmp, dst)


def git_anchor(seq, head):
    """Append the head to anchors.jsonl, commit, push. Failure never
    stops the run - the next anchor carries the chain forward."""
    try:
        entry = {"kind": "chain-head", "through_seq": seq,
                 "chain_head": head, "anchored_at": now_iso(),
                 "note": "automated in-run anchor"}
        with io.open(os.path.join(HERE, "anchors.jsonl"), "a",
                     encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        subprocess.run(["git", "add", "anchors.jsonl"], cwd=HERE,
                       capture_output=True, timeout=60)
        subprocess.run(["git", "commit", "-m",
                        "anchor: chain head at seq %d" % seq],
                       cwd=HERE, capture_output=True, timeout=60)
        subprocess.run(["git", "push"], cwd=HERE, capture_output=True,
                       timeout=120)
        print("ANCHORED seq %d head %s" % (seq, head[:16]), flush=True)
    except Exception as e:  # noqa: BLE001
        print("anchor failed (run continues): %s" % e, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1000000)
    ap.add_argument("--max-reporters", type=int, default=0)
    # Anchoring is opt-in so a test run can never push a throwaway-branch
    # head to the public anchor repo (a smoke test did exactly that once).
    ap.add_argument("--anchor", action="store_true")
    args = ap.parse_args()

    os.makedirs(DATA, exist_ok=True)
    spec_hash = spec_sha256()
    state = tail_state()
    if not state.get("run_started_at"):
        state["run_started_at"] = now_iso()
        save_state(state)
    done = set(tuple(v) for v in state["done_volumes"])
    print("RUN START %s | resuming at seq %d, %d volumes done"
          % (state["run_started_at"], state["seq"], len(done)), flush=True)

    # Work list: every volume zip of every reporter, in listing order.
    reps = reporters()
    if args.max_reporters:
        reps = reps[:args.max_reporters]
    work = []
    for rep in reps:
        try:
            for v in volume_zips(rep):
                if (rep, v) not in done:
                    work.append((rep, v))
        except Exception as e:  # noqa: BLE001
            print("reporter %s listing failed: %s" % (rep, e), flush=True)
    print("work list: %d volumes across %d reporters"
          % (len(work), len(reps)), flush=True)

    q_in = queue.Queue()
    q_out = queue.Queue(maxsize=THREADS * 2)
    for w in work:
        q_in.put(w)

    def downloader():
        while True:
            try:
                rep, vol = q_in.get_nowait()
            except queue.Empty:
                return
            path = os.path.join(DATA, "%s-%d.zip" % (rep, vol))
            try:
                blob = fetch("%s/%s/%d.zip" % (BASE, rep, vol))
                io.open(path, "wb").write(blob)
                q_out.put((rep, vol, path,
                           hashlib.sha256(blob).hexdigest()))
            except Exception as e:  # noqa: BLE001
                print("download failed %s/%d: %s" % (rep, vol, e),
                      flush=True)
            finally:
                q_in.task_done()

    threads = [threading.Thread(target=downloader, daemon=True)
               for _ in range(THREADS)]
    for t in threads:
        t.start()

    seq = state["seq"]
    seq0 = seq
    prev = state["prev_hash"]
    counters = state["node_counters"]
    shard = None
    shard_id = -1
    t0 = time.time()
    last_anchor = (seq // ANCHOR_EVERY) * ANCHOR_EVERY

    def shard_for(n):
        nonlocal shard, shard_id
        want = n // SHARD_ROWS
        if want != shard_id:
            if shard:
                shard.close()
            shard_id = want
            shard = io.open(os.path.join(
                DATA, "ledger-%03d.jsonl" % want), "a", encoding="utf-8")
        return shard

    alive = lambda: any(t.is_alive() for t in threads)  # noqa: E731
    while seq < args.target and (alive() or not q_out.empty()):
        try:
            rep, vol, path, zip_sha = q_out.get(timeout=10)
        except queue.Empty:
            continue
        added = 0
        try:
            with zipfile.ZipFile(path) as z:
                names = sorted(n for n in z.namelist()
                               if re.match(r"json/\d{4}-\d{2}\.json$", n))
                for name in names:
                    if seq >= args.target:
                        break
                    raw = z.read(name)
                    try:
                        doc = json.loads(raw.decode("utf-8"))
                    except Exception:
                        continue
                    jur = (doc.get("jurisdiction") or {}).get(
                        "name_long") or ""
                    locus, _ = addresser.locus_and_jur(jur)
                    n = counters.get(locus, 0)
                    counters[locus] = n + 1
                    ts = now_iso()
                    mgn = addresser.address(jur, n, ts)
                    if not addresser.valid(mgn):
                        raise SystemExit("invalid address: " + mgn)
                    cites = [c.get("cite") for c in
                             (doc.get("citations") or [])
                             if c.get("type") == "official"]
                    row = {
                        "seq": seq + 1,
                        "gsi_id": str(uuid.uuid4()),
                        "mgn": mgn,
                        "doc_source": "cap-static",
                        "doc_id": str(doc.get("id")),
                        "doc_url": "%s/%s/%d/cases/%s" % (
                            BASE, rep, vol, name.split("/")[1]),
                        "doc_sha256": hashlib.sha256(raw).hexdigest(),
                        "doc_title": doc.get("name_abbreviation")
                                     or doc.get("name"),
                        "doc_cite": cites[0] if cites else None,
                        "doc_date": doc.get("decision_date"),
                        "court": (doc.get("court") or {}).get("name"),
                        "jurisdiction": jur,
                        "classified_at": ts,
                        "spec_version": addresser.SPEC_VERSION,
                        "spec_sha256": spec_hash,
                        "classifier": "the-record-addresser/0.2.0",
                        "prev_hash": prev,
                    }
                    row["row_hash"] = hashlib.sha256(
                        (prev + canonical({k: v for k, v in row.items()
                                           if k != "prev_hash"})
                         ).encode("utf-8")).hexdigest()
                    prev = row["row_hash"]
                    seq += 1
                    added += 1
                    shard_for(seq - 1).write(
                        json.dumps(row, ensure_ascii=False) + "\n")
        except zipfile.BadZipFile:
            print("bad zip %s/%d, skipped" % (rep, vol), flush=True)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        state.update({"seq": seq, "prev_hash": prev,
                      "node_counters": counters})
        state["done_volumes"].append([rep, vol, zip_sha, added])
        if shard:
            shard.flush()
        save_state(state)

        if seq // 10000 != (seq - added) // 10000:
            rate = (seq - seq0) / max(time.time() - t0, 1)
            print("PROGRESS %d rows  (%.0f/s this session)" % (seq, rate),
                  flush=True)
        if args.anchor and seq - last_anchor >= ANCHOR_EVERY:
            last_anchor = (seq // ANCHOR_EVERY) * ANCHOR_EVERY
            git_anchor(seq, prev)

    if shard:
        shard.close()
    ended = now_iso()
    print("RUN COMPLETE: seq %d | head %s | started %s | ended %s"
          % (seq, prev, state["run_started_at"], ended), flush=True)
    if args.anchor:
        git_anchor(seq, prev)


if __name__ == "__main__":
    main()
