# ============================================================
# THE RECORD - addresser tests v0.1.0
# Run: python test_addresser.py   (prints PASS/FAIL per check, exits 1 on any FAIL)
# F-Keys | www.f-keys.com
# ============================================================

import sys

import addresser

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
FAILS = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        FAILS.append(name)


T = "2026-08-27T12:00:00Z"

a = addresser.address("Pennsylvania", 0, T)
check("state address exact",
      a == "MGN·UNK·UNK·SR/NA/US/PA·0000·:TXT·%AUT·@" + T + "·§US-PA·^PROV")
check("state address validates", addresser.valid(a))

f = addresser.address("United States", 7, T)
check("federal locus stops at US", "·SR/NA/US·" in f and "§US·" in f)
check("federal address validates", addresser.valid(f))

check("unknown jurisdiction falls back to US",
      addresser.valid(addresser.address("Navajo Nation", 0, T)))

check("node 0", addresser.node_code(0) == "0000")
check("node 35", addresser.node_code(35) == "000Z")
check("node 36", addresser.node_code(36) == "0010")
check("node max", addresser.node_code(36 ** 4 - 1) == "ZZZZ")
try:
    addresser.node_code(36 ** 4)
    check("node overflow raises", False)
except ValueError:
    check("node overflow raises", True)

check("garbage rejected", not addresser.valid("MGN·URB·STR·SR/NA/US·0000"))
check("EVID never emitted by shape",
      not addresser.valid(a.replace("^PROV", "^EVID")))

print("----")
if FAILS:
    print("%d FAILING" % len(FAILS))
    sys.exit(1)
print("all checks pass")
