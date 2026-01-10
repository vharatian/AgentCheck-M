"""
LLM Prompts for Site Exploration

Prompts that instruct Gemini how to explore and understand websites.
"""

# System prompt for the orchestrator
ORCHESTRATOR_SYSTEM = """You are an expert website analyzer. Your job is to explore websites thoroughly and discover all interactive elements.

Given the current page content (in markdown), you will:
1. Identify all interactive elements (buttons, links, forms, menus, etc.)
2. Suggest actions to discover more content
3. Prioritize unexplored areas

RULES:
- NEVER suggest clicking checkout, payment, or delete buttons
- Focus on navigation, product browsing, search, filters
- Identify menus that might expand when clicked
- Look for hidden content (dropdowns, accordions)
"""


def plan_exploration_prompt(page_markdown: str, page_url: str, visited_urls: list, discovered_elements: int) -> str:
    """Generate prompt for LLM to plan next exploration actions."""
    visited_str = "\n".join(f"  - {url}" for url in visited_urls[-10:])
    
    return f"""{ORCHESTRATOR_SYSTEM}

## Current Page
URL: {page_url}

## Page Content (Markdown)
{page_markdown[:8000]}

## Exploration Status
- Pages visited: {len(visited_urls)}
- Elements discovered so far: {discovered_elements}
- Recent pages:
{visited_str}

## Your Task
Analyze this page and return a JSON response with:

1. **elements**: List of interactive elements you found on this page
2. **actions**: List of actions to explore more (click menu, expand dropdown, etc.)
3. **links_to_visit**: Important internal links to visit next

## Response Format (JSON only)
```json
{{
  "elements": [
    {{
      "type": "button|link|input|select|dropdown|menu|form|filter|search|other",
      "text": "visible text",
      "purpose": "what it does (add_to_cart, navigate, filter, etc.)",
      "selector_hint": "CSS selector or description"
    }}
  ],
  "actions": [
    {{
      "type": "click|hover",
      "target": "element description",
      "reason": "why this action will reveal more content"
    }}
  ],
  "links_to_visit": [
    {{
      "url": "relative or absolute URL",
      "reason": "why this page is important to explore"
    }}
  ],
  "page_summary": "Brief description of what this page contains"
}}
```

Respond with ONLY the JSON, no other text.
"""


def analyze_elements_prompt(html_snippet: str, page_url: str) -> str:
    """Prompt to deeply analyze HTML elements."""
    return f"""Analyze these HTML elements and categorize them.

## Page URL
{page_url}

## HTML Snippet
{html_snippet[:5000]}

## Your Task
Extract all interactive elements with their details.

## Response Format (JSON only)
```json
{{
  "elements": [
    {{
      "type": "button|link|input|select|checkbox|radio|dropdown|menu|form",
      "text": "visible text or aria-label",
      "selector": "CSS selector",
      "attributes": {{"data-testid": "...", "class": "..."}},
      "input_type": "text|email|password|number (for inputs)",
      "options": ["option1", "option2"] // for selects
    }}
  ]
}}
```

Respond with ONLY the JSON.
"""


def classify_action_result_prompt(before_state: str, after_state: str, action_taken: str) -> str:
    """Prompt to classify what happened after an action."""
    return f"""You executed an action on a webpage. Analyze what changed.

## Action Taken
{action_taken}

## Page State BEFORE
{before_state[:2000]}

## Page State AFTER
{after_state[:2000]}

## Your Task
Determine what the action did.

## Response Format (JSON only)
```json
{{
  "result_type": "navigation|modal_opened|dropdown_expanded|content_changed|form_submitted|cart_updated|filter_applied|error_shown|no_change",
  "description": "What specifically changed",
  "new_elements_visible": ["list of new elements that appeared"],
  "url_changed": true/false,
  "new_url": "URL if changed"
}}
```

Respond with ONLY the JSON.
"""


def generate_prompts_from_elements_prompt(elements: list, site_url: str, site_type: str) -> str:
    """Prompt to generate test prompts from discovered elements."""
    elements_str = "\n".join([
        f"- {e.get('type', 'unknown')}: {e.get('text', 'no text')} ({e.get('purpose', 'unknown purpose')})"
        for e in elements[:50]
    ])
    
    return f"""You have mapped a website and discovered its interactive elements.
Now generate comprehensive test prompts to evaluate a browser agent.

## Website
URL: {site_url}
Type: {site_type}

## Discovered Elements
{elements_str}

## Your Task
Generate diverse prompts that test ALL these elements across different:
- Difficulty levels (trivial, easy, medium, hard, complex)
- Prompt styles (direct, vague, multi-step)
- User personas (tech-savvy, beginner, specific needs)

## Response Format (JSON only)
```json
{{
  "prompts": [
    {{
      "prompt": "The natural language instruction",
      "difficulty": "trivial|easy|medium|hard|complex",
      "elements_tested": ["element1", "element2"],
      "expected_actions": ["what the agent should do"]
    }}
  ]
}}
```

Generate at least 20 prompts covering different elements.
Respond with ONLY the JSON.
"""
