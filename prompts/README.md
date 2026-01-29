## Browser Agent Abstraction (Python)

This workspace contains a minimal abstract browser agent and a concrete `BrowserUseAdapter`
implementation that opens a website based on a natural-language prompt and records a
video of the execution.

### Files

- **`browser_agent.py`**: Contains
  - `BrowserAgent` (abstract base class)
  - `BrowserTaskResult` (result dataclass)
  - `ScreenRecorder` (simple full-screen recorder using `mss` + OpenCV)
  - `BrowserUseAdapter` (concrete implementation using Selenium Chrome)
  - `main()` function to run a sample prompt
- **`requirements.txt`**: Python dependencies.

### Setup

Create and activate a virtual environment if desired, then install dependencies:

```bash
cd /home/vahid/Desktop/AgentCheck
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You also need:

- Google Chrome or another Chromium-based browser
- A matching ChromeDriver (for Selenium) available on your `PATH`

### Running the sample browser agent

`browser_agent.py` already has a `main()` function wired up. Run:

```bash
python browser_agent.py
```

By default it will:

- Use `BrowserUseAdapter` to interpret the prompt:
  - `open https://example.com and wait 5 seconds`
- Open Chrome and navigate to that URL
- Wait 5 seconds
- Record the whole screen during execution
- Save a video in the `./recordings` folder (created automatically)

### Adapting the abstraction

- To add other adapters (e.g., different browsers or automation stacks), subclass
  `BrowserAgent` and implement `run(self, prompt: str) -> BrowserTaskResult`.
- Reuse `ScreenRecorder` or plug in your own recording solution as needed.


