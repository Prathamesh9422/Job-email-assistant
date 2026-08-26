"""Best-effort HR/contact email discovery from a company's public website.

Never raises; always returns a (possibly empty) list. No JS rendering, no login,
no CAPTCHA handling. Triggered only via an explicit user action in the UI.
"""
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
GENERIC_PREFIXES = ("noreply", "no-reply", "webmaster", "postmaster", "abuse", "mailer-daemon")
LINK_KEYWORDS = re.compile(r"career|careers|contact|jobs|about", re.IGNORECASE)

TIMEOUT = 5
MAX_FOLLOW_LINKS = 3
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; job-triage-bot/1.0)"}


def _slugify(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", company.lower())


def _guess_homepage(company: str) -> str:
    return f"https://{_slugify(company)}.com"


def _fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.text
    except requests.RequestException:
        pass
    return None


def _extract_emails(html: str) -> list[str]:
    found = EMAIL_RE.findall(html)
    return [e for e in found if not e.lower().startswith(GENERIC_PREFIXES)]


def _find_relevant_links(html: str, base_url: str) -> list[str]:
    links = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True) or ""
            href = a["href"]
            if LINK_KEYWORDS.search(text) or LINK_KEYWORDS.search(href):
                full = urljoin(base_url, href)
                if urlparse(full).netloc == urlparse(base_url).netloc:
                    links.append(full)
    except Exception:
        pass
    return links[:MAX_FOLLOW_LINKS]


def scrape_company_emails(company: str, homepage_url: str | None = None) -> list[str]:
    homepage_url = homepage_url or _guess_homepage(company)

    html = _fetch(homepage_url)
    if not html:
        return []

    candidates: set[str] = set(_extract_emails(html))

    for link in _find_relevant_links(html, homepage_url):
        sub_html = _fetch(link)
        if sub_html:
            candidates.update(_extract_emails(sub_html))

    return sorted(candidates)
