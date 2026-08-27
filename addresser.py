# ============================================================
# THE RECORD - addresser v0.1.0
# Deterministic Modulign (DAG-OR) addresser for legal documents.
# F-Keys | www.f-keys.com
# ============================================================
#
# Implements: Modulign Standard v3.0 (Zenodo DOI 10.5281/zenodo.19348704).
# Per spec section 26.3 every implementation must state the spec version
# and the SHA-256 of the spec document it implements; pipeline.py computes
# and embeds SPEC_SHA256 in every ledger row.
#
# WHAT A ROW'S ADDRESS SAYS, SEGMENT BY SEGMENT:
#   MGN               namespace
#   UNK-UNK           domain-subdomain. The Decision Protocol's domain step
#                     is run with document METADATA only, which is genuinely
#                     insufficient for subject-matter classification - the
#                     spec's stated condition for UNK. A later CDP pass over
#                     full text SUPERSEDES these rows (spec 1.3: history is
#                     never deleted, only superseded).
#   SR/NA/US[/ST]     locus chain, monotonic. State from the case's
#                     jurisdiction; federal jurisdiction stops at US.
#   NNNN              node, Base36^4, minted sequentially per locus.
#   :TXT              medium - "written records, transcripts, legal
#                     documents" (spec sect. Medium).
#   %AUT              automated observer, no competence annotation.
#   @TIME             classification timestamp, ISO 8601 UTC.
#   SUS[-ST]          jurisdiction axis (spec writes the section sign;
#                     ASCII 'S' stands in for U+00A7 in code comments only,
#                     the emitted address uses the real character).
#   ^PROV             MANDATORY per spec 15.1: any classification without a
#                     domain competence annotation is provisional. These
#                     rows are NOT evidence-grade and never claim to be.
#
# Segment order follows the spec's Full Syntax line (JUR before META);
# the modulign.org hero example orders them the other way - noted, spec wins.
# ============================================================

import re
import string

SPEC_VERSION = "Modulign Standard v3.0"
ADDRESSER_VERSION = "the-record-addresser/0.1.0"

B36 = string.digits + string.ascii_uppercase

# CAP jurisdiction name_long -> USPS code. Non-state federal systems map to
# None: the locus chain stops at US (monotonic chains may be shallow).
STATES = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT",
    "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI",
    "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO",
    "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND",
    "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA",
    "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD",
    "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
    "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY",
    "District of Columbia": "DC", "Puerto Rico": "PR",
}


def node_code(n):
    """Base36^4 node id for the n-th document minted in a locus (0-based)."""
    if not 0 <= n < 36 ** 4:
        raise ValueError("node counter out of Base36^4 range: %r" % n)
    out = ""
    for _ in range(4):
        out = B36[n % 36] + out
        n //= 36
    return out


def locus_and_jur(jurisdiction_name_long):
    """Locus chain + jurisdiction code from a CAP jurisdiction name.

    A recognised state yields (SR/NA/US/XX, US-XX). Anything else -
    'United States' (federal), tribal, territorial oddities - stays at the
    national level, which is monotonic-valid and never wrong, rather than
    guessed deeper.
    """
    st = STATES.get((jurisdiction_name_long or "").strip())
    if st:
        return "SR/NA/US/" + st, "US-" + st
    return "SR/NA/US", "US"


def address(jurisdiction_name_long, node_n, classified_at_iso):
    """The canonical MGN code for one document. Deterministic."""
    locus, jur = locus_and_jur(jurisdiction_name_long)
    return (
        "MGN·UNK·UNK·" + locus
        + "·" + node_code(node_n)
        + "·:TXT·%AUT·@" + classified_at_iso
        + "·§" + jur
        + "·^PROV"
    )


_ADDR_RE = re.compile(
    "^MGN·UNK·UNK·SR/NA/US(/[A-Z]{2})?"
    "·[0-9A-Z]{4}·:TXT·%AUT"
    "·@\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}Z"
    "·§US(-[A-Z]{2})?·\\^PROV$"
)


def valid(code):
    """Shape check for every emitted address; the pipeline gates on it."""
    return bool(_ADDR_RE.match(code))
