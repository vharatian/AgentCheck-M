import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from time import perf_counter

import requests
from dotenv import load_dotenv


# Number of parallel requests to send; change this value as needed.
NUM_REQUESTS = 200

logger = logging.getLogger(__name__)


def load_api_key(env_path: Path) -> str:
    """
    Load the Fireworks API key from a .env file.

    Expects a line like:
        FIREWORKS_API_KEY=your_key_here
    """
    logger.debug("Looking for .env file at %s", env_path)
    if env_path.is_file():
        logger.info("Loading environment variables from .env")
        load_dotenv(dotenv_path=env_path)
    else:
        logger.warning(".env file not found at %s; falling back to process env", env_path)

    api_key = os.getenv("FIREWORKS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "FIREWORKS_API_KEY not found in environment. "
            "Please add it to your .env file."
        )
    logger.info("Successfully loaded FIREWORKS_API_KEY")
    return api_key


def read_prompt(prompt_path: Path) -> str:
    logger.info("Reading prompt from %s", prompt_path)
    if not prompt_path.is_file():
        logger.error("Prompt file not found at %s", prompt_path)
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    text = prompt_path.read_text(encoding="utf-8")
    logger.info("Loaded prompt (%d characters)", len(text))
    return text


def call_fireworks(prompt: str, api_key: str) -> dict:
    url = "https://api.fireworks.ai/inference/v1/chat/completions"

    payload = {
        "model": "accounts/vahid-h-2e9ud19m5iz9/deployedModels/gpt-oss-120b-y0so8jfi",
        "max_tokens": 16384,
        "top_p": 1,
        "top_k": 40,
        "presence_penalty": 0,
        "frequency_penalty": 0,
        "temperature": 0.6,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    logger.info("Sending request to Fireworks API")
    logger.debug("Request URL: %s", url)
    response = requests.post(url, headers=headers, data=json.dumps(payload))
    logger.info("Received response with status code %s", response.status_code)
    response.raise_for_status()
    result = response.json()

    try:
        # Log a short preview of the first assistant message if present
        choices = result.get("choices") or []
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            preview = content[:120].replace("\n", " ")
            logger.info("First response message preview: %r%s", preview, "..." if len(content) > 120 else "")
        else:
            logger.warning("No choices found in Fireworks response")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to summarize Fireworks response for logging: %s", e)

    return result


def _run_single(index: int, prompt: str, api_key: str) -> tuple[float, dict]:
    logger.info("Starting Fireworks request %d", index)
    start = perf_counter()
    result = call_fireworks(prompt, api_key)
    elapsed = perf_counter() - start
    logger.info("Completed Fireworks request %d in %.3f seconds", index, elapsed)
    return elapsed, result


def main() -> None:
    project_root = Path(__file__).resolve().parent

    # Basic console logging setup
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting Fireworks prompt runner")

    num_requests = NUM_REQUESTS
    if num_requests <= 0:
        raise ValueError("NUM_REQUESTS must be a positive integer")
    logger.info("Configured to send %d parallel request(s)", num_requests)

    env_path = project_root / ".env"
    prompt_path = project_root / "prompt.md"

    api_key = load_api_key(env_path)
    prompt = read_prompt(prompt_path)

    logger.info("Calling Fireworks API in parallel...")
    overall_start = perf_counter()
    results: list[dict] = []
    durations: list[float] = []
    errors: list[tuple[int, Exception]] = []

    max_workers = num_requests
    logger.info("Using up to %d worker threads", max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(_run_single, i, prompt, api_key): i for i in range(num_requests)
        }

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                elapsed, result = future.result()
                durations.append(elapsed)
                results.append(result)
            except Exception as exc:  # noqa: BLE001
                logger.error("Request %d generated an exception: %s", idx, exc)
                errors.append((idx, exc))

    overall_total = perf_counter() - overall_start

    logger.info(
        "Finished all requests: %d success, %d error(s); wall-clock total time: %.3fs",
        len(results),
        len(errors),
        overall_total,
    )

    if durations:
        total_time = sum(durations)
        avg_time = total_time / len(durations)
        min_time = min(durations)
        max_time = max(durations)
        logger.info(
            "Per-request timing (successes only): avg=%.3fs, min=%.3fs, max=%.3fs, sum=%.3fs, wall-clock total=%.3fs",
            avg_time,
            min_time,
            max_time,
            total_time,
            overall_total,
        )

    if results:
        logger.info(
            "At least one successful response received; not printing full JSON payloads "
            "to avoid noisy output."
        )
    else:
        logger.warning("No successful responses were received")


if __name__ == "__main__":
    main()


