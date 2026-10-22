#!/usr/bin/env python3
"""Websites in the side panel (idea 365), in a hidden probe.

Build first (`./build.sh`), then `python3 Tests/site_panel.py`. It runs in a
world of its own with split_view.py's harness: started hidden, everything
removed afterwards. Nothing is shown on any screen.

Off by default: nothing goes into the panel. On: a site goes there as a page
of the window's space, signed in where that space's tabs are (a cookie set in
the panel is the tabs' cookie), never a private tab's; the same site again
closes it; it keeps to the web; it goes into a tab of its own on request;
and after a switch to a space that starts afresh, it comes again signed in
as that space is.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import split_view as sv  # noqa: E402

sv.use("bld-s107-sitepanel")
GAP = 8
WIDTH = 380


def panel(action="state", **f): return sv.cmd({"do": "sidepanel", "action": action, **f})


def peval(js): return panel("eval", js=js).get("value")


def wait(cond, within=6):
    until = time.time() + within
    while time.time() < until:
        if cond(): return True
        time.sleep(0.2)
    return cond()


def window():
    p = sv.cmd({"do": "probe"})
    w = next(w for w in p["windows"] if w["kind"] == "AppKitWindow")
    return w["frame"][2], w["frame"][3]


def urls(): return [x["url"] for x in sv.sp("state")["tabs"]]


def main():
    t = sv.T()
    try:
        # Off, as it is unless turned on.
        sv.setup(sidebar=True); sv.launch()
        sv.page("a")
        panel("site", url=f"{sv.BASE}/panel")
        t.ok("off: a site doesn't go into the panel", not panel()["shown"], panel())
        sv.quit()

        sv.setup(sidebar=True, **{"panel.sites": True})
        sv.launch()
        a = sv.page("a")
        panel("site", url=f"{sv.BASE}/panel")
        st = panel()
        t.ok("on: the site is in the panel", st["shown"] and st["content"]["kind"] == "site", st)
        wait(lambda: panel()["title"] == "panel")
        st = panel()
        t.ok("its page loads there", st["title"] == "panel" and st["page"].endswith("/panel"), st)
        t.ok("signed in as the space's tabs are: the space's own store", st["content"]["store"] is True and st["content"]["sameStore"] is True, st["content"])
        t.ok("no window opens from it without a click", st["opensWindows"] is False, st)
        w, h = window()
        f = st["frame"]
        t.ok("beside the page on the far side, as wide as a panel", f and f[2] == WIDTH and f[0] + f[2] == w - GAP, (f, w))

        # The cookie is the tabs' cookie.
        peval("document.cookie = 'fromPanel=yes; path=/'; 1")
        b = sv.page("b")
        cookie = sv.ev(b, "document.cookie")
        t.ok("a cookie set in the panel is the tabs' cookie", "fromPanel=yes" in (cookie or ""), cookie)

        # It keeps to the web.
        peval("location.href = 'file:///etc/hosts'; 1"); time.sleep(1.0)
        t.ok("a file on this Mac doesn't load in it", panel()["page"].startswith(sv.BASE), panel()["page"])

        # The same site again closes it; the tab's menu puts one there.
        panel("site", url=f"{sv.BASE}/panel")
        t.ok("the same site again closes it", not panel()["shown"], panel())
        panel("site", tab=b)
        st = panel()
        t.ok("Open in Side Panel from a tab's menu", st["shown"] and st["content"]["url"].endswith("/b"), st)

        # Never a private tab's page.
        panel("close")
        sv.sp("private"); time.sleep(0.6)
        shy = sv.sp("state")["activeID"]
        panel("site", tab=shy)
        t.ok("a private tab's page never goes there", not panel()["shown"], panel())

        # Into a tab of its own.
        panel("site", url=f"{sv.BASE}/kept")
        wait(lambda: panel()["page"].endswith("/kept"))
        before = len(urls())
        panel("totab"); time.sleep(0.8)
        t.ok("into a tab: the panel closes and the page is a tab", not panel()["shown"] and len(urls()) == before + 1
             and any(u.endswith("/kept") for u in urls()), (panel(), urls()))
        sv.quit()

        # Another space, one that starts afresh: the site comes again,
        # signed in as that space is.
        sv.setup(sidebar=True, spaces=True, **{"panel.sites": True})
        sv.launch()
        sv.page("a")
        panel("site", url=f"{sv.BASE}/panel")
        wait(lambda: panel()["title"] == "panel")
        first = panel()["content"]
        peval("document.cookie = 'space=one; path=/'; 1")
        sv.cmd({"do": "space", "action": "new", "name": "Fresh", "fresh": True}); time.sleep(1.2)
        st = panel()
        t.ok("another space: still up, now in that space", st["shown"] and st["content"].get("space") != first["space"]
             and st["content"]["sameStore"] is True, (first, st["content"]))
        wait(lambda: panel()["title"] == "panel")
        t.ok("another space: signed in as it is (none of the first space's cookies)",
             "space=one" not in (peval("document.cookie") or ""), peval("document.cookie"))
        sv.quit()
    finally:
        t.done(); sv.finish()
    sys.exit(1 if t.failed else 0)


if __name__ == "__main__":
    main()
