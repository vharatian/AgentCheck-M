from __future__ import annotations

from typing import Any, Dict, List


def usecase_specification_prompt(website_url: str, num_use_cases: int) -> str:
    return f"""
You are an expert product analyst. Think step by step before answering.

First, silently reason about the website's main purpose and target users.
Then, based on that reasoning, produce ONLY the final JSON described below (do not include your reasoning).

Website URL: "{website_url}"

Your goals:
1) Provide a concise, factual overall description of what this website is about (1–3 sentences).
   - Mention the primary domain (e.g. travel booking, e‑commerce, productivity, content).
   - Mention the main types of users and what they try to accomplish.
2) Identify the {num_use_cases} most important, high-level user use cases.
   - Each use case should describe a distinct type of task users regularly perform on this site.
   - Keep them high-level but concrete (e.g. "Catalogue browsing", "Product search and discovery", "Booking and checkout").
   - Avoid implementation details or UI-specific wording (no button names, exact labels, or step sequences).

Quality criteria for each use case:
- "title": short, 3–7 words, clear and human-readable.
- "description": 1–3 sentences, covering:
  - What the user is trying to achieve.
  - Why they would use this website for that.
  - Any key constraints (e.g. logged-in vs guest, typical user mindset).

Return ONLY a valid JSON object with this exact structure and no other text:
{{
  "website_description": "string",
  "use_cases": [
    {{
      "id": 1,
      "title": "string",
      "description": "string"
    }}
  ]
}}

Rules:
- Ensure there are exactly {num_use_cases} items in "use_cases".
- Do not include any fields other than the ones specified.
- Do not include explanations, comments, or markdown; output must be raw JSON.
"""


def userflow_specification_prompt(website_description: str, use_case: Dict[str, Any], num_workflows: int) -> str:
    title = use_case.get("title", "")
    description = use_case.get("description", "")

    return f"""
You are an expert UX designer. Think step by step about how users practically use this feature area.

First, reason internally about the main sub-tasks users perform within this use case.
Then, based on that reasoning, output ONLY the final JSON described below (do not include your reasoning).

Website description:
\"\"\"{website_description}\"\"\"

Use case:
Title: {title}
Description: {description}

Task:
- Propose {num_workflows} common user workflows under this specific use case.
- Each workflow is a reusable pattern of behavior (e.g. "Browse categories and subcategories to discover products").
- The workflows should be:
  - Abstract and generic (applicable to many concrete paths).
  - Independent from specific UI labels, exact filters, or particular item examples.

Things to avoid:
- Overly specific flows like "searching for a specific type of product with three filters X, Y, Z".
- Mentioning exact product names, brand names, dates, or arbitrary numbers unless they are essential to describe the pattern.

Quality criteria for each workflow:
- "title": short, 3–9 words, describing the pattern.
- "description": 1–3 sentences, covering:
  - What the user is trying to do.
  - The general sequence or strategy (at a conceptual level).
  - Any relevant preconditions (e.g. having an account, having items in cart).

Return ONLY a valid JSON object with this exact structure and no other text:
{{
  "use_case_title": "string",
  "use_case_description": "string",
  "workflows": [
    {{
      "id": 1,
      "title": "string",
      "description": "string"
    }}
  ]
}}

Rules:
- Ensure there are exactly {num_workflows} items in "workflows".
- Do not include any fields other than the ones specified.
- Do not include explanations, comments, or markdown; output must be raw JSON.
"""


def prompt_generation_prompt(
    website_url: str,
    website_description: str,
    use_case_title: str,
    workflow: Dict[str, Any],
    difficulty_levels: List[str],
    num_paths_per_difficulty: int,
) -> str:
    workflow_title = workflow.get("title", "")
    workflow_description = workflow.get("description", "")
    difficulties_str = ", ".join(f'"{d}"' for d in difficulty_levels)

    return f"""
You are an expert prompt engineer for browser automation agents. Think step by step before writing the final prompts.

First, reason internally about:
- What realistic tasks users would perform on this website for this workflow.
- How to turn those tasks into clear, executable, single-goal prompts for an automation agent.
- How to vary difficulty levels while keeping each prompt realistic and testable.

Then, based on that reasoning, output ONLY the final JSON described below (do not include your reasoning).

Website:
URL: {website_url}
Description:
\"\"\"{website_description}\"\"\"

Use case title:
\"\"\"{use_case_title}\"\"\"

User workflow:
Title: {workflow_title}
Description: {workflow_description}

Task:
- For each difficulty level in [{difficulties_str}], generate {num_paths_per_difficulty} concrete user paths (prompts) that a browser agent can execute on this website.
- Each path must be a high-quality natural-language prompt for an agent, describing:
  - A single, well-defined user goal on the website.
  - Any necessary constraints (e.g. price ranges, dates, locations, ratings, categories).
  - When needed, what to compare, select, or prepare (e.g. "then add to cart", "then proceed to checkout page").
- The prompts must:
  - ALWAYS start with: "Open {website_url} and ..."
  - NOT assume any pre-existing state or navigation (the agent only starts from opening the website).
  - NOT say things like "on the final step", "resume from where you left off", or "continue from the previous page".
  - Be specific enough that there is no ambiguity about what success looks like.
  - Be feasible for a generic browsing agent (no internal APIs or developer tools).
  - Be written as direct instructions in the second person, starting with an imperative verb after "Open {website_url} and ...".
- CRITICAL: Transaction safety rules:
  - Prompts can go through the entire booking/checkout/purchase flow (browsing, selecting, adding to cart, filling forms, reviewing).
  - However, prompts MUST stop before finalizing any transaction that would:
    - Complete a purchase and charge a payment method.
    - Confirm a reservation that commits the user to payment.
    - Submit an order that cannot be easily cancelled.
  - Instead, prompts should end at the final review/confirmation page, or instruct to "proceed to the payment page" or "review the order summary" without clicking final confirmation buttons.
  - Examples of acceptable endings: "add to cart and proceed to checkout", "fill in booking details and review the reservation summary", "select items and review the order".
  - Examples to AVOID: "complete the purchase", "confirm the booking", "finalize the order", "submit payment", "place the order".

Difficulty guidelines:
- "trivial": 1–2 simple steps, no complex filters, no comparisons.
- "easy": a few steps, possibly one simple filter or constraint.
- "fair": multiple steps, combinations of filters or conditions, but still linear.
- "hard": longer flows with several conditions, comparisons, or back-and-forth navigation.
- "complex": multi-step scenarios combining several features (search, filters, comparison, booking/checkout preparation, account actions, etc.). Note: checkout flows should stop at review/confirmation pages, not finalize transactions.

Return ONLY a valid JSON object with this exact structure and no other text:
{{
  "use_case_title": "string",
  "workflow_title": "string",
  "website_description": "string",
  "paths": [
    {{
      "difficulty": "trivial | easy | fair | hard | complex",
      "title": "short human-readable title",
      "prompt": "concrete natural-language instruction for a browser agent, starting with: Open {website_url} and ...",
      "requires_credentials": true
    }}
  ]
}}

Rules:
- The "paths" array must contain exactly {len(difficulty_levels) * num_paths_per_difficulty} items.
- For each difficulty level, include exactly {num_paths_per_difficulty} items with that difficulty.
- Prompts must be mutually distinct and not trivial rephrasings of each other.
- Do not include explanations, comments, or markdown; output must be raw JSON.
"""



