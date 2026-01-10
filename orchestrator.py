"""
LLM Orchestrator with Stop Support

Uses OpenRouter API for site exploration with stop capability.
"""
from __future__ import annotations

import asyncio
import time
from typing import Callable, Optional
from urllib.parse import urljoin

from models import Element, ElementType, SiteMap
from crawler import SiteCrawler, get_domain, ensure_http
from prompts import plan_exploration_prompt
from llm_client import LLMClient


DEFAULT_MODEL = "google/gemini-3-flash-preview"


class Orchestrator:
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        max_pages: int = 10,
        headless: bool = True
    ):
        self.llm = LLMClient(api_key=api_key, model=model)
        self.max_pages = max_pages
        self.headless = headless
    
    def map_site(self, url: str, progress_callback=None) -> SiteMap:
        """Map a website (no stop support)."""
        return self.map_site_with_stop(url, progress_callback, stop_check=lambda: False)
    
    def map_site_with_stop(
        self, 
        url: str, 
        progress_callback=None, 
        stop_check: Callable[[], bool] = None
    ) -> SiteMap:
        """Map a website with stop support."""
        return asyncio.run(self._map_site_async(url, progress_callback, stop_check or (lambda: False)))
    
    async def _map_site_async(
        self, 
        url: str, 
        progress_callback, 
        stop_check: Callable[[], bool]
    ) -> SiteMap:
        url = ensure_http(url)
        domain = get_domain(url)
        
        site_map = SiteMap(url=url, domain=domain)
        start_time = time.time()
        
        def log(msg: str):
            elapsed = time.time() - start_time
            timed_msg = f"[{elapsed:.1f}s] {msg}"
            site_map.log(timed_msg)
            if progress_callback:
                progress_callback(timed_msg)
        
        log(f"Starting: {url}")
        
        visited_urls = set()
        urls_to_visit = [url]
        
        async with SiteCrawler(headless=self.headless) as crawler:
            while urls_to_visit and site_map.pages_crawled < self.max_pages:
                # Check for stop
                if stop_check():
                    log("⏹️ Stop requested")
                    break
                
                current_url = urls_to_visit.pop(0)
                
                if current_url in visited_urls:
                    continue
                
                visited_urls.add(current_url)
                site_map.add_page(current_url)
                
                log(f"[Page {site_map.pages_crawled}] {current_url[:50]}...")
                
                # Fetch
                md, html, meta, fetch_time = await crawler.fetch_page(current_url)
                
                if not html:
                    log(f"  ⚠ Failed ({fetch_time:.1f}s)")
                    continue
                
                log(f"  ✓ Fetched ({fetch_time:.1f}s)")
                
                # Extract elements
                elements = crawler.extract_elements_from_html(html, current_url)
                for el in elements:
                    site_map.add_element(el)
                
                log(f"  ✓ {len(elements)} elements")
                
                # LLM analysis (skip if stopped)
                if not stop_check():
                    try:
                        prompt = plan_exploration_prompt(
                            page_markdown=md[:6000],
                            page_url=current_url,
                            visited_urls=list(visited_urls),
                            discovered_elements=site_map.elements_discovered
                        )
                        
                        llm_resp = self.llm.generate_json(prompt)
                        
                        if "error" not in llm_resp:
                            # Add LLM elements
                            for el_data in llm_resp.get("elements", []):
                                try:
                                    el_type = el_data.get("type", "other")
                                    el = Element(
                                        id=f"llm_{site_map.elements_discovered + 1:04d}",
                                        type=ElementType(el_type) if el_type in [e.value for e in ElementType] else ElementType.OTHER,
                                        text=el_data.get("text", ""),
                                        selector=el_data.get("selector_hint", ""),
                                        page_url=current_url,
                                        attributes={"purpose": el_data.get("purpose", "")}
                                    )
                                    site_map.add_element(el)
                                except:
                                    pass
                            
                            # Add links
                            for link_data in llm_resp.get("links_to_visit", []):
                                link_url = link_data.get("url", "")
                                if link_url:
                                    if not link_url.startswith("http"):
                                        link_url = urljoin(current_url, link_url)
                                    if link_url not in visited_urls and link_url not in urls_to_visit:
                                        if get_domain(link_url) == domain:
                                            urls_to_visit.append(link_url)
                    except:
                        pass
                
                # Fallback: extract links from HTML
                new_links = crawler.extract_internal_links(html, url)
                for link in new_links[:5]:
                    if link not in visited_urls and link not in urls_to_visit:
                        urls_to_visit.append(link)
                
                log(f"  Total: {site_map.elements_discovered} elements | Queue: {len(urls_to_visit)}")
                
                await asyncio.sleep(0.2)
        
        total_time = time.time() - start_time
        log(f"✅ Done: {site_map.pages_crawled} pages, {site_map.elements_discovered} elements ({total_time:.1f}s)")
        
        return site_map
