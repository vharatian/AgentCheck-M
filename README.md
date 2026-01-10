# LLM-Orchestrated Site Mapper

Maps websites using **Gemini + Crawl4AI** to discover all interactive elements.

## How It Works

```
Crawl4AI (fetches page) → Gemini (analyzes + decides what to explore) → Repeat
```

## Setup

```bash
cd site_mapper
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
# Basic usage
python cli.py map https://example.com

# With options
python cli.py map https://zalando.de -o zalando_map.json --max-pages 50

# Visible browser (for debugging)
python cli.py map https://example.com --headful
```

## Output

The output is a JSON file with:

```json
{
  "url": "https://example.com",
  "pages_crawled": 25,
  "elements_discovered": 342,
  "elements": [
    {
      "type": "button",
      "text": "Add to Cart",
      "selector": "[data-testid='add-cart']",
      "page_url": "/product/123"
    }
  ]
}
```

## Configuration

Set your Gemini API key in `.env`:
```
GEMINI_API_KEY=your_key_here
```
