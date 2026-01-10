"""
Site Mapper CLI

Command-line interface for mapping websites using LLM orchestration.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orchestrator import map_website, Orchestrator
from models import SiteMap


def main():
    parser = argparse.ArgumentParser(
        description="LLM-Orchestrated Site Mapper - Discover all interactive elements on a website",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py map https://example.com
  python cli.py map https://zalando.de -o zalando_map.json --max-pages 50
  python cli.py map https://docs.python.org --headful
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Map command
    map_parser = subparsers.add_parser("map", help="Map a website")
    map_parser.add_argument("url", help="Website URL to map")
    map_parser.add_argument("-o", "--output", help="Output JSON file (default: site_map.json)")
    map_parser.add_argument("--max-pages", type=int, default=30, help="Maximum pages to explore (default: 30)")
    map_parser.add_argument("--headful", action="store_true", help="Run browser in visible mode")
    
    args = parser.parse_args()
    
    if args.command == "map":
        run_map(args)
    else:
        parser.print_help()


def run_map(args):
    """Run the site mapping command."""
    url = args.url
    output = args.output or "site_map.json"
    max_pages = args.max_pages
    headless = not args.headful
    
    print(f"🚀 LLM-Orchestrated Site Mapper")
    print(f"   URL: {url}")
    print(f"   Max pages: {max_pages}")
    print(f"   Output: {output}")
    print()
    
    def progress(msg: str):
        print(f"  {msg}")
    
    try:
        orchestrator = Orchestrator(max_pages=max_pages, headless=headless)
        site_map = orchestrator.map_site(url, progress_callback=progress)
        
        # Save output
        site_map.save(output)
        
        print()
        print(f"✅ Mapping complete!")
        print(f"   Pages crawled: {site_map.pages_crawled}")
        print(f"   Elements discovered: {site_map.elements_discovered}")
        print(f"   Output saved to: {output}")
        
        # Print element breakdown
        print()
        print("📊 Element Breakdown:")
        type_counts = {}
        for el in site_map.elements:
            t = el.type.value if hasattr(el.type, 'value') else str(el.type)
            type_counts[t] = type_counts.get(t, 0) + 1
        
        for el_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"   {el_type}: {count}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
