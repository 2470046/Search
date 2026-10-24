#!/usr/bin/env python3
"""An extension's declarativeNetRequest rule sending a site to its own page,
as Norma sends a blocked site to its block page — in a hidden probe.

Build first (`./build.sh`), then `python3 Tests/extension_rule_redirect.py`.
It runs a copy of build/Search.app under a bundle id of its own, in a world
of its own with split_view.py's harness, started hidden; the copy, its
WebKit folders and the world are removed afterwards.

Norma showed Search's "No connection." instead of its page. Its rule asks
only "declarativeNetRequest", and WebKit carries out a redirect only for
"declarativeNetRequestWithHostAccess", so the site went to the network,
where Norma's Mac filter dropped it. Then WebKit's redirect lands in the
tab's own view, which can't show an extension page, and escapes the
rule's "#site" into the path. What is checked:

- a site the rule names (one with no DNS at all, https and http) shows the
  extension's page, with its fragment, in the tab;
- a site the rule leaves out, and an excluded sub-domain, are not sent;
- a file the extension doesn't expose to websites is never shown.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import split_view as sv  # noqa: E402

sv.use("rule-redirect")
BUNDLE = "com.officecommun.search.ruleredirect"
work = Path(tempfile.mkdtemp(prefix="search-ruleredirect-"))
PORT = sv.srv.server_port

FILES = {
    "manifest.json": json.dumps({
        "manifest_version": 3, "name": "Blocker", "version": "1.0",
        "permissions": ["declarativeNetRequest", "storage"],
        "host_permissions": ["<all_urls>"],
        "background": {"service_worker": "sw.js"},
        "web_accessible_resources": [{"resources": ["blocked.html"], "matches": ["<all_urls>"]}],
    }),
    # Norma's rule, as it writes it: the page by full address, the site
    # in the fragment, a sub-domain left out.
    "sw.js": """
const rule = (id, domain, page) => ({
  id, priority: 1,
  action: { type: "redirect", redirect: { url: chrome.runtime.getURL(page) + "#" + encodeURIComponent(domain) } },
  condition: { requestDomains: [domain], excludedRequestDomains: ["music.rule-blocked.invalid"], resourceTypes: ["main_frame"] },
});
chrome.declarativeNetRequest.getDynamicRules().then((old) => chrome.declarativeNetRequest.updateDynamicRules({
  removeRuleIds: old.map((r) => r.id),
  addRules: [rule(1, "rule-blocked.invalid", "blocked.html"), rule(2, "localhost", "blocked.html"),
             rule(3, "rule-hidden.invalid", "hidden.html")],
})).then(() => chrome.storage.local.set({ ready: true }));
""",
    "blocked.html": '<!doctype html><title>Blocked</title><p>blocked</p><script src="blocked.js"></script>',
    "blocked.js": "document.title = 'Blocked: ' + decodeURIComponent(location.hash.slice(1));",
    "hidden.html": "<!doctype html><title>Hidden</title><p>hidden</p>",
}


def probe_copy():
    """build/Search.app under a bundle id of its own, signed ad hoc."""
    app = work / "Search.app"
    shutil.copytree(Path(sv.ROOT, "build", "Search.app"), app, symlinks=True)
    subprocess.run(["/usr/libexec/PlistBuddy", "-c", f"Set :CFBundleIdentifier {BUNDLE}", str(app / "Contents/Info.plist")], check=True)
    (app / "Contents/embedded.provisionprofile").unlink(missing_ok=True)
    subprocess.run(["codesign", "-f", "-s", "-", "--entitlements", str(Path(sv.ROOT, "Search.entitlements")), "--deep", str(app)],
                   check=True, capture_output=True)
    return str(app)


def visit(url, within=8):
    """Open a bench tab at url → the tab it settles on (the extension's page
    takes the tab's place in the row, under another id)."""
    before = {t["id"] for t in sv.cmd({"do": "tabs"})["tabs"]}
    sv.cmd({"do": "open", "url": url})
    end = time.time() + within
    tab = None
    while time.time() < end:
        tabs = [t for t in sv.cmd({"do": "tabs"})["tabs"] if t["id"] not in before]
        tab = tabs[-1] if tabs else None
        if tab and not tab["loading"] and (tab["title"] or time.time() > end - 4):
            break
        time.sleep(0.25)
    return tab


def main():
    t = sv.T()
    folder = work / "ext"
    folder.mkdir()
    for name, body in FILES.items():
        (folder / name).write_text(body)
    sv.APP = probe_copy()
    try:
        sv.setup()
        sv.launch()
        sv.cmd({"do": "ext-folder", "path": str(folder), "yes": True})
        ext = None
        for _ in range(60):
            ext = next((x for x in sv.cmd({"do": "extensions"})["extensions"] if x["name"] == "Blocker" and x["loaded"]), None)
            if ext:
                break
            time.sleep(0.25)
        t.ok("the extension loads", ext is not None)
        if not ext:
            return t
        page = sv.cmd({"do": "ext-page", "id": ext["id"], "path": "hidden.html"})["id"]
        rules = []
        for _ in range(40):
            try:
                sv.ev(page, "chrome.declarativeNetRequest.getDynamicRules().then((r) => window.__rules = r.length); 1")
            except RuntimeError:
                pass  # the page isn't there yet
            time.sleep(0.25)
            rules = sv.ev(page, "window.__rules || 0")
            if rules == 3:
                break
        t.ok("its rules are in", rules == 3, rules)
        base = ext["base"]

        tab = visit("https://rule-blocked.invalid/somewhere")
        t.ok("a site its rule names shows the extension's page, before any DNS",
             tab and tab["url"] == base + "blocked.html#rule-blocked.invalid", tab)
        t.ok("with the fragment the rule gave it, as Chrome reads it",
             tab and tab["title"] == "Blocked: rule-blocked.invalid", tab)

        tab = visit(f"http://localhost:{PORT}/site")
        t.ok("an http site too", tab and tab["url"] == base + "blocked.html#localhost", tab)

        tab = visit(f"http://127.0.0.1:{PORT}/site")
        t.ok("a site it doesn't name loads as itself", tab and tab["url"].startswith("http://127.0.0.1"), tab)

        tab = visit("https://music.rule-blocked.invalid/")
        t.ok("an excluded sub-domain isn't sent", tab and not tab["url"].startswith(base), tab)

        tab = visit("https://rule-hidden.invalid/")
        t.ok("a file it doesn't expose to websites is never shown",
             tab and "hidden.html" not in tab["view"] and tab["title"] != "Hidden", tab)
    finally:
        sv.finish()
        for kind in ("WebKit", "Caches", "HTTPStorages"):
            shutil.rmtree(Path.home() / "Library" / kind / BUNDLE, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
    return t


if __name__ == "__main__":
    t = main()
    t.done()
    sys.exit(1 if t.failed else 0)
