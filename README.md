# THE RECORD

A hash-chained, append-only ledger of Modulign (DAG-OR) addresses for legal
documents, on Cloudflare D1. Modulign's legal channel: public-record corpora
in, auditable classification ledger out. No scraping — every source is an
official bulk-published archive.

Implements **Modulign Standard v3.0** (DOI 10.5281/zenodo.19348704). Per
spec §26.3, every ledger row embeds the SHA-256 of the spec document this
implementation follows (`Modulign-Standard-v3.pdf`, vendored here).

## What a row is

One legal document → one permanent GSI-ID (UUIDv4) → one canonical address:

```
MGN·UNK·UNK·SR/NA/US/PA·0007·:TXT·%AUT·@2026-08-27T06:40:00Z·§US-PA·^PROV
```

- `UNK·UNK` — the domain step runs on metadata only, which is genuinely
  insufficient for subject classification: the spec's stated condition for
  UNK. A later full-text CDP pass supersedes these rows (spec §1.3 — history
  is never deleted, only superseded). Categories fill in later by design.
- `§US-XX` from the case's jurisdiction; federal stays `§US`.
- `^PROV` — **mandatory honesty**: spec §15.1 makes any classification
  without a domain-competence annotation provisional. Nothing in this ledger
  claims evidence grade. The append-only chain (spec §26.2) is the
  infrastructure that lets reviewed rows be upgraded later.

## The chain

`row_hash = sha256(prev_hash + canonical_row_json)`, from a fixed genesis
string. Editing, deleting, or reordering any row breaks every hash after it.
`verify_chain.py` re-walks the whole chain from genesis. Chain heads get
anchored outside the database (the `anchors` table records where).

## Files

| File | Role |
|---|---|
| `addresser.py` | Metadata → canonical address. Pure, deterministic, tested. |
| `pipeline.py` | CAP static → addressed, chained `ledger.jsonl` + D1 insert batches. |
| `verify_chain.py` | Recomputes every hash from genesis. |
| `test_addresser.py` | 12 checks. Run before any pipeline run. |
| `schema.sql` | The D1 ledger + anchors tables. |
| `Modulign-Standard-v3.pdf` | The spec this implements (hash embedded per row). |

## Source corpus

Harvard **Caselaw Access Project** static archive (`static.case.law`) —
bulk-published, openly licensed public court records. Each row records the
exact artifact URL and the SHA-256 of the exact bytes retrieved.

## The million run — 2026-08-27

Sequence 1,001 through 1,000,000 — 999,000 legal documents — addressed in
one continuous chained run: **started 07:32:24.797 UTC, row 1,000,000 at
07:40:39.361 UTC — 8 minutes 14.6 seconds**, including one mid-run crash
(a Windows file lock at seq 113,563) and its recovery, both visible in the
row timestamps. Chain heads were committed to this repository every
100,000 rows *while the run was going*; GitHub's commit timestamps witness
the pace independently.

Full-chain audit: `verify_full.py` recomputes every hash from genesis —
**1,000,000 rows VERIFIED, head
`11644eb269e3940df5b8b2aa722bcf568ea19672c31100fba5df026635a791f1`** —
19 jurisdictions, every row `^PROV`, every row carrying its source URL,
the SHA-256 of its exact source bytes, and the spec hash.

## Infrastructure

Cloudflare D1 database `the-record` (id `1b9e0cf6-403d-4e34-aa52-6c601f3f1e83`).
Read API worker: not yet built (next step), which will serve
`registry.modulign.org`-style queries from the ledger.

---

www.f-keys.com | © 2026 F-Keys LLC
