#!/usr/bin/env python3
"""
Crawl a live site and a staging site, then build a redirect file mapping
each live URL to the most similar staging URL.

Uses the url-spider (crawling) and url-redirect (matching) submodules.

Usage:
    python migrate.py https://www.example.com https://staging.example.com -f nginx -o redirects.conf
"""

import argparse
import getpass
import multiprocessing
import os
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
SPIDER_DIR = HERE / "url-spider"
REDIRECT_DIR = HERE / "url-redirect"
sys.path[:0] = [str(SPIDER_DIR), str(REDIRECT_DIR)]

# fetch the submodules on first run if the repo was cloned without --recurse-submodules
if not (SPIDER_DIR / "spider.py").exists() or not (REDIRECT_DIR / "url_redirects.py").exists():
    print("Fetching url-spider and url-redirect submodules...", file=sys.stderr)
    try:
        subprocess.run(["git", "submodule", "update", "--init"], cwd=HERE, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"Couldn't fetch the submodules ({e}). Run `git submodule update --init` in {HERE}.")

try:
    import spider
    import url_redirects
except ImportError as e:
    sys.exit(f"{e}\nInstall the requirements: .venv/bin/pip install -r url-spider/requirements.txt")


def parse_auth(value, label):
    if not value:
        return None
    username, sep, password = value.partition(":")
    if not sep:
        password = getpass.getpass(f"{label} password for {username}: ")
    return username, password


def crawl_site(label, start_url, auth, args):
    """Crawl one site and return [(url, status)]. Ctrl-C stops this crawl but keeps what was found."""
    hosts = {spider.site(urlparse(spider.normalise(start_url)).netloc)}

    def new_driver():
        driver = spider.make_driver(args.browser, not args.show, bool(auth), args.page_timeout)
        if auth:
            spider.add_basic_auth(driver, *auth, hosts)
        return driver

    print(f"crawling {start_url}", file=sys.stderr)
    crawler = spider.Crawler(new_driver, [start_url], hosts, max_pages=args.max_pages, delay=args.delay,
                             page_timeout=args.page_timeout, max_wait=args.wait, settle=args.settle,
                             same_host=not args.all_hosts)
    try:
        crawler.run(max(1, args.workers))
    except KeyboardInterrupt:
        print("stopped, keeping what was found so far", file=sys.stderr)
    with crawler.cond:
        return list(crawler.results)


def live_pages(results):
    """Keep only URLs that loaded: drop errors, timeouts and 4xx/5xx pages."""
    return [url for url, status in results if not (status in ("error", "timeout") or (isinstance(status, int) and status >= 400))]


def write_list(path, urls):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(u + "\n" for u in urls)


class PrefixedStream:
    """Put a label at the start of every line, so the two crawls' output can be told apart."""

    def __init__(self, stream, prefix):
        self.stream, self.prefix, self.at_line_start = stream, prefix, True

    def write(self, text):
        out = []
        for part in text.splitlines(keepends=True):
            if self.at_line_start:
                out.append(self.prefix)
            out.append(part)
            self.at_line_start = part.endswith("\n")
        self.stream.write("".join(out))
        self.stream.flush()
        return len(text)

    def flush(self):
        self.stream.flush()


def crawl_to_file(label, start_url, auth, path, args):
    """Runs in its own process: crawl one site and save the pages that loaded to `path`."""
    sys.stderr = PrefixedStream(sys.__stderr__, f"[{label}] ")
    results = crawl_site(label, start_url, auth, args)
    urls = live_pages(results)
    write_list(path, urls)
    print(f"{len(urls)} of {len(results)} URLs saved to {path}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Crawl a live and a staging site, then write a redirect file from live URLs to staging URLs.")
    ap.add_argument("live", help="live site start URL")
    ap.add_argument("staging", help="staging site start URL")

    out = ap.add_argument_group("output")
    out.add_argument("-o", "--output", help="redirect file (default: stdout)")
    out.add_argument("-f", "--format", choices=["csv", "htaccess", "nginx"], default="csv")
    out.add_argument("-t", "--threshold", type=float, default=0.4, help="minimum score to accept a match (0-1, default 0.4)")
    out.add_argument("--include-low", action="store_true", help="include best-guess matches below the threshold")
    out.add_argument("--fallback", help="htaccess/nginx: redirect below-threshold URLs here instead (e.g. / )")
    out.add_argument("-j", "--jobs", type=int, help="processes to match URLs with (default: one per CPU core)")
    out.add_argument("--live-list", default="live.txt", help="where to save the live crawl (default: live.txt)")
    out.add_argument("--staging-list", default="staging.txt", help="where to save the staging crawl (default: staging.txt)")
    out.add_argument("--reuse", action="store_true", help="skip crawling and reuse the saved --live-list / --staging-list")

    crawl = ap.add_argument_group("crawling")
    crawl.add_argument("--live-auth", metavar="USER[:PASS]", default=os.environ.get("LIVE_AUTH"),
                       help="HTTP basic auth for the live site; prompts for the password if omitted. Also read from $LIVE_AUTH")
    crawl.add_argument("--staging-auth", metavar="USER[:PASS]", default=os.environ.get("STAGING_AUTH"),
                       help="HTTP basic auth for the staging site; prompts for the password if omitted. Also read from $STAGING_AUTH")
    crawl.add_argument("-m", "--max-pages", type=int, default=500, help="max pages per site (default: 500)")
    crawl.add_argument("--workers", type=int, default=4, help="browsers per site (default: 4, so 8 in total)")
    crawl.add_argument("-d", "--delay", type=float, default=0, help="extra seconds between pages (default: 0)")
    crawl.add_argument("-w", "--wait", type=float, default=10, help="max seconds to wait for a page to render (default: 10)")
    crawl.add_argument("-p", "--page-timeout", type=float, default=30, help="max seconds for a page to load (default: 30)")
    crawl.add_argument("-s", "--settle", type=float, default=1.5, help="seconds links must stay unchanged (default: 1.5)")
    crawl.add_argument("-b", "--browser", choices=("firefox", "chrome"), default="firefox")
    crawl.add_argument("--show", action="store_true", help="show the browser window instead of running headless")
    crawl.add_argument("--all-hosts", action="store_true", help="follow links off each site's domain")
    args = ap.parse_args()

    if not args.reuse:
        # ask for both passwords up front so the run can be left unattended
        live_auth = parse_auth(args.live_auth, "Live")
        staging_auth = parse_auth(args.staging_auth, "Staging")

        # crawl both sites at once, each with its own browser
        crawls = [
            multiprocessing.Process(target=crawl_to_file, args=(label, url, auth, path, args))
            for label, url, auth, path in (("live", args.live, live_auth, args.live_list),
                                           ("staging", args.staging, staging_auth, args.staging_list))
        ]
        for p in crawls:
            p.start()
        # Ctrl-C reaches both crawls directly and they save what they found, so just wait for them
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        for p in crawls:
            p.join()
        signal.signal(signal.SIGINT, previous)
        if any(p.exitcode for p in crawls):
            sys.exit("A crawl failed, see the output above.")

    old_urls = url_redirects.read_urls(args.live_list)
    new_urls = url_redirects.read_urls(args.staging_list)
    if not old_urls:
        sys.exit("No live URLs found.")
    if not new_urls:
        sys.exit("No staging URLs found.")

    results = url_redirects.build_redirects(old_urls, new_urls, args.threshold, args.jobs)

    fh = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
    try:
        written = url_redirects.write_output(results, args.format, fh, args.include_low, args.fallback)
    finally:
        if args.output:
            fh.close()

    counts = {s: sum(1 for r in results if r[3] == s) for s in ("exact", "match", "low_confidence")}
    print(
        f"\n{len(old_urls)} live URLs: {counts['exact']} unchanged, {counts['match']} matched, "
        f"{counts['low_confidence']} below threshold. {written} redirects written"
        + (f" to {args.output}." if args.output else "."),
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
