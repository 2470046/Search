#!/usr/bin/env python3
"""Closed tabs give their memory back, in a hidden probe.

Build first (`./build.sh`), then `python3 Tests/memory_close.py` from a
worktree; `--sites` adds a round on real sites (network needed),
`--last-window` weighs the app after its only window closes (its tabs are
kept, pages and all, by design: printed, not checked), `--keep` leaves the
world for a look afterwards. It uses the split suite's harness:
started hidden with SEARCH_MEASURE (pages throttled as they are for
people), in a world of its own, everything removed afterwards. No window
is ever made or brought forward.

Each heavy page holds about 130 MB (typed arrays and a drawn canvas), so a
page that stays alive after its tab closed shows in the numbers as well as
in the bench's `alive` count: tabs and page views still in memory, against
what the rows hold.

Checked here: closing tabs one by one leaves no Tab and no page view
behind; their web processes end; the app's own footprint comes back near
where it was; three rounds of open-and-close don't climb; a tab put to
sleep lets its page and process go. Printed, not checked: the footprint
of the app and of each helper process at every step.
"""
import os
import re
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import split_view as sv  # noqa: E402

sv.use("memory-close")

MB = 1024 * 1024


class Heavy(BaseHTTPRequestHandler):
    def do_GET(self):
        n = self.path.strip("/") or "0"
        body = f"""<!doctype html><title>heavy {n}</title>
<canvas id=c width=2000 height=2000></canvas>
<script>
// About 100 MB the page keeps, touched so it is really there.
window.keep = [];
for (let i = 0; i < 25; i++) {{ const a = new Float64Array(512 * 1024); for (let j = 0; j < a.length; j += 512) a[j] = Math.random(); a.fill(i + 0.5); keep.push(a); }}
const g = document.getElementById('c').getContext('2d');
for (let i = 0; i < 400; i++) {{ g.fillStyle = `hsl(${{i}},70%,50%)`; g.fillRect((i * 37) % 1900, (i * 53) % 1900, 100, 100); }}
document.title = 'heavy {n} ready';
</script>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = ThreadingHTTPServer(("127.0.0.1", 0), Heavy)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"

SITES = [
    "https://x.com/explore", "https://github.com/trending", "https://www.youtube.com/",
    "https://medium.com/", "https://www.google.com/search?q=webkit", "https://github.com/WebKit/WebKit",
    "https://www.youtube.com/feed/trending", "https://medium.com/tag/programming",
    "https://www.google.com/search?q=swift", "https://en.wikipedia.org/wiki/WebKit",
]


def launch():
    """sv.launch, with SEARCH_MEASURE beside SEARCH_PROBE."""
    if os.path.exists(sv.SOCK):
        os.remove(sv.SOCK)
    before = sv.running()
    subprocess.run(["open", "-n", "-g", "-j", "--env", f"SEARCH_PROBE={sv.W}", "--env", "SEARCH_MEASURE=1", sv.APP])
    for _ in range(150):
        if os.path.exists(sv.SOCK):
            break
        time.sleep(0.1)
    time.sleep(3)
    sv.started.update((sv.running() - before) & sv.holding())


def footprint(pid):
    """phys_footprint in bytes, or None once the process is gone."""
    out = subprocess.run(["footprint", "-f", "bytes", "--noCategories", "-p", str(pid)],
                         capture_output=True, text=True).stdout
    m = re.search(r"phys_footprint:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def alive():
    return sv.cmd({"do": "alive"})


seen = set()
helpers = {}


def weigh(label):
    """The app and every helper seen so far, in MB, printed on one line."""
    a = alive()
    seen.update(a["processes"])
    for k in ("gpu", "network"):
        if a.get(k):
            helpers[k] = a[k]
    app = footprint(sv.pids()[0])
    content = {p: footprint(p) for p in sorted(seen)}
    living = {p: f for p, f in content.items() if f is not None}
    extra = {k: footprint(p) for k, p in helpers.items()}
    total = (app or 0) + sum(living.values()) + sum(v or 0 for v in extra.values())
    print(f"  [{label}] app {app / MB:.0f} MB · {len(living)} web processes {sum(living.values()) / MB:.0f} MB"
          + "".join(f" · {k} {(v or 0) / MB:.0f} MB" for k, v in extra.items())
          + f" · total {total / MB:.0f} MB · tabs {a['tabs']} (rows {a['inRows']}) · pages {a['pages']} (built {a['built']})")
    return {"app": app or 0, "content": living, "alive": a, "total": total}


def settle(seconds):
    time.sleep(seconds)


def open_heavy(n, tag):
    ids = []
    for i in range(n):
        ids.append(sv.sp("open", url=f"{BASE}/{tag}-{i}")["resultID"])
        time.sleep(1.2)
    time.sleep(3)
    return ids


def close(ids):
    for id in ids:
        sv.sp("close", id=id)
        time.sleep(0.3)


def main():
    t = sv.T()
    sites = "--sites" in sys.argv
    try:
        sv.setup()
        launch()
        settle(4)
        base = weigh("start")

        rounds = []
        for r in range(3):
            ids = open_heavy(10, f"r{r}")
            full = weigh(f"round {r + 1}: 10 heavy tabs")
            pids = set(full["alive"]["processes"])
            close(ids)
            settle(2)
            weigh(f"round {r + 1}: closed, 2 s")
            settle(10)
            after = weigh(f"round {r + 1}: closed, 12 s")
            a = after["alive"]
            # One Tab object may linger a moment after the last close (its
            # page is gone either way, which is what costs): not more.
            t.ok(f"round {r + 1}: no closed tab left in memory", a["tabs"] <= a["inRows"] + 1, a)
            t.ok(f"round {r + 1}: no closed page left in memory", a["pages"] == a["built"], a)
            gone = [p for p in pids if footprint(p) is None]
            t.ok(f"round {r + 1}: the closed pages' processes ended ({len(gone)} of {len(pids)})",
                 len(gone) >= len(pids) - 1, sorted(pids - set(gone)))
            t.ok(f"round {r + 1}: the web processes give back what they held",
                 sum(after["content"].values()) < sum(full["content"].values()) / 3,
                 (sum(after["content"].values()) // MB, sum(full["content"].values()) // MB))
            rounds.append(after["app"])
        grew = (rounds[-1] - rounds[0]) / MB
        print(f"  app after each round: {[round(r / MB) for r in rounds]} MB (start {base['app'] / MB:.0f} MB)")
        t.ok("the app doesn't climb round after round (< 40 MB)", grew < 40, grew)

        # Asleep: the page and its process go, the tab stays.
        ids = open_heavy(4, "sleep")
        full = weigh("4 heavy tabs to sleep")
        pids = set(full["alive"]["processes"])
        for id in ids[:-1]:
            said = sv.cmd({"do": "sleep", "id": id})
            if said.get("said") != "asleep":
                print("   sleep:", id, said)
        settle(8)
        after = weigh("3 of them asleep, 8 s")
        a = after["alive"]
        t.ok("asleep: the tabs stay, their pages go", a["tabs"] == a["inRows"] and a["pages"] == a["built"], a)
        t.ok("asleep: three pages fewer", full["alive"]["pages"] - a["pages"] >= 3, (full["alive"], a))
        close(ids)
        settle(4)
        weigh("closed them")

        if sites:
            ids = []
            for url in SITES:
                ids.append(sv.sp("open", url=url)["resultID"])
                time.sleep(4)
            settle(10)
            full = weigh("10 real sites")
            close(ids)
            settle(15)
            after = weigh("real sites closed, 15 s")
            a = after["alive"]
            t.ok("sites: nothing closed left in memory", a["tabs"] <= a["inRows"] + 1 and a["pages"] == a["built"], a)
        if "--last-window" in sys.argv:
            # The last window closed, the app still running: printed, as
            # Windows.closing keeps that window's tabs, pages and all, for
            # when it is opened again.
            open_heavy(5, "last")
            weigh("5 heavy tabs, before the last window closes")
            sv.cmd({"do": "windows", "action": "close", "n": 1})
            settle(10)
            weigh("last window closed, 10 s")
    finally:
        t.done()
        if "--keep" not in sys.argv:
            sv.finish()
    sys.exit(1 if t.failed else 0)


if __name__ == "__main__":
    main()
