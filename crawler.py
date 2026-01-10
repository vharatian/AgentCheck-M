"""
Robust Production-Ready Crawler

Uses Crawl4AI browser rendering by default for reliable access.
Falls back to requests for API errors.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Dict, List, Optional, Tuple, Set
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
import tldextract

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    CRAWL4AI_OK = True
except ImportError:
    CRAWL4AI_OK = False

from models import Element, ElementType


# Request headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_domain(url: str) -> str:
    ext = tldextract.extract(url)
    return f"{ext.domain}.{ext.suffix}"


def ensure_http(url: str) -> str:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def same_site(base: str, u: str) -> bool:
    return get_domain(base) == get_domain(u)


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def fetch_with_requests(url: str, timeout: int = 15) -> Tuple[str, str, Dict, float]:
    """Fallback fetch using requests."""
    start = time.time()
    
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=timeout, allow_redirects=True)
        elapsed = time.time() - start
        
        if resp.status_code == 200 and len(resp.text) > 500:
            html = resp.text
            soup = BeautifulSoup(html, "lxml")
            
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            
            title = soup.title.get_text(strip=True) if soup.title else ""
            meta_desc = soup.find("meta", attrs={"name": "description"})
            description = meta_desc.get("content", "")[:300] if meta_desc else ""
            markdown = clean_text(soup.get_text(" "))[:10000]
            
            return markdown, html, {"title": title, "description": description}, elapsed
        
        return "", "", {"error": f"HTTP {resp.status_code}"}, elapsed
    except Exception as e:
        return "", "", {"error": str(e)[:100]}, time.time() - start


class SiteCrawler:
    """
    Production-ready crawler using Crawl4AI browser rendering.
    
    Modern websites (Zalando, Amazon, etc.) require JavaScript rendering.
    Uses Crawl4AI by default for reliable access.
    """
    
    def __init__(self, headless: bool = True, timeout_ms: int = 30000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._crawler = None
        self._initialized = False
        
        if CRAWL4AI_OK:
            self.browser_config = BrowserConfig(
                headless=headless,
                viewport_width=1280,
                viewport_height=900,
            )
            self.crawler_config = CrawlerRunConfig(
                cache_mode=CacheMode.BYPASS,
                page_timeout=timeout_ms,
                wait_until="domcontentloaded",
            )
    
    async def __aenter__(self):
        if CRAWL4AI_OK:
            self._crawler = AsyncWebCrawler(config=self.browser_config)
            await self._crawler.__aenter__()
            self._initialized = True
        return self
    
    async def __aexit__(self, *args):
        if self._crawler:
            await self._crawler.__aexit__(*args)
    
    async def fetch_page(self, url: str) -> Tuple[str, str, Dict, float]:
        """
        Fetch page using Crawl4AI browser rendering.
        Falls back to requests if Crawl4AI fails.
        """
        url = ensure_http(url)
        start = time.time()
        
        # Use Crawl4AI (preferred for modern websites)
        if self._initialized and self._crawler:
            try:
                result = await self._crawler.arun(url, config=self.crawler_config)
                elapsed = time.time() - start
                
                if result.success and result.html:
                    return (
                        result.markdown or "",
                        result.html or "",
                        result.metadata or {},
                        elapsed
                    )
                # If Crawl4AI fails, try requests
            except Exception:
                pass
        
        # Fallback to requests
        return fetch_with_requests(url, timeout=15)
    
    def extract_elements_from_html(self, html: str, page_url: str) -> List[Element]:
        """Extract ALL interactive elements from HTML."""
        if not html:
            return []
        
        soup = BeautifulSoup(html, "lxml")
        elements = []
        element_id = 0
        seen_selectors: Set[str] = set()
        
        def make_id() -> str:
            nonlocal element_id
            element_id += 1
            return f"el_{element_id:04d}"
        
        def get_text(el) -> str:
            text = el.get_text(strip=True)
            if not text:
                text = el.get("aria-label", "")
            if not text:
                text = el.get("title", "")
            if not text:
                text = el.get("placeholder", "")
            if not text:
                text = el.get("alt", "")
            if not text:
                text = el.get("value", "")
            return clean_text(text)[:100]
        
        def get_selector(el) -> str:
            if el.get("id"):
                return f"#{el['id']}"
            if el.get("data-testid"):
                return f"[data-testid='{el['data-testid']}']"
            if el.get("data-test"):
                return f"[data-test='{el['data-test']}']"
            if el.get("name"):
                return f"{el.name}[name='{el['name']}']"
            classes = el.get("class", [])
            if classes:
                return f"{el.name}.{'.'.join(classes[:2])}"
            return el.name
        
        def add_element(el_type: ElementType, el, **kwargs):
            selector = get_selector(el)
            text = get_text(el)
            key = f"{selector}:{text[:30]}"
            
            if key in seen_selectors:
                return
            seen_selectors.add(key)
            
            # Allow inputs without text, require text for others
            if not text and el_type not in [ElementType.INPUT, ElementType.TEXTAREA, ElementType.SEARCH]:
                return
            
            elements.append(Element(
                id=make_id(),
                type=el_type,
                text=text,
                selector=selector,
                page_url=page_url,
                attributes=dict(el.attrs) if el.attrs else {},
                **kwargs
            ))
        
        # BUTTONS
        for btn in soup.find_all("button"):
            add_element(ElementType.BUTTON, btn)
        
        for inp in soup.find_all("input", type=["submit", "button"]):
            add_element(ElementType.BUTTON, inp)
        
        # LINKS
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                add_element(ElementType.LINK, link)
        
        # INPUTS
        for inp in soup.find_all("input"):
            inp_type = inp.get("type", "text").lower()
            if inp_type in ("hidden", "submit", "button", "image"):
                continue
            if inp_type == "search":
                add_element(ElementType.SEARCH, inp, input_type=inp_type)
            else:
                add_element(ElementType.INPUT, inp, input_type=inp_type)
        
        # TEXTAREAS
        for ta in soup.find_all("textarea"):
            add_element(ElementType.TEXTAREA, ta)
        
        # SELECTS
        for sel in soup.find_all("select"):
            options = [clean_text(opt.get_text()) for opt in sel.find_all("option")][:15]
            add_element(ElementType.SELECT, sel, options=[o for o in options if o])
        
        # CHECKBOXES & RADIOS
        for inp in soup.find_all("input", type=["checkbox", "radio"]):
            el_type = ElementType.CHECKBOX if inp.get("type") == "checkbox" else ElementType.RADIO
            add_element(el_type, inp)
        
        # ARIA ROLES
        role_map = {
            "button": ElementType.BUTTON,
            "link": ElementType.LINK,
            "menuitem": ElementType.MENU,
            "tab": ElementType.TAB,
            "checkbox": ElementType.CHECKBOX,
            "radio": ElementType.RADIO,
            "switch": ElementType.CHECKBOX,
            "searchbox": ElementType.SEARCH,
            "combobox": ElementType.DROPDOWN,
            "listbox": ElementType.SELECT,
        }
        for role, el_type in role_map.items():
            for el in soup.find_all(attrs={"role": role}):
                add_element(el_type, el)
        
        # ONCLICK HANDLERS
        for el in soup.find_all(attrs={"onclick": True}):
            if el.name not in ["button", "a", "input"]:
                add_element(ElementType.BUTTON, el)
        
        # ARIA POPUP/EXPANDED
        for el in soup.find_all(attrs={"aria-haspopup": True}):
            add_element(ElementType.DROPDOWN, el)
        
        for el in soup.find_all(attrs={"aria-expanded": True}):
            add_element(ElementType.ACCORDION, el)
        
        # FORMS
        for form in soup.find_all("form"):
            add_element(ElementType.FORM, form)
        
        # SEARCH ROLES
        for el in soup.find_all(attrs={"role": "search"}):
            for inp in el.find_all("input"):
                add_element(ElementType.SEARCH, inp)
        
        # FILTER PATTERNS
        filter_re = re.compile(r'(filter|facet|refine)', re.I)
        for el in soup.find_all(class_=filter_re):
            for inp in el.find_all(["input", "select"]):
                add_element(ElementType.FILTER, inp)
        
        return elements
    
    def extract_internal_links(self, html: str, base_url: str) -> List[str]:
        """Extract all internal links from HTML."""
        if not html:
            return []
        
        soup = BeautifulSoup(html, "lxml")
        links = []
        seen = set()
        
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                full_url = urljoin(base_url, href)
                full_url = full_url.split("#")[0].split("?")[0].rstrip("/")
                
                if full_url in seen:
                    continue
                seen.add(full_url)
                
                if same_site(base_url, full_url):
                    if not re.search(r'\.(jpg|jpeg|png|gif|css|js|pdf|zip)$', full_url, re.I):
                        links.append(full_url)
        
        return links[:100]
