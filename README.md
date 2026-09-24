# site-migration

Crawls a live site and a staging site, then writes a redirect file that maps each live URL to the most similar staging URL.

It combines [url-spider](https://github.com/IslayAnderson/url-spider) (crawling) and [url-redirect](https://github.com/IslayAnderson/url-redirect) (matching), which are included as git submodules.

## Setup

```bash
git clone --recurse-submodules <this repo>
cd site-migration
python3 -m venv .venv
.venv/bin/pip install -r url-spider/requirements.txt
```

If you cloned without `--recurse-submodules`, the script fetches the submodules the first time it runs. Install the requirements after that, or run `git submodule update --init` yourself first.

Each submodule is pinned to a specific commit, so new commits to url-spider or url-redirect aren't picked up automatically. To move to the latest versions:

```bash
git submodule update --remote
git commit -am "Update submodules"
```

After you pull changes to site-migration itself, run `git submodule update` to check out the commits it now points to.

Needs Firefox (default) or Chrome, like url-spider.

## Usage

```bash
.venv/bin/python migrate.py https://www.example.com https://staging.example.com --staging-auth admin -f nginx -o redirects.conf
```

This:

1. crawls the live site and saves the URLs to `live.txt`,
2. crawls the staging site and saves the URLs to `staging.txt`,
3. matches each live URL to the most similar staging URL and writes the redirect file.

URLs that errored, timed out or returned 4xx/5xx are left out of the lists, so dead pages don't get redirects. Ctrl-C during a crawl stops that crawl, keeps what it found and moves on.

To try different thresholds or formats without crawling again, use `--reuse`:

```bash
.venv/bin/python migrate.py https://www.example.com https://staging.example.com --reuse -t 0.5 -f htaccess -o .htaccess
```

### Options

| Option | Default | |
|---|---|---|
| `-o`, `--output` | stdout | redirect file |
| `-f`, `--format` | `csv` | `csv`, `htaccess` or `nginx` |
| `-t`, `--threshold` | `0.4` | minimum similarity score (0–1) to accept a match |
| `--include-low` | off | include the best guess for URLs below the threshold |
| `--fallback PATH` | none | htaccess/nginx: redirect URLs below the threshold to `PATH` |
| `--live-list` | `live.txt` | where to save the live crawl |
| `--staging-list` | `staging.txt` | where to save the staging crawl |
| `--reuse` | off | skip crawling and use the saved lists |
| `--live-auth` | `$LIVE_AUTH` | basic auth for live, `user:pass` or `user` to be prompted |
| `--staging-auth` | `$STAGING_AUTH` | basic auth for staging, `user:pass` or `user` to be prompted |
| `-m`, `--max-pages` | `500` | max pages per site |
| `-w`, `--wait` | `10` | max seconds to wait for a page to render |
| `-p`, `--page-timeout` | `30` | max seconds for a page to load |
| `-s`, `--settle` | `1.5` | seconds links must stay unchanged before moving on |
| `-d`, `--delay` | `0` | extra seconds between pages |
| `-b`, `--browser` | `firefox` | `firefox` or `chrome` |
| `--show` | off | show the browser window |
| `--all-hosts` | off | follow links off each site's domain |

Passwords are asked for before either crawl starts, so the run can be left unattended.

See the url-spider and url-redirect READMEs for how crawling and matching work.
