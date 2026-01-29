from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv  # type: ignore
import google.generativeai as genai  # type: ignore
from tqdm.auto import tqdm  # type: ignore

from prompts.prompt_templates import (  # type: ignore
    prompt_generation_prompt,
    usecase_specification_prompt,
    userflow_specification_prompt,
)


# =========================
# Configuration
# =========================

# Hardcoded website URL to analyze.
WEBSITE_URL = "https://en.zalando.de"

# For quick testing of the flow, keep these small (e.g. 2).
NUM_USE_CASES = 2
NUM_WORKFLOWS_PER_USE_CASE = 2
NUM_PATHS_PER_DIFFICULTY = 2  # set to 5 when you want full coverage

DIFFICULTY_LEVELS = ["trivial", "easy", "fair", "hard", "complex"]

MODEL_NAME = "gemini-pro-latest"

# Very rough, editable price estimates (USD per 1k tokens).
# Adjust these to match your actual Gemini pricing.
PRICE_PER_1K_INPUT_TOKENS = 0.0010
PRICE_PER_1K_OUTPUT_TOKENS = 0.0035


# =========================
# Gemini Client Wrapper
# =========================


@dataclass
class UsageTotals:
    prompt_tokens: int = 0
    candidates_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.candidates_tokens


class GeminiJsonClient:
    """Small helper around google.generativeai for JSON-only responses with retries."""

    def __init__(self, model_name: str = MODEL_NAME, max_retries: int = 3, retry_delay: float = 2.0) -> None:
        load_dotenv()
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set in the environment (.env).")

        genai.configure(api_key=api_key)

        self.model = genai.GenerativeModel(
            model_name,
            generation_config={"response_mime_type": "application/json"},
        )
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.usage = UsageTotals()

    def _update_usage(self, response: Any) -> None:
        metadata = getattr(response, "usage_metadata", None)
        if not metadata:
            return
        self.usage.prompt_tokens += getattr(metadata, "prompt_token_count", 0)
        self.usage.candidates_tokens += getattr(metadata, "candidates_token_count", 0)

    def _strip_code_fences(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            # Remove first fence line
            lines = text.splitlines()
            # Drop first and last line if they look like fences
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text

    def generate_json(self, prompt: str) -> Dict[str, Any]:
        """Call the model with simple text prompt and parse JSON response."""
        last_err: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.model.generate_content(prompt)
                self._update_usage(response)
                raw_text = getattr(response, "text", "") or ""
                cleaned = self._strip_code_fences(raw_text)
                return json.loads(cleaned)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_delay * attempt)
        if last_err:
            raise last_err
        raise RuntimeError("Unexpected error in generate_json")


def ensure_run_directory() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path("out") / "run" / ts
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def estimate_cost(usage: UsageTotals) -> float:
    input_cost = (usage.prompt_tokens / 1000.0) * PRICE_PER_1K_INPUT_TOKENS
    output_cost = (usage.candidates_tokens / 1000.0) * PRICE_PER_1K_OUTPUT_TOKENS
    return input_cost + output_cost


def main() -> None:
    client = GeminiJsonClient()
    run_dir = ensure_run_directory()

    # ---- Usecase Specification: Website overview + use cases ----
    print("=== Stage 1: Usecase Specification ===")
    print(f"Analyzing website: {WEBSITE_URL}")

    usecase_prompt = usecase_specification_prompt(WEBSITE_URL, NUM_USE_CASES)
    usecase_spec_json = client.generate_json(usecase_prompt)
    website_description = usecase_spec_json.get("website_description", "")
    use_cases: List[Dict[str, Any]] = usecase_spec_json.get("use_cases", [])

    (run_dir / "01_usecase_specification.json").write_text(
        json.dumps(usecase_spec_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---- Userflow Specification: Workflows per use case ----
    print("=== Stage 2: Userflow Specification ===")
    print(f"Number of use cases: {len(use_cases)} (target: {NUM_USE_CASES})")

    userflow_specs_per_use_case: List[Dict[str, Any]] = []
    for idx, uc in enumerate(tqdm(use_cases, desc="Use cases"), start=1):
        userflow_prompt = userflow_specification_prompt(website_description, uc, NUM_WORKFLOWS_PER_USE_CASE)
        userflow_spec_json = client.generate_json(userflow_prompt)

        filename = run_dir / f"02_usecase_{idx:02d}_userflow_specification.json"
        filename.write_text(
            json.dumps(userflow_spec_json, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        userflow_specs_per_use_case.append(userflow_spec_json)

    # ---- Prompt Generation: Concrete paths per workflow & CSV creation ----
    print("=== Stage 3: Prompt Generation ===")
    csv_path = run_dir / "prompts.csv"
    rows: List[List[str]] = []

    for uc_idx, uc_with_flows in enumerate(
        tqdm(userflow_specs_per_use_case, desc="Use cases (prompt generation)"),
        start=1,
    ):
        uc_title = uc_with_flows.get("use_case_title") or ""
        workflows: List[Dict[str, Any]] = uc_with_flows.get("workflows", [])

        for wf_idx, wf in enumerate(
            tqdm(workflows, desc=f"Workflows for use case {uc_idx}", leave=False),
            start=1,
        ):
            generation_prompt = prompt_generation_prompt(
                website_url=WEBSITE_URL,
                website_description=website_description,
                use_case_title=uc_title,
                workflow=wf,
                difficulty_levels=DIFFICULTY_LEVELS,
                num_paths_per_difficulty=NUM_PATHS_PER_DIFFICULTY,
            )
            prompt_gen_json = client.generate_json(generation_prompt)

            filename = run_dir / f"03_usecase_{uc_idx:02d}_workflow_{wf_idx:02d}_prompt_generation.json"
            filename.write_text(
                json.dumps(prompt_gen_json, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            paths: List[Dict[str, Any]] = prompt_gen_json.get("paths", [])
            for p in paths:
                difficulty = str(p.get("difficulty", "")).lower()
                prompt_text = p.get("prompt", "")
                requires_credentials = bool(p.get("requires_credentials", False))

                # Each CSV row: use_case_title, userflow_title, difficulty, prompt, requires_credentials
                rows.append(
                    [
                        uc_title,
                        prompt_gen_json.get("workflow_title", "") or wf.get("title", ""),
                        difficulty,
                        prompt_text,
                        str(requires_credentials).lower(),
                    ]
                )

    # Write CSV at the end
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "use_case_title",
                "workflow_title",
                "difficulty",
                "prompt",
                "requires_credentials",
            ]
        )
        writer.writerows(rows)

    # ---- Print token usage and rough cost ----
    print("=== Run Summary ===")
    print("Total prompt tokens:", client.usage.prompt_tokens)
    print("Total candidate tokens:", client.usage.candidates_tokens)
    print("Total tokens:", client.usage.total_tokens)
    print("Estimated cost (USD):", round(estimate_cost(client.usage), 6))
    print("Run directory:", run_dir.resolve())
    print("CSV file:", csv_path.resolve())


if __name__ == "__main__":
    main()


