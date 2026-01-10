"""
Site Mapper & Prompt Generator

Features:
- REAL stop button (file-based signal)
- Difficulty checkboxes actually filter prompts
- Data preserved when stopped
"""
import streamlit as st
import json
import os
import time
import asyncio
from pathlib import Path

st.set_page_config(
    page_title="Site Mapper & Prompt Generator",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp { background-color: #0e1117; }
    .element-item { 
        background: #1e1e2e; 
        padding: 8px 12px; 
        margin: 4px 0; 
        border-radius: 6px;
        font-family: monospace;
        font-size: 0.85em;
    }
    .prompt-card {
        background: #1a1a2e;
        border-radius: 8px;
        padding: 15px;
        margin: 10px 0;
        border-left: 4px solid #2196F3;
    }
    .L1 { border-left-color: #4CAF50; }
    .L2 { border-left-color: #8BC34A; }
    .L3 { border-left-color: #FFC107; }
    .L4 { border-left-color: #FF9800; }
    .L5 { border-left-color: #F44336; }
</style>
""", unsafe_allow_html=True)

# Stop signal file
STOP_FILE = Path("/tmp/site_mapper_stop_signal")

def request_stop():
    STOP_FILE.touch()

def clear_stop():
    if STOP_FILE.exists():
        STOP_FILE.unlink()

def should_stop():
    return STOP_FILE.exists()

try:
    from generator import PromptGenerator, DIFFICULTY_LEVELS, WORD_COUNTS, generate_prompts_url_only
    from models import SiteMap, Element, ElementType
    from crawler import SiteCrawler, ensure_http, get_domain
    from llm_client import DEFAULT_MODEL
    ALL_OK = True
except ImportError as e:
    ALL_OK = False
    IMPORT_ERROR = str(e)


def init_state():
    defaults = {
        "site_map": None,
        "prompts": [],
        "is_running": False,
        "was_stopped": False,
        "url_only_mode": False,
        "current_url": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def main():
    init_state()
    clear_stop()  # Clear any old stop signals
    
    st.title("🗺️ Site Mapper & Prompt Generator")
    st.caption(f"OpenRouter • {DEFAULT_MODEL if ALL_OK else 'N/A'}")
    
    if not ALL_OK:
        st.error(f"Import error: {IMPORT_ERROR}")
        return
    
    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        
        api_key = st.text_input("OpenRouter API Key", 
                                value=os.getenv("OPENROUTER_API_KEY", ""), 
                                type="password")
        
        st.divider()
        
        st.markdown("**📊 Generation Mode**")
        use_crawl_data = st.toggle("Use Crawl Data", value=True, 
                                   help="ON: Crawl site for detailed element-aware prompts\nOFF: Generate from URL only (faster, inference-based)")
        
        if use_crawl_data:
            st.caption("🔍 Will crawl pages and extract elements")
        else:
            st.caption("⚡ Fast mode - infers from URL only")
        
        st.divider()
        max_pages = st.slider("Max Pages", 3, 100, 10, disabled=not use_crawl_data)
        prompts_per_level = st.slider("Prompts per Level", 3, 20, 5)
        
        st.divider()
        st.markdown("**Select Difficulty Levels**")
        st.caption("Only selected levels will be generated")
        
        selected_difficulties = []
        for level, label in DIFFICULTY_LEVELS.items():
            word_info = WORD_COUNTS.get(level, "")
            checked = st.checkbox(f"{level}: {label} ({word_info})", 
                                 value=level in ["L2", "L3", "L4"], 
                                 key=f"diff_{level}")
            if checked:
                selected_difficulties.append(level)
        
        if not selected_difficulties:
            st.warning("Select at least one level!")
            selected_difficulties = ["L3"]
        
        st.success(f"Will generate: {', '.join(selected_difficulties)}")
    
    # Main area
    url = st.text_input("🌐 Website URL", placeholder="https://amazon.com")
    
    # Button row - changes based on mode
    if use_crawl_data:
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            start_btn = st.button("🚀 Start Mapping", type="primary", use_container_width=True)
        with col2:
            stop_btn = st.button("🛑 STOP & Use Data", type="secondary", use_container_width=True)
        with col3:
            clear_btn = st.button("🗑️ Clear", use_container_width=True)
        url_only_btn = False
    else:
        col1, col2 = st.columns([3, 1])
        with col1:
            url_only_btn = st.button("⚡ Generate Prompts (URL Only)", type="primary", use_container_width=True)
        with col2:
            clear_btn = st.button("🗑️ Clear", use_container_width=True)
        start_btn = False
        stop_btn = False
    
    # Handle buttons
    if clear_btn:
        st.session_state.site_map = None
        st.session_state.prompts = []
        st.session_state.was_stopped = False
        clear_stop()
        st.rerun()
    
    if stop_btn:
        request_stop()
        st.warning("⏹️ Stop signal sent! Waiting for current page to finish...")
        time.sleep(0.5)  # Give time for signal to be read
        st.rerun()
    
    # URL-Only mode - generate directly without crawling
    if url_only_btn and url:
        if not api_key:
            st.error("⚠️ API key required")
            st.stop()
        
        os.environ["OPENROUTER_API_KEY"] = api_key
        st.session_state.site_map = None  # Clear any existing site map
        st.session_state.prompts = []
        
        with st.status("⚡ Generating prompts from URL...", expanded=True) as s:
            try:
                # Store URL for export filename
                import tldextract
                ext = tldextract.extract(url)
                st.session_state.current_url = f"{ext.domain}.{ext.suffix}"
                
                prompts = generate_prompts_url_only(
                    url=url,
                    api_key=api_key,
                    prompts_per_difficulty=prompts_per_level,
                    difficulties=selected_difficulties,
                    progress_callback=lambda m: st.write(m)
                )
                st.session_state.prompts = prompts
                st.session_state.url_only_mode = True
                s.update(label=f"✅ {len(prompts)} prompts generated (URL-only mode)!", state="complete")
            except Exception as e:
                s.update(label=f"❌ {str(e)[:50]}", state="error")
    
    # Check if we have data from a stopped run
    if st.session_state.site_map and st.session_state.was_stopped and not st.session_state.prompts:
        site_map = st.session_state.site_map
        st.success(f"✅ Stopped with {site_map.pages_crawled} pages, {site_map.elements_discovered} elements. Ready to generate prompts!")
    
    # Run mapping
    if start_btn and url:
        if not api_key:
            st.error("⚠️ API key required")
            st.stop()
        
        os.environ["OPENROUTER_API_KEY"] = api_key
        clear_stop()  # Clear any previous stop signal
        
        # Reset
        st.session_state.site_map = None
        st.session_state.prompts = []
        st.session_state.is_running = True
        st.session_state.was_stopped = False
        
        # Progress containers
        status_box = st.empty()
        
        col_log, col_elem = st.columns(2)
        with col_log:
            st.markdown("### 📋 Progress")
            log_area = st.empty()
        with col_elem:
            st.markdown("### 🔍 Elements Found")
            elem_area = st.empty()
        
        logs = []
        elements_display = []
        start_time = time.time()
        
        status_box.info("🔄 Mapping... Click **STOP & Use Data** anytime to use collected data")
        
        try:
            url_clean = ensure_http(url)
            domain = get_domain(url_clean)
            site_map = SiteMap(url=url_clean, domain=domain)
            st.session_state.site_map = site_map  # Store immediately
            
            async def crawl():
                nonlocal site_map
                visited = set()
                to_visit = [url_clean]
                
                async with SiteCrawler(headless=True) as crawler:
                    page_num = 0
                    
                    while to_visit and page_num < max_pages:
                        # CHECK FOR STOP SIGNAL
                        if should_stop():
                            elapsed = time.time() - start_time
                            logs.append(f"[{elapsed:.1f}s] ⏹️ STOPPED BY USER")
                            log_area.code("\n".join(logs[-15:]))
                            st.session_state.was_stopped = True
                            break
                        
                        current = to_visit.pop(0)
                        if current in visited:
                            continue
                        
                        visited.add(current)
                        page_num += 1
                        site_map.add_page(current)
                        
                        elapsed = time.time() - start_time
                        logs.append(f"[{elapsed:.1f}s] Page {page_num}/{max_pages}: {current[:45]}...")
                        log_area.code("\n".join(logs[-15:]))
                        
                        # Fetch
                        md, html, meta, fetch_time = await crawler.fetch_page(current)
                        
                        if html:
                            # Extract elements
                            elements = crawler.extract_elements_from_html(html, current)
                            for el in elements:
                                site_map.add_element(el)
                                t = el.type.value if hasattr(el.type, 'value') else str(el.type)
                                text = el.text[:35] if el.text else "(no text)"
                                elements_display.append(f"[{t}] {text}")
                            
                            elem_area.code("\n".join(elements_display[-20:]))
                            logs.append(f"  ✓ {len(elements)} elements ({fetch_time:.1f}s)")
                            log_area.code("\n".join(logs[-15:]))
                            
                            # Update session state after each page
                            st.session_state.site_map = site_map
                            
                            # Get links
                            links = crawler.extract_internal_links(html, url_clean)
                            for link in links[:5]:
                                if link not in visited and link not in to_visit:
                                    to_visit.append(link)
                        else:
                            logs.append(f"  ⚠ Failed to fetch")
                            log_area.code("\n".join(logs[-15:]))
                        
                        await asyncio.sleep(0.1)
                
                return site_map
            
            site_map = asyncio.run(crawl())
            st.session_state.site_map = site_map
            st.session_state.is_running = False
            
            elapsed = time.time() - start_time
            
            if st.session_state.was_stopped:
                status_box.warning(f"⏹️ Stopped: {site_map.pages_crawled} pages, {site_map.elements_discovered} elements ({elapsed:.1f}s)")
            else:
                status_box.success(f"✅ Complete: {site_map.pages_crawled} pages, {site_map.elements_discovered} elements ({elapsed:.1f}s)")
            
            clear_stop()
            
        except Exception as e:
            status_box.error(f"❌ Error: {str(e)[:100]}")
            st.session_state.is_running = False
            clear_stop()
    
    # Show results if we have data
    if st.session_state.site_map and st.session_state.site_map.elements_discovered > 0:
        site_map = st.session_state.site_map
        
        st.divider()
        
        # Stats
        cols = st.columns(4)
        cols[0].metric("Pages", site_map.pages_crawled)
        cols[1].metric("Elements", site_map.elements_discovered)
        cols[2].metric("Buttons", sum(1 for e in site_map.elements if e.type == ElementType.BUTTON))
        cols[3].metric("Links", sum(1 for e in site_map.elements if e.type == ElementType.LINK))
        
        # Elements
        with st.expander("📊 All Elements", expanded=False):
            # Type counts summary
            type_counts = {}
            for el in site_map.elements:
                t = el.type.value if hasattr(el.type, 'value') else str(el.type)
                type_counts[t] = type_counts.get(t, 0) + 1
            
            cols = st.columns(4)
            for i, (t, c) in enumerate(sorted(type_counts.items(), key=lambda x: -x[1])):
                cols[i % 4].write(f"**{t}**: {c}")
            
            st.divider()
            
            # Build copyable text
            elements_text = []
            for el in site_map.elements:
                t = el.type.value if hasattr(el.type, 'value') else str(el.type)
                text = el.text[:80] if el.text else "(no text)"
                elements_text.append(f"[{t}] {text}")
            
            # Scrollable container with all elements
            st.markdown("""
            <style>
            .scrollable-elements {
                max-height: 400px;
                overflow-y: auto;
                background: #1a1a2e;
                padding: 15px;
                border-radius: 8px;
                font-family: monospace;
                font-size: 0.85em;
                white-space: pre-wrap;
            }
            </style>
            """, unsafe_allow_html=True)
            
            st.markdown(f'<div class="scrollable-elements">{chr(10).join(elements_text)}</div>', unsafe_allow_html=True)
            
            st.divider()
            
            # Copy-friendly text area
            st.markdown("**📋 Copy All Elements:**")
            st.text_area(
                "Elements (select all and copy)",
                value="\n".join(elements_text),
                height=200,
                label_visibility="collapsed"
            )
            
            # Download button for elements
            st.download_button(
                "📥 Download Elements as TXT",
                "\n".join(elements_text),
                f"elements_{site_map.domain}.txt",
                use_container_width=True
            )
        
        # Generate prompts button
        if not st.session_state.prompts:
            st.markdown(f"**Will generate prompts for: {', '.join(selected_difficulties)}**")
            
            if st.button("🎯 Generate Prompts", type="primary", use_container_width=True):
                with st.status("🔄 Generating...", expanded=True) as s:
                    try:
                        gen = PromptGenerator(api_key=api_key)
                        prompts = gen.generate_prompts(
                            site_map=site_map,
                            prompts_per_difficulty=prompts_per_level,
                            difficulties=selected_difficulties,  # USE SELECTED ONLY
                            progress_callback=lambda m: st.write(m)
                        )
                        st.session_state.prompts = prompts
                        s.update(label=f"✅ {len(prompts)} prompts!", state="complete")
                    except Exception as e:
                        s.update(label=f"❌ {str(e)[:50]}", state="error")
    
    # Display prompts
    if st.session_state.prompts:
        prompts = st.session_state.prompts
        
        st.divider()
        st.subheader(f"📋 Prompts ({len(prompts)})")
        
        by_diff = {}
        for p in prompts:
            by_diff.setdefault(p.difficulty, []).append(p)
        
        if by_diff:
            tabs = st.tabs([f"{d} - {WORD_COUNTS.get(d, '')}" for d in by_diff])
            for tab, (diff, ps) in zip(tabs, by_diff.items()):
                with tab:
                    for i, p in enumerate(ps, 1):
                        wc = len(p.prompt.split())
                        st.markdown(f"""
                        <div class="prompt-card {diff}">
                            <b>#{i}</b> [{p.category}] ({wc} words)<br><br>
                            {p.prompt}
                        </div>
                        """, unsafe_allow_html=True)
        
        # Export
        st.divider()
        
        # Get domain for filename
        if st.session_state.site_map:
            domain = st.session_state.site_map.domain
        else:
            domain = st.session_state.current_url or "url_only"
        
        # Show mode indicator
        if st.session_state.url_only_mode:
            st.caption("⚡ These prompts were generated in **URL-only mode** (no crawling data)")
        else:
            st.caption("🔍 These prompts were generated using **crawled element data**")
        
        c1, c2, c3 = st.columns(3)
        c1.download_button("📥 JSON", json.dumps([p.to_dict() for p in prompts], indent=2),
                          f"prompts_{domain}.json", use_container_width=True)
        import pandas as pd
        c2.download_button("📥 CSV", pd.DataFrame([p.to_dict() for p in prompts]).to_csv(index=False),
                          f"prompts_{domain}.csv", use_container_width=True)
        c3.download_button("📥 TXT", "\n\n".join([f"[{p.difficulty}] {p.prompt}" for p in prompts]),
                          f"prompts_{domain}.txt", use_container_width=True)


if __name__ == "__main__":
    main()
