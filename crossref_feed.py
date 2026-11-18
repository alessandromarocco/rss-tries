#!/usr/bin/env python3
"""Generates date-sorted RSS 2.0 feeds from the Crossref API.

For each journal listed in feeds.txt, the script retrieves the latest articles
registered with Crossref (title, authors, DOI, abstract, online publication date)
and writes an RSS feed, from newest to oldest, readable by Zotero.

Usage:
    python crossref_feed.py feeds.txt public/

Keyword filter (optional): in feeds.txt, add "|" at the end of a line followed by
a keyword file (e.g. glaciology.txt) and/or comma-separated terms. Only articles
whose title or abstract contains at least one of these terms are kept: one term in
the title is enough, otherwise at least ABSTRACT_MIN mentions in the abstract are
required. Each term is matched at the start of a word: "glaci" matches glacier,
glaciers, glaciology…; a term followed by "$" must be a whole word ("ice cap$" does
not match "ice capacity").

Optional but recommended environment variable:
    CROSSREF_MAILTO=your.address@example.com
    (Crossref serves requests that provide a contact faster and more reliably.)
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from html import unescape
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://api.crossref.org/works"
ROWS = 100  # number of articles kept in each feed
SCAN = 1000  # recent articles scanned for a filtered journal (Crossref maximum: 1000)
ABSTRACT_MIN = 3  # article kept if a term is in the title, or at least 3 mentions in the abstract
SEP = "[\\s\\-\u2010-\u2015\u00a0]+"  # space, hyphen or typographic dash (AGU writes "Ice‐Shelf")
MAILTO = os.environ.get("CROSSREF_MAILTO", "").strip()
UA = "rss-crossref/1.0 (https://github.com" + (f"; mailto:{MAILTO}" if MAILTO else "") + ")"


def fetch(issns, rows=ROWS):
    params = {
        "filter": ",".join(f"issn:{i}" for i in issns) + ",type:journal-article",
        # "published" often contains only the year or month of the volume, and
        # Elsevier/IEEE/AMS do not deposit an online date: sort by DOI
        # registration date, which matches online publication
        "sort": "created",
        "order": "desc",
        "rows": str(rows),
        "select": "DOI,URL,title,author,abstract,container-title,volume,issue,"
                  "article-number,page,published,published-online,published-print,created",
    }
    if MAILTO:
        params["mailto"] = MAILTO
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)["message"]["items"]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(20 * (attempt + 1))  # Crossref rate-limits requests (error 429)


def to_date(field):
    """Converts a Crossref date field ({'date-parts': [[2026, 11, 9]]}) to a datetime."""
    try:
        parts = field["date-parts"][0]
    except (KeyError, IndexError, TypeError):
        return None
    if not parts or parts[0] is None:
        return None
    y, m, d = (list(parts) + [1, 1])[:3]
    try:
        return datetime(int(y), int(m), int(d), 12, tzinfo=timezone.utc)
    except ValueError:
        return None


def online_date(item):
    # online date if complete (to the day), otherwise DOI registration date;
    # "print" dates are only used as a last resort
    try:
        if len(item["published-online"]["date-parts"][0]) == 3:
            return to_date(item["published-online"])
    except (KeyError, IndexError, TypeError):
        pass
    for key in ("created", "published", "published-print"):
        d = to_date(item.get(key))
        if d:
            return d
    return None


def clean_abstract(jats):
    if not jats:
        return ""
    s = re.sub(r"<jats:title>.*?</jats:title>", "", jats, flags=re.S)  # removes "Abstract"
    s = re.sub(r"<(/?)jats:p\b[^>]*>", r"<\1p>", s)
    s = re.sub(r"<(/?)jats:(italic|i)\b[^>]*>", r"<\1i>", s)
    s = re.sub(r"<(/?)jats:(bold|b)\b[^>]*>", r"<\1b>", s)
    s = re.sub(r"<(/?)jats:sub\b[^>]*>", r"<\1sub>", s)
    s = re.sub(r"<(/?)jats:sup\b[^>]*>", r"<\1sup>", s)
    s = re.sub(r"</?jats:[^>]*>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def load_keywords(spec, base):
    """"glaciology.txt, albedo" -> list of terms (files relative to feeds.txt)."""
    terms = []
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        if part.endswith(".txt"):
            for line in (base / part).read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if line:
                    terms.append(line)
        else:
            terms.append(part)
    return terms


def keyword_regex(terms):
    pats = []
    for t in terms:
        whole = t.endswith("$")
        t = t.rstrip("$").strip().lower()
        words = [re.escape(w) for w in re.split(SEP, t) if w]
        pat = r"\b" + SEP.join(words) + (r"\b" if whole else "")
        pats.append(pat)
    return re.compile("|".join(pats), re.I)


def matches(item, rx):
    plain = lambda s: unescape(re.sub(r"<[^>]+>", " ", s))
    if rx.search(plain(" ".join(item.get("title") or []))):
        return True
    # a single passing mention in the abstract ("… less snow …") is not enough
    return len(rx.findall(plain(item.get("abstract") or ""))) >= ABSTRACT_MIN


def author_name(a):
    if a.get("family"):
        return f"{a['family']}, {a['given']}" if a.get("given") else a["family"]
    return a.get("name", "")


def build(items, title, issns):
    entries = []
    for it in items:
        doi = it.get("DOI", "")
        if not doi:
            continue
        entries.append(dict(
            doi=doi,
            title=re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", " ".join(
                it.get("title") or ["(untitled)"])))).strip(),
            date=online_date(it),
            authors=[n for n in (author_name(a) for a in it.get("author", [])) if n],
            abstract=clean_abstract(it.get("abstract", "")),
            journal=(it.get("container-title") or [title])[0],
            volume=it.get("volume", ""),
            number=it.get("article-number") or it.get("issue", ""),
        ))
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    entries.sort(key=lambda e: (e["date"] or epoch, e["doi"]), reverse=True)

    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>https://portal.issn.org/resource/ISSN/{escape(issns[0])}</link>",
        f"<description>{escape(title)} — latest articles (source: Crossref)</description>",
        f"<lastBuildDate>{format_datetime(datetime.now(timezone.utc))}</lastBuildDate>",
    ]
    for e in entries:
        url = f"https://doi.org/{e['doi']}"
        out += ["<item>",
                f"<title>{escape(e['title'])}</title>",
                f"<link>{escape(url)}</link>",
                f'<guid isPermaLink="true">{escape(url)}</guid>']
        if e["date"]:
            out.append(f"<pubDate>{format_datetime(e['date'])}</pubDate>")
            out.append(f"<dc:date>{e['date'].strftime('%Y-%m-%dT%H:%M:%SZ')}</dc:date>")
        out += [f"<dc:creator>{escape(a)}</dc:creator>" for a in e["authors"]]
        out.append(f"<dc:identifier>doi:{escape(e['doi'])}</dc:identifier>")
        out.append(f"<prism:doi>{escape(e['doi'])}</prism:doi>")
        out.append(f"<prism:publicationName>{escape(e['journal'])}</prism:publicationName>")
        if e["volume"]:
            out.append(f"<prism:volume>{escape(e['volume'])}</prism:volume>")
        if e["number"]:
            out.append(f"<prism:number>{escape(e['number'])}</prism:number>")
        if e["abstract"]:
            out.append(f"<description><![CDATA[{e['abstract'].replace(']]>', ']]&gt;')}]]></description>")
        out.append("</item>")
    out += ["</channel>", "</rss>", ""]
    return "\n".join(out)


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    outdir = Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line, _, kw = line.partition("|")
        name, issns, title = line.strip().split(maxsplit=2)
        issns = issns.split(",")
        try:
            if kw.strip():
                rx = keyword_regex(load_keywords(kw, Path(sys.argv[1]).parent))
                scanned = fetch(issns, SCAN)
                items = [it for it in scanned if matches(it, rx)][:ROWS]
                info = f"{len(items)} articles kept out of {len(scanned)} scanned"
            else:
                items = fetch(issns)
                info = f"{len(items)} articles"
            (outdir / name).write_text(build(items, title, issns), encoding="utf-8")
            print(f"OK  {name} ({info})")
        except Exception as exc:  # a failing journal does not block the others
            failures += 1
            print(f"ERR {name}: {exc}", file=sys.stderr)
        time.sleep(3)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
