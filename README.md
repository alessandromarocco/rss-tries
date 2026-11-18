# Date-sorted RSS feeds generated from Crossref

Cambridge Core RSS feeds are ordered by article number and stop at around a hundred
articles: the most recent ones are missing. Instead, `crossref_feed.py` builds a feed
from the Crossref API, which registers every DOI:

- the 100 latest articles of each journal (adjustable with `ROWS` in the script);
- sorted from newest to oldest, by online publication date;
- title, authors, DOI, volume, article number and abstract (when the publisher has deposited it).

The script only uses the Python standard library. Journals are listed in
`feeds.txt` (one line per journal: output file, ISSN, title, optional filter).

## Keyword filter

For a general-interest journal, add `| glaciology.txt` at the end of its line in `feeds.txt`.
The script then scans its 1000 latest articles and keeps only the glaciology ones:

- one term from `glaciology.txt` in the **title** is enough;
- otherwise, **at least 3 mentions in the abstract** are required (a single passing
  mention, such as "less snow" in a hydrology article, is not enough);
- Elsevier does not send abstracts to Crossref: for its journals (RSE, CRST, ISPRS),
  only the title counts.

`glaciology.txt` can be edited freely: one term per line, matched at the start of a word
(`glaci` matches glacier, glaciology…). Terms can also be added directly on the line:
`| glaciology.txt, albedo`.

## Setup (once) on another repository

1. Create a **public** repository on GitHub and add `crossref_feed.py`,
   `feeds.txt`, `glaciology.txt` and `.github/workflows/feeds.yml` (keeping this path).
2. *Settings → Pages → Build and deployment → Source*: choose **GitHub Actions**.
3. (Recommended) *Settings → Secrets and variables → Actions → **Secrets** tab → New repository
   secret*: name `CROSSREF_MAILTO`, value = your email address. A secret appears neither in the
   repository files nor in the run logs, even if the repository is public; only Crossref
   receives it.
4. *Actions → Sorted RSS feeds → Run workflow*.
5. In Zotero, optionally unsubscribe from the old feeds first, then subscribe to:
   - `https://<user>.github.io/<repository>/journal-of-glaciology.xml`
   - `https://<user>.github.io/<repository>/annals-of-glaciology.xml`
   - etc.

The feeds are regenerated every day. To add a journal, add a line to `feeds.txt`
with its ISSNs (print and online).

## Locally

```bash
CROSSREF_MAILTO=me@example.com python crossref_feed.py feeds.txt public
cd public && python -m http.server 8000
# then in Zotero: http://localhost:8000/journal-of-glaciology.xml
```
