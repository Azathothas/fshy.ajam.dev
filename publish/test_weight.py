#!/usr/bin/env python3
"""The weight budget of the wiki: the limits that a built site must stay under (docs/ui-plan.md, R14).

A reader on a slow phone pays for each byte of the shared files and of the page shell on every page, and for the
rows of a long list. These limits hold today with a margin; a change that passes one fails here and names the file
and the limit. Sizes are gzip -9, as a server compresses them, except the page shell, which is raw.

usage:
  python publish/build.py --site site/dist && python publish/test_weight.py --site site/dist

Exit codes: 0 every file is under its limit, 1 a file is over, 2 no built site.
"""
import argparse
import gzip
import os
import re
import sys

ASSET_LIMIT = 25 * 1024 * 1024  # the largest static asset of Workers (publish/build.py ASSET_MAX_BYTES)
# (what, limit in bytes). The shared files and the page shell have the limits of the plan. The page limits keep about
# a third of room above the heaviest page of 2026-10-29 (in parentheses), so a publish that adds records passes, and
# a change that doubles a kind of page fails. A rejected page holds every dead end of its topic and is not the
# reading path, so its limit is the largest. When a publish fails here, a change of pages.py comes first, or a
# reviewed change of a limit.
LIMITS = {
    "shared": ("style.css plus app.js, gzip", 12_000),  # (11,474)
    "shell": ("the page shell (header, topic bar, footer), raw", 2_200),  # (1,968)
    "topic": ("a topic page or its paid page, gzip", 80_000),  # (58,175: t/compute/)
    "rejected": ("a rejected page, gzip", 160_000),  # (121,007: t/storage/rejected/)
    "need": ("a best-per-need page, gzip", 40_000),  # (29,209: need/debrid-cheapest/)
    "provider": ("a provider page or a record page, gzip", 30_000),  # (20,528: p/hostbrr/)
    "list": ("the graveyard or the changes page, gzip", 40_000),  # (26,758: graveyard/)
    "asset": ("any file, raw: 70 percent of the 25 MiB asset limit", int(0.7 * ASSET_LIMIT)),
}


def gz(path):
    with open(path, "rb") as f:
        return len(gzip.compress(f.read(), 9))


def kind(rel):
    if re.fullmatch(r"t/[^/]+/(?:paid/)?index\.html", rel):
        return "topic"
    if re.fullmatch(r"t/[^/]+/rejected/index\.html", rel):
        return "rejected"
    if re.fullmatch(r"need/[^/]+/index\.html", rel):
        return "need"
    if re.fullmatch(r"p/[^/]+/(?:[^/]+/)?index\.html", rel):
        return "provider"
    if rel in ("graveyard/index.html", "changes/index.html"):
        return "list"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site", "dist"))
    a = ap.parse_args()
    dist = os.path.abspath(a.site)
    if not os.path.exists(os.path.join(dist, "404.html")):
        print("no built site at %s: run python publish/build.py --site site/dist first" % dist)
        return 2
    over, worst = [], {}

    def measure(what, rel, n):
        if n > worst.get(what, (0, ""))[0]:
            worst[what] = (n, rel)
        if n > LIMITS[what][1]:
            over.append("%s is %s bytes; the limit of %s is %s" % (rel, "{:,}".format(n), LIMITS[what][0], "{:,}".format(LIMITS[what][1])))
    measure("shared", "assets/style.css + assets/app.js",
            gz(os.path.join(dist, "assets", "style.css")) + gz(os.path.join(dist, "assets", "app.js")))
    page = open(os.path.join(dist, "404.html"), encoding="utf-8").read()
    main_part = re.search(r'<main id="main">(.*)</main>', page, re.S)
    measure("shell", "404.html without its main", len(page.encode("utf-8")) - len(main_part.group(1).encode("utf-8")))
    for root, _, files in os.walk(dist):
        for fn in files:
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, dist).replace("\\", "/")
            measure("asset", rel, os.path.getsize(p))
            k = kind(rel)
            if k:
                measure(k, rel, gz(p))
    for what, (n, rel) in sorted(worst.items()):
        print("%-8s %10s of %10s  %s" % (what, "{:,}".format(n), "{:,}".format(LIMITS[what][1]), rel))
    for line in over:
        print("OVER " + line)
    print("%s: %d over" % ("FAIL" if over else "PASS", len(over)))
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main())
