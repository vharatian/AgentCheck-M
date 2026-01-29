"""
Agent Testing UI

A simple Streamlit interface to test the agent swarm components.
Run with: streamlit run test_agents.py --server.port 8505
"""

import streamlit as st
import json
from agents.flow_discovery import FlowDiscoveryAgent, FlowType

st.set_page_config(
    page_title="Agent Swarm Tester",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Agent Swarm Tester")
st.markdown("Test each agent component individually")

# Tabs for different agents
tab1, tab2, tab3, tab4 = st.tabs(["🔍 Flow Discovery", "🎲 Diversity", "🧹 Dedupe", "⚖️ Judge"])

with tab1:
    st.header("Flow Discovery Agent")
    st.markdown("Discovers user flows from site elements and URLs")
    
    # Input mode selection
    input_mode = st.radio(
        "Input Mode:",
        ["🌐 Crawl a URL", "📝 Manual Input"],
        horizontal=True
    )
    
    if input_mode == "🌐 Crawl a URL":
        st.subheader("Enter Website URL")
        url_to_crawl = st.text_input(
            "Website URL:",
            placeholder="https://amazon.com",
            help="Enter a website URL to crawl and discover flows"
        )
        
        max_pages = st.slider("Max pages to crawl", 1, 20, 5)
        
        if st.button("🕷️ Crawl & Discover", type="primary"):
            if not url_to_crawl:
                st.error("Please enter a URL")
            else:
                import asyncio
                from crawler import SiteCrawler, ensure_http
                
                url_to_crawl = ensure_http(url_to_crawl)
                
                with st.spinner(f"Crawling {url_to_crawl}..."):
                    async def crawl_site():
                        all_elements = []
                        all_urls = [url_to_crawl]
                        visited = set()
                        
                        async with SiteCrawler(headless=True) as crawler:
                            to_visit = [url_to_crawl]
                            
                            while to_visit and len(visited) < max_pages:
                                url = to_visit.pop(0)
                                if url in visited:
                                    continue
                                visited.add(url)
                                
                                st.write(f"  📄 Crawling: {url[:60]}...")
                                
                                markdown, html, meta, elapsed = await crawler.fetch_page(url)
                                
                                if html:
                                    # Extract elements
                                    elements = crawler.extract_elements_from_html(html, url)
                                    all_elements.extend(elements)
                                    
                                    # Extract links
                                    links = crawler.extract_internal_links(html, url)
                                    for link in links:
                                        if link not in visited and link not in to_visit:
                                            to_visit.append(link)
                                            all_urls.append(link)
                        
                        return all_elements, list(set(all_urls))
                    
                    elements, urls = asyncio.run(crawl_site())
                
                st.success(f"✅ Crawled {len(urls)} pages, found {len(elements)} elements")
                
                # Store in session state for display
                st.session_state['crawled_elements'] = elements
                st.session_state['crawled_urls'] = urls
                
                # Run flow discovery
                agent = FlowDiscoveryAgent()
                
                # Convert elements to text list
                element_texts = [f"{e.type.value}: {e.text} ({e.selector})" for e in elements if e.text]
                
                result = agent.discover(element_texts, urls, include_partial=True)
                
                # Stats
                st.subheader("📊 Flow Discovery Results")
                col_a, col_b, col_c, col_d = st.columns(4)
                col_a.metric("Patterns Checked", result.stats["patterns_checked"])
                col_b.metric("Patterns Matched", result.stats["patterns_matched"])
                col_c.metric("Flows Discovered", result.stats["flows_discovered"])
                col_d.metric("Avg Confidence", f"{result.stats['average_confidence']:.2f}")
                
                # Flows
                if result.flows:
                    st.subheader("🎯 Discovered Flows")
                    for flow in result.flows:
                        status = "✅" if flow.flow_type == FlowType.HAPPY_PATH else "🟡"
                        with st.expander(f"{status} {flow.name} ({flow.flow_type.value}) - Confidence: {flow.confidence}"):
                            st.markdown("**Evidence:**")
                            st.write(flow.evidence)
                            st.markdown("**Steps:**")
                            for i, step in enumerate(flow.steps, 1):
                                st.write(f"  {i}. {step['description']}")
                else:
                    st.warning("No flows discovered")
                
                # Show crawled elements
                with st.expander(f"📦 Crawled Elements ({len(elements)})"):
                    for e in elements[:50]:
                        st.write(f"• [{e.type.value}] {e.text[:50]} - {e.selector}")
                    if len(elements) > 50:
                        st.write(f"... and {len(elements) - 50} more")
    
    else:  # Manual Input
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Input: Site Elements")
            default_elements = """input[type=search]
button.search-submit
Login button
Sign in link
Add to Cart button
Buy Now button
filter-price
sort-dropdown
cart-icon
checkout-button
input[type=email]
input[type=password]"""
            elements_input = st.text_area(
                "Enter elements (one per line):",
                value=default_elements,
                height=250
            )
        
        with col2:
            st.subheader("Input: Site URLs")
            default_urls = """https://example.com/
https://example.com/login
https://example.com/search?q=laptop
https://example.com/product/123
https://example.com/cart
https://example.com/checkout"""
            urls_input = st.text_area(
                "Enter URLs (one per line):",
                value=default_urls,
                height=250
            )
        
        # Options
        col3, col4 = st.columns(2)
        with col3:
            include_partial = st.checkbox("Include partial flows (0.5-0.7 confidence)", value=True)
        with col4:
            confidence_threshold = st.slider("Confidence threshold", 0.3, 1.0, 0.7, 0.05)
        
        if st.button("🚀 Discover Flows", type="primary"):
            elements = [e.strip() for e in elements_input.strip().split('\n') if e.strip()]
            urls = [u.strip() for u in urls_input.strip().split('\n') if u.strip()]
            
            agent = FlowDiscoveryAgent()
            agent.CONFIDENCE_THRESHOLD = confidence_threshold
            
            with st.spinner("Discovering flows..."):
                result = agent.discover(elements, urls, include_partial=include_partial)
            
            # Stats
            st.subheader("📊 Results")
            col_a, col_b, col_c, col_d = st.columns(4)
            col_a.metric("Patterns Checked", result.stats["patterns_checked"])
            col_b.metric("Patterns Matched", result.stats["patterns_matched"])
            col_c.metric("Flows Discovered", result.stats["flows_discovered"])
            col_d.metric("Avg Confidence", f"{result.stats['average_confidence']:.2f}")
            
            # Flows
            if result.flows:
                st.subheader("🎯 Discovered Flows")
                for flow in result.flows:
                    status = "✅" if flow.flow_type == FlowType.HAPPY_PATH else "🟡"
                    with st.expander(f"{status} {flow.name} ({flow.flow_type.value}) - Confidence: {flow.confidence}"):
                        
                        # Evidence breakdown
                        st.markdown("**Evidence Scores:**")
                        evidence = flow.evidence
                        cols = st.columns(4)
                        cols[0].write(f"🧩 Elements: {evidence['element_score']}")
                        cols[1].write(f"🔗 URLs: {evidence['url_score']}")
                        cols[2].write(f"🤖 LLM: {evidence['llm_score']}")
                        cols[3].write(f"📚 Source: {evidence['pattern_source']}")
                        
                        # Steps
                        st.markdown("**Flow Steps:**")
                        for i, step in enumerate(flow.steps, 1):
                            st.write(f"  {i}. {step['description']}")
                        
                        # Matched elements
                        st.markdown("**Matched Elements:**")
                        st.write(", ".join(flow.elements) if flow.elements else "None")
                        
                        # Matched pages
                        st.markdown("**Matched Pages:**")
                        st.write(", ".join(flow.pages) if flow.pages else "None")
            else:
                st.warning("No flows discovered. Try lowering the confidence threshold or adding more elements.")
            
            # Debug: All pattern scores
            with st.expander("🔧 Debug: All Pattern Scores"):
                patterns = agent._get_all_patterns()
                for pid, pattern in patterns.items():
                    elem_score = agent._calculate_element_score(elements, pattern.get('elements', []))
                    url_score = agent._calculate_url_score(urls, pattern.get('urls', []))
                    confidence = agent._calculate_confidence(elem_score, url_score)
                    
                    color = "🟢" if confidence >= confidence_threshold else "🔴"
                    st.write(f"{color} **{pid}**: confidence={confidence:.2f} (elem={elem_score:.2f}, url={url_score:.2f})")
            
            # Show patterns.json
            with st.expander("📁 Current Patterns Database"):
                st.json(agent.patterns)

with tab2:
    st.header("🎲 Diversity Agent")
    st.info("Coming soon - will generate prompt variations from discovered flows")

with tab3:
    st.header("🧹 Dedupe Agent")
    st.info("Coming soon - will remove duplicate prompts using embeddings")

with tab4:
    st.header("⚖️ Judge Agent")
    st.info("Coming soon - will score and filter prompts")
