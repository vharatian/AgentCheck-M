from __future__ import annotations
import re, time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse, urldefrag
import requests
from bs4 import BeautifulSoup
import tldextract
import trafilatura
import urllib.robotparser as robotparser


@dataclass
class Page:
    url: str
    title: str | None
    h1: str | None
    text: str
    links: list[str]
    page_type: str


class URLPromptGenerator:
    def __init__(
        self,
        base_url: str,
        max_pages: int = 60,
        max_depth: int = 2,
        per_page_link_cap: int = 25,
        delay_s: float = 0.2,
        timeout_s: int = 15,
        respect_robots: bool = True,
    ):
        if not base_url.startswith(("http://", "https://")):
            base_url = "https://" + base_url
        self.base_url = base_url.rstrip("/")
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.per_page_link_cap = per_page_link_cap
        self.delay_s = delay_s
        self.timeout_s = timeout_s

        ext = tldextract.extract(self.base_url)
        self.reg_domain = f"{ext.domain}.{ext.suffix}"

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "PromptEvalGenerator/0.1 (+no-login-no-destructive)"})

        self.rp = None
        if respect_robots:
            self.rp = robotparser.RobotFileParser()
            self.rp.set_url(urljoin(self.base_url + "/", "/robots.txt"))
            try:
                self.rp.read()
            except Exception:
                self.rp = None  # fail open (or change to fail closed if you prefer)

    def _same_site(self, u: str) -> bool:
        ext = tldextract.extract(u)
        return f"{ext.domain}.{ext.suffix}" == self.reg_domain

    def _allowed(self, url: str) -> bool:
        if not self.rp:
            return True
        try:
            return self.rp.can_fetch(self.session.headers["User-Agent"], url)
        except Exception:
            return True

    def _normalize(self, u: str) -> str | None:
        if not u:
            return None
        u, _ = urldefrag(u)
        # drop common tracking params aggressively (keep it simple; extend as needed)
        u = re.sub(r"(\?|&)(utm_[^=&]+|gclid|fbclid|yclid)=[^&#]+", "", u, flags=re.I)
        u = u.rstrip("?&")
        return u

    def _get(self, url: str) -> str | None:
        if not self._allowed(url):
            return None
        try:
            r = self.session.get(url, timeout=self.timeout_s)
            if r.status_code >= 400:
                return None
            ctype = r.headers.get("Content-Type", "")
            if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                return None
            return r.text
        except Exception:
            return None

    def _discover_sitemap_urls(self) -> list[str]:
        # Try sitemap.xml (basic). You can extend with sitemap index parsing if needed.
        sm_url = urljoin(self.base_url + "/", "/sitemap.xml")
        xml = self._get(sm_url)
        if not xml:
            return []
        soup = BeautifulSoup(xml, "xml")
        urls = []
        for loc in soup.find_all("loc"):
            u = loc.get_text(strip=True)
            u = self._normalize(u)
            if u and self._same_site(u):
                urls.append(u)
        # cap to avoid huge sitemaps
        return list(dict.fromkeys(urls))[:200]

    def _extract_links(self, html: str, page_url: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        out = []
        for a in soup.select("a[href]"):
            href = a.get("href")
            u = self._normalize(urljoin(page_url, href))
            if not u:
                continue
            if not self._same_site(u):
                continue
            if re.search(r"\.(jpg|png|gif|pdf|zip|mp4)$", u, re.I):
                continue
            # avoid obvious facet/pagination explosions (tune per your needs)
            if re.search(r"[?&](page|p)=\d+", u, re.I):
                continue
            out.append(u)
        return list(dict.fromkeys(out))

    def _page_type(self, url: str, title: str | None, text: str) -> str:
        u = url.lower()
        t = (title or "").lower()
        x = (text or "").lower()

        if any(k in u for k in ["/privacy", "/terms", "/legal", "impressum"]) or any(k in x for k in ["privacy", "terms of", "legal notice"]):
            return "policy"
        if "pricing" in u or "pricing" in t or "pricing" in x:
            return "pricing"
        if any(k in u for k in ["/help", "/support", "/contact", "/faq"]) or any(k in x for k in ["help center", "support", "contact us", "faq"]):
            return "support"
        if any(k in u for k in ["/docs", "/documentation", "/developer"]) or any(k in x for k in ["documentation", "api reference", "developer guide"]):
            return "docs"
        if any(k in x for k in ["search", "filter", "sort by"]):
            return "search_or_listing"
        if len(x) > 2000:
            return "article_or_detail"
        return "general"

    def crawl_representative(self) -> list[Page]:
        seeds = [self.base_url] + self._discover_sitemap_urls()[:30]
        seen = set()
        queue = [(u, 0) for u in seeds]
        pages: list[Page] = []

        while queue and len(pages) < self.max_pages:
            url, depth = queue.pop(0)
            if url in seen or depth > self.max_depth:
                continue
            seen.add(url)

            html = self._get(url)
            if not html:
                continue

            soup = BeautifulSoup(html, "lxml")
            title = soup.title.get_text(strip=True) if soup.title else None
            h1tag = soup.find("h1")
            h1 = h1tag.get_text(strip=True) if h1tag else None

            text = trafilatura.extract(html, include_tables=True) or ""
            links = self._extract_links(html, url)

            ptype = self._page_type(url, title, text)
            pages.append(Page(url=url, title=title, h1=h1, text=text[:6000], links=links, page_type=ptype))

            for nxt in links[: self.per_page_link_cap]:
                if nxt not in seen:
                    queue.append((nxt, depth + 1))

            time.sleep(self.delay_s)

        return pages

    def generate_prompts(self, pages: list[Page], max_prompts: int = 50) -> list[str]:
        # Representative sampling per page type
        by_type: dict[str, list[Page]] = {}
        for p in pages:
            by_type.setdefault(p.page_type, []).append(p)

        reps: list[Page] = []
        for typ, plist in by_type.items():
            reps.extend(plist[:4])  # 4 representatives/type

        prompts: list[str] = []

        def add(s: str):
            if len(prompts) < max_prompts:
                prompts.append(s)

        # Core templates (plain text, scorable, no login/destructive)
        for p in reps:
            if p.page_type == "policy":
                add(
                    f"[L1] On {p.url}, find the key user-facing rule stated on this policy page. "
                    f"Constraints: do not sign in. Output: (a) the rule, (b) one exception (if stated). "
                    f"Evidence: cite the exact URL and quote 1–2 sentences that support your answer."
                )
            elif p.page_type == "pricing":
                add(
                    f"[L1] On {p.url}, extract one concrete pricing figure and what it applies to. "
                    f"Constraints: do not sign in. Evidence: cite URL + quote the line containing the price. "
                    f"Output: item/service, price, and any conditions/tiers mentioned."
                )
                add(
                    f"[L3] Using {p.url} and one additional official page reachable from it, cross-check whether the pricing has tiers/limits/conditions. "
                    f"Constraints: do not sign in. Evidence: cite both URLs and quote relevant lines from each. "
                    f"Output: a short reconciliation stating what is priced, how, and under what conditions."
                )
            elif p.page_type == "support":
                add(
                    f"[L2] Starting from {p.url}, locate a help article about a common user problem relevant to this site. "
                    f"Constraints: do not sign in; do not contact support. "
                    f"Output: a 4–6 step checklist derived from the article. Evidence: cite the final article URL and quote one prerequisite/limitation line."
                )
            elif p.page_type == "docs":
                add(
                    f"[L2] Starting from {p.url}, locate a 'Getting Started' / 'Quickstart' style document. "
                    f"Constraints: do not sign in; do not execute setup actions. "
                    f"Output: prerequisites + first 3 steps. Evidence: cite URL(s) and quote at least one prerequisite line."
                )
                add(
                    f"[L4] Attempt to access any console/dashboard/action page linked from {p.url}. "
                    f"Constraints: do NOT sign in; stop immediately at any authentication prompt. "
                    f"Output: where the login gate occurs, what is visible without login, and the last public URL reached."
                )
            elif p.page_type == "search_or_listing":
                add(
                    f"[L2] Use the site’s search starting from {p.url} to find one item/page matching a single clear constraint you can verify on-page. "
                    f"Constraints: do not sign in. Evidence: provide the final URL and quote the text proving the constraint."
                )
                add(
                    f"[L4] Starting from {p.url}, perform a search that yields no results (choose a very specific query). "
                    f"Then recover by refining the query once. Constraints: do not sign in. "
                    f"Output: what you observed on the no-results page (quote any message if present), what you changed, and the final URL."
                )
            else:
                add(
                    f"[L5] Starting from {p.url}, produce a short 'public-only site guide' with: "
                    f"(1) main sections you can reach without login, (2) one key policy page, (3) one help/support page, and (4) any feature that appears login-gated. "
                    f"Constraints: do not sign in. Evidence: provide URLs for each item and quote at least one line from a policy/help page."
                )

        # Light dedupe
        out, seen = [], set()
        for pr in prompts:
            k = pr[:180]
            if k not in seen:
                out.append(pr)
                seen.add(k)
        return out[:max_prompts]


if __name__ == "__main__":
    url = input("URL: ").strip()
    gen = URLPromptGenerator(url, max_pages=60, max_depth=2, per_page_link_cap=25, respect_robots=True)
    pages = gen.crawl_representative()
    prompts = gen.generate_prompts(pages, max_prompts=45)
    print("\n\n".join(f"{i+1}. {p}" for i, p in enumerate(prompts)))