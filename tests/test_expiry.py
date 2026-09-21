import sys, os, json, tempfile, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scraper"))
import run_daily, common
from datetime import date, timedelta

tmp = tempfile.mkdtemp(); os.makedirs(tmp + "/data/latest")
run_daily.ROOT = tmp
os.chdir(tmp)
run_daily.CHAINS = ["fake", "stark"]
state = {"rows": []}
for name in ("fake", "stark"):
    m = types.ModuleType(name); nm = name
    m.scrape = (lambda limit=None, _n=nm: [dict(r, chain=_n) for r in state["rows"]])
    sys.modules[name] = m

def mk(i): return {"sku": f"s{i}", "url": f"http://x/{i}", "name": f"p{i}", "price": 10.0 + i, "in_stock": True}
def load(chain="fake"):
    return {json.loads(l)["sku"]: json.loads(l) for l in open(f"{tmp}/data/latest/{chain}.jsonl")}
def run(chain, today, *args):
    class D(date):
        @classmethod
        def today(cls): return date.fromisoformat(today)
    run_daily.date = D
    sys.argv = ["run_daily.py", "--only", chain, *args]
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): run_daily.main()
    return buf.getvalue()
def ok(cond, msg): print(("PASS " if cond else "FAIL ") + msg); assert cond

D0 = "2026-10-01"
state["rows"] = [mk(i) for i in range(100)]
run("fake", D0); ok(len(load()) == 100 and not any("missing_since" in r for r in load().values()), "day0: 100 rows, no stamps")

# 5 products delisted (5% < 15%): stamped, still present
state["rows"] = [mk(i) for i in range(95)]
out = run("fake", "2026-10-02")
L = load(); ok(len(L) == 100 and L["s99"].get("missing_since") == "2026-10-02" and "missing_since" not in L["s0"], "day1: 5 delisted rows kept, stamped missing_since; live rows unstamped")

# one comes back -> stamp cleared
state["rows"] = [mk(i) for i in range(95)] + [mk(99)]
run("fake", "2026-10-03")
L = load(); ok("missing_since" not in L["s99"] and L["s98"]["missing_since"] == "2026-10-02", "day2: returning product loses stamp; others keep ORIGINAL date")

# day 13 after first stamp: not yet dropped; day 14: dropped
run("fake", "2026-10-15"); ok(len(load()) == 100, "day 13 after stamp: still kept")
run("fake", "2026-10-16"); L = load()
ok(len(L) == 96 and "s96" not in L and "s99" in L, "day 14 after stamp: 4 expired rows dropped, returning + live rows kept")

# safety cap: 30% suddenly missing -> nothing stamped or dropped
state["rows"] = [mk(i) for i in range(60)]
out = run("fake", "2026-10-17"); L = load()
ok(len(L) == 96 and not any("missing_since" in r for r in L.values()) and "expiry skipped" in out, "30% missing: expiry skipped entirely (safety cap)")

# partial (limit) run never stamps
state["rows"] = [mk(i) for i in range(10)]
run("fake", "2026-10-18", "10"); L = load()
ok(not any("missing_since" in r for r in L.values()), "limit/smoke run: no stamps")

# resuming (leftover checkpoint file) never stamps
open(f"{tmp}/data/latest/.seen-fake.txt", "w").write("x\n")
state["rows"] = [mk(i) for i in range(90)]
run("fake", "2026-10-19"); L = load()
ok(not any("missing_since" in r for r in L.values()), "resuming pass: no stamps")
os.remove(f"{tmp}/data/latest/.seen-fake.txt")

# stark (rotating) never stamps even on a 'complete' slice
state["rows"] = [mk(i) for i in range(100)]; run("stark", D0)
state["rows"] = [mk(i) for i in range(95)]; run("stark", "2026-10-02")
ok(not any("missing_since" in r for r in load("stark").values()) and len(load("stark")) == 100, "stark: rotation slice never expires rows")
print("ALL PASSED")
