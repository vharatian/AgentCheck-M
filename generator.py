"""
Prompt Generator with Strict Difficulty Filtering

Only generates prompts for selected difficulty levels.
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from models import SiteMap, Element
from llm_client import LLMClient


DEFAULT_MODEL = "google/gemini-3-flash-preview"

DIFFICULTY_LEVELS = {
    "L1": "Simple",
    "L2": "Easy", 
    "L3": "Medium",
    "L4": "Hard",
    "L5": "Expert",
}

WORD_COUNTS = {
    "L1": "5-10 words",
    "L2": "10-20 words",
    "L3": "20-30 words",
    "L4": "40-50 words",
    "L5": "60-70+ words",
}


@dataclass
class GeneratedPrompt:
    prompt: str
    difficulty: str
    difficulty_label: str
    elements_tested: List[str]
    expected_actions: List[str]
    category: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt": self.prompt,
            "difficulty": self.difficulty,
            "difficulty_label": self.difficulty_label,
            "elements_tested": self.elements_tested,
            "expected_actions": self.expected_actions,
            "category": self.category,
            "word_count": len(self.prompt.split())
        }


class PromptGenerator:
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        self.llm = LLMClient(api_key=api_key, model=model)
    
    def generate_prompts(
        self,
        site_map: SiteMap,
        prompts_per_difficulty: int = 5,
        difficulties: List[str] = None,
        progress_callback=None
    ) -> List[GeneratedPrompt]:
        if difficulties is None:
            difficulties = list(DIFFICULTY_LEVELS.keys())
        
        def log(msg: str):
            if progress_callback:
                progress_callback(msg)
        
        total_expected = len(difficulties) * prompts_per_difficulty
        log(f"Building element summary...")
        element_summary = self._summarize_elements(site_map.elements)
        
        log(f"Generating: {difficulties} x {prompts_per_difficulty} = {total_expected} prompts")
        
        prompt = self._build_generation_prompt(
            url=site_map.url,
            domain=site_map.domain,
            element_summary=element_summary,
            difficulties=difficulties,
            prompts_per_difficulty=prompts_per_difficulty,
            pages=site_map.pages
        )
        
        try:
            result = self.llm.generate_json(prompt)
            
            prompts = []
            for p in result.get("prompts", []):
                diff = p.get("difficulty", "L3")
                
                # FILTER: Only include prompts with selected difficulty
                if diff not in difficulties:
                    continue
                
                prompts.append(GeneratedPrompt(
                    prompt=p.get("prompt", ""),
                    difficulty=diff,
                    difficulty_label=DIFFICULTY_LEVELS.get(diff, "Medium"),
                    elements_tested=p.get("elements_tested", []),
                    expected_actions=p.get("expected_actions", []),
                    category=p.get("category", "general")
                ))
            
            log(f"✓ Generated {len(prompts)} prompts (expected {total_expected})")
            return prompts
            
        except Exception as e:
            log(f"Error: {e}")
            return []
    
    def _summarize_elements(self, elements: List[Element]) -> str:
        by_type = {}
        for el in elements:
            t = el.type.value if hasattr(el.type, 'value') else str(el.type)
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(el)
        
        lines = []
        for el_type, els in sorted(by_type.items()):
            lines.append(f"\n### {el_type.upper()} ({len(els)})")
            for el in els[:15]:
                text = el.text[:80] if el.text else "(no text)"
                lines.append(f"- {text}")
            if len(els) > 15:
                lines.append(f"  ... +{len(els) - 15} more")
        
        return "\n".join(lines)
    
    def _build_generation_prompt(
        self,
        url: str,
        domain: str,
        element_summary: str,
        difficulties: List[str],
        prompts_per_difficulty: int,
        pages: List[str]
    ) -> str:
        pages_str = "\n".join(f"- {p}" for p in pages[:15])
        
        # Build level-specific instructions
        level_instructions = []
        for d in difficulties:
            label = DIFFICULTY_LEVELS.get(d, "")
            words = WORD_COUNTS.get(d, "")
            level_instructions.append(f"- {d} ({label}): {prompts_per_difficulty} prompts, {words}")
        
        levels_str = "\n".join(level_instructions)
        total = len(difficulties) * prompts_per_difficulty
        
        return f"""Generate browser agent test prompts.

## Website
URL: {url}
Domain: {domain}

## Pages
{pages_str}

## Elements
{element_summary}

## EXACT REQUIREMENTS - READ CAREFULLY!

Generate EXACTLY these prompts:

{levels_str}

TOTAL: {total} prompts

## Word Count Rules

| Level | Word Count |
|-------|------------|
| L1 Simple | 5-10 words |
| L2 Easy | 10-20 words |
| L3 Medium | 20-30 words |
| L4 Hard | 40-50 words |
| L5 Expert | 60-70+ words |

## Style

Write as a REAL human would type - natural, conversational:
- "what's on sale?"
- "need running shoes under $80"
- "show me laptops with 16gb ram"

## JSON Response

ONLY generate prompts for these levels: {difficulties}
DO NOT generate prompts for any other levels!

```json
{{
  "prompts": [
    {{
      "prompt": "natural text",
      "difficulty": "{difficulties[0]}",
      "elements_tested": ["element"],
      "expected_actions": ["action"],
      "category": "search|navigation|filter|product|form"
    }}
  ]
}}
```

ONLY levels {difficulties} - nothing else!
Total: {total} prompts

JSON:
"""


def generate_prompts_from_sitemap(site_map, api_key=None, prompts_per_difficulty=5, progress_callback=None):
    return PromptGenerator(api_key).generate_prompts(site_map, prompts_per_difficulty, progress_callback=progress_callback)


def generate_prompts_url_only(
    url: str,
    api_key: str = None,
    prompts_per_difficulty: int = 5,
    difficulties: List[str] = None,
    progress_callback=None,
    model: str = DEFAULT_MODEL
) -> List[GeneratedPrompt]:
    """
    Generate prompts based ONLY on URL/domain - no crawling.
    Uses LLM to infer website type and generate appropriate prompts.
    """
    if difficulties is None:
        difficulties = list(DIFFICULTY_LEVELS.keys())
    
    def log(msg: str):
        if progress_callback:
            progress_callback(msg)
    
    from urllib.parse import urlparse
    import tldextract
    
    parsed = urlparse(url if url.startswith("http") else f"https://{url}")
    ext = tldextract.extract(url)
    domain = f"{ext.domain}.{ext.suffix}"
    
    # Build level instructions
    level_instructions = []
    for d in difficulties:
        label = DIFFICULTY_LEVELS.get(d, "")
        words = WORD_COUNTS.get(d, "")
        level_instructions.append(f"- {d} ({label}): {prompts_per_difficulty} prompts, {words}")
    
    levels_str = "\n".join(level_instructions)
    total = len(difficulties) * prompts_per_difficulty
    
    log(f"Generating {total} prompts for {domain} (URL-only mode)...")
    
    prompt = f"""Generate browser agent test prompts for a website.

## Website
URL: {url}
Domain: {domain}

## TASK: Infer Website Type

Based on the URL and domain, infer what type of website this is:
- E-commerce (amazon, ebay, zalando, etc.)
- Search engine (google, bing)
- Social media (facebook, twitter/x, instagram)
- Video streaming (youtube, netflix)
- News/Media
- Travel/Booking (booking.com, airbnb)
- Food delivery (uber eats, doordash)
- Banking/Finance
- Other

Then generate realistic prompts that a human would ask a browser agent for this type of site.

## EXACT REQUIREMENTS

Generate EXACTLY these prompts:

{levels_str}

TOTAL: {total} prompts

## Word Count Rules

| Level | Word Count |
|-------|------------|
| L1 Simple | 5-10 words |
| L2 Easy | 10-20 words |
| L3 Medium | 20-30 words |
| L4 Hard | 40-50 words |
| L5 Expert | 60-70+ words |

## Style

Write as a REAL human would type - natural, conversational:
- "what's on sale?"
- "need running shoes under $80"
- "show me laptops with 16gb ram"

## JSON Response

ONLY generate prompts for these levels: {difficulties}

```json
{{
  "inferred_type": "e-commerce|search|social|video|news|travel|food|banking|other",
  "prompts": [
    {{
      "prompt": "natural text",
      "difficulty": "{difficulties[0]}",
      "elements_tested": ["inferred element"],
      "expected_actions": ["action"],
      "category": "search|navigation|filter|product|form"
    }}
  ]
}}
```

JSON:
"""
    
    try:
        llm = LLMClient(api_key=api_key, model=model)
        result = llm.generate_json(prompt)
        
        inferred_type = result.get("inferred_type", "unknown")
        log(f"Inferred website type: {inferred_type}")
        
        prompts = []
        for p in result.get("prompts", []):
            diff = p.get("difficulty", "L3")
            
            if diff not in difficulties:
                continue
            
            prompts.append(GeneratedPrompt(
                prompt=p.get("prompt", ""),
                difficulty=diff,
                difficulty_label=DIFFICULTY_LEVELS.get(diff, "Medium"),
                elements_tested=p.get("elements_tested", []),
                expected_actions=p.get("expected_actions", []),
                category=p.get("category", "general")
            ))
        
        log(f"✓ Generated {len(prompts)} prompts (URL-only mode)")
        return prompts
        
    except Exception as e:
        log(f"Error: {e}")
        return []
