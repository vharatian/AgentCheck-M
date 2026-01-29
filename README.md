# AgentCheck-M

Tools for **prompt generation**, **site mapping**, and **browser-agent evaluation**—crawl sites, generate evaluation prompts, and run browser agents from natural-language instructions.

This repo keeps the **initial LLM-orchestrated site mapper** at the root and adds four project folders below.

---

## Initial code (root)

The **root directory** contains the original **LLM-Orchestrated Site Mapper**: Crawl4AI + Gemini to discover pages and interactive elements.

**How it works**

```
Crawl4AI (fetches page) → Gemini (analyzes + decides what to explore) → Repeat
```

**Setup**

```bash
# From repo root
python -m venv venv
source venv/bin/activate   # or venv\Scripts\activate on Windows
pip install -r requirements.txt
playwright install chromium
```

Create a `.env` in the repo root:

```
GEMINI_API_KEY=your_key_here
```

**Usage**

```bash
# From repo root
python cli.py map https://example.com
python cli.py map https://example.com -o map.json --max-pages 50
python cli.py map https://example.com --headful
```

**Output** (example)

```json
{
  "url": "https://example.com",
  "pages_crawled": 25,
  "elements_discovered": 342,
  "elements": [
    { "type": "button", "text": "Add to Cart", "selector": "[data-testid='add-cart']", "page_url": "/product/123" }
  ]
}
```

---

## Additional projects (subfolders)

| Folder | Description |
|--------|-------------|
| [**prompt_code**](./prompt_code/) | URL-based prompt generator: crawls a site and produces evaluation-style prompts (policy, pricing, support, docs, search) with evidence/constraint wording. |
| [**prompt_generator**](./prompt_generator/) | Hybrid prompt generator: Playwright + LLM (Gemini) to crawl sites and generate diverse, realistic browser-agent evaluation prompts with difficulty levels. |
| [**prompts**](./prompts/) | Browser agent abstraction: run a concrete browser agent from natural-language prompts, record execution, and use prompt templates. |
| [**site_mapper**](./site_mapper/) | Extended site mapper (agents, flow discovery, etc.). Use the root for the original minimal version; use this folder for the extended codebase. |

### prompt_code

```bash
cd prompt_code
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python main.py   # or: streamlit run app.py
```

### prompt_generator

```bash
cd prompt_generator
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt && playwright install chromium
# Set GEMINI_API_KEY in .env
streamlit run app.py
```

### prompts

```bash
cd prompts
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Chrome + ChromeDriver on PATH
python browser_agent.py
```

### site_mapper (extended)

```bash
cd site_mapper
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt && playwright install chromium
# Set GEMINI_API_KEY in .env
python cli.py map https://example.com
```

---

## License

See individual project folders for any license or attribution notes. Provided as-is for evaluation and experimentation.
