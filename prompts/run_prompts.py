from __future__ import annotations

"""
Script to run browser agent for each prompt in a CSV file.

This script:
1. Reads prompts from a CSV file (typically in out/run/TIMESTAMP/prompts.csv)
2. Runs the browser agent for each prompt (with option to skip credential-required prompts)
3. Records results including the output folder name
4. Creates a new CSV with all original columns plus output folder and execution results

Usage:
    python run_prompts.py
"""

import asyncio
import csv
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from dotenv import load_dotenv
from tqdm.auto import tqdm

from browser_agent import BrowserUseAdapter, BrowserTaskResult

# =========================
# Configuration (hardcoded)
# =========================

# Path to the input CSV file with prompts
CSV_PATH = Path("out/run/20251203_163315/prompts.csv")

# Base directory where agent outputs will be saved
OUTPUT_BASE_DIR = Path("out/run/20251203_163315/recordings/")

# Enable execution of prompts that require credentials
ENABLE_CREDENTIALS = False

# Difficulty levels to execute (empty list = all difficulties)
# Available levels: "trivial", "easy", "fair", "hard", "complex"
# ALLOWED_DIFFICULTIES = ["trivial", "easy", "fair", "hard", "complex"]  # Set to [] to run all
ALLOWED_DIFFICULTIES = ["fair", "hard"]  # Set to [] to run all

# Path to save the results CSV (None = next to input CSV with _results suffix)
OUTPUT_CSV_PATH = Path("out/run/20251203_163315/prompts_recordings.csv")

# Timeout in seconds for each task (None = no timeout)
TASK_TIMEOUT = 120  # 2 minutes


def read_prompts_csv(csv_path: Path) -> List[Dict[str, str]]:
    """Read prompts from CSV file and return as list of dictionaries."""
    prompts = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            prompts.append(row)
    return prompts


def should_execute_prompt(
    prompt_row: Dict[str, str], 
    enable_credentials: bool, 
    allowed_difficulties: List[str]
) -> Tuple[bool, str]:
    """
    Determine if a prompt should be executed based on credentials flag and difficulty level.
    
    Returns:
        Tuple of (should_execute, skip_reason)
        skip_reason is empty string if should_execute is True
    """
    # Check credentials requirement
    requires_creds = prompt_row.get("requires_credentials", "false").lower() == "true"
    if requires_creds and not enable_credentials:
        return False, "requires credentials"
    
    # Check difficulty level
    if allowed_difficulties:  # If list is not empty, filter by difficulty
        difficulty = prompt_row.get("difficulty", "").lower().strip()
        if difficulty not in [d.lower() for d in allowed_difficulties]:
            return False, f"difficulty '{difficulty}' not in allowed list"
    
    return True, ""


def extract_output_folder(result: BrowserTaskResult) -> str:
    """Extract the output folder name from the result's video_path."""
    # The video_path is either a file or a directory
    # If it's a file, get its parent directory
    # If it's a directory, use it directly
    path = Path(result.video_path)
    if path.is_file():
        folder = path.parent
    else:
        folder = path
    
    # Return just the folder name (timestamp), not the full path
    return folder.name


def run_agent_with_timeout(
    adapter: BrowserUseAdapter, 
    prompt: str, 
    timeout: Optional[float] = None
) -> BrowserTaskResult:
    """
    Run the browser agent with a timeout.
    
    If timeout occurs, the agent is stopped but recordings and steps are still captured.
    
    Args:
        adapter: BrowserUseAdapter instance
        prompt: Prompt to execute
        timeout: Timeout in seconds (None = no timeout)
    
    Returns:
        BrowserTaskResult with success=False if timeout occurred
    """
    if timeout is None:
        # No timeout, just run normally
        return adapter.run(prompt)
    
    # Run with timeout by accessing the async method directly
    async def run_with_timeout():
        # Get the timestamp before starting to help identify the run directory
        from datetime import datetime
        start_time = datetime.now()
        expected_ts = start_time.strftime("%Y%m%d_%H%M%S")
        
        try:
            # Pass timeout to _run_async so it can handle it internally
            # and extract steps from the agent object
            result = await adapter._run_async(prompt, timeout=timeout)
            return result
        except asyncio.TimeoutError as timeout_exc:
            # The _run_async should have handled this and extracted steps,
            # but if it didn't, we'll try to find the result file
            # Timeout occurred - try to find the run directory that was created
            # The finally block in _run_async should have run, but we need to
            # find the directory and create a proper result
            
            # Wait a moment for cleanup to complete
            await asyncio.sleep(0.5)
            
            # Find the most recently created/modified directory
            run_dir = None
            if adapter.video_output_dir.exists():
                # Look for directories matching the expected timestamp pattern
                dirs = [
                    d for d in adapter.video_output_dir.iterdir()
                    if d.is_dir() and d.name.startswith(expected_ts[:8])  # Match date part
                ]
                if dirs:
                    # Get the most recently modified directory
                    run_dir = max(dirs, key=lambda d: d.stat().st_mtime)
            
            # If we found a directory, check for recordings
            if run_dir and run_dir.exists():
                artefact_path = run_dir / "result.txt"
                timeout_message = f"Task timed out after {timeout} seconds. Partial execution recorded."
                
                # Check if result file already has content (from _run_async)
                existing_content = ""
                if artefact_path.exists():
                    existing_content = artefact_path.read_text(encoding="utf-8")
                
                # Only append if it doesn't already contain timeout message
                if existing_content and "timed out" not in existing_content.lower():
                    artefact_path.write_text(
                        f"{existing_content}\n\n{timeout_message}",
                        encoding="utf-8"
                    )
                elif not existing_content:
                    artefact_path.write_text(timeout_message, encoding="utf-8")
                
                # Look for video file
                candidates = sorted(
                    [p for p in run_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}],
                    key=lambda p: p.stat().st_mtime,
                )
                video_path = candidates[-1] if candidates else artefact_path
                
                return BrowserTaskResult(
                    success=False,
                    message=timeout_message,
                    video_path=video_path,
                )
            else:
                # Fallback: create a directory and save timeout message
                run_dir = adapter.video_output_dir / expected_ts
                run_dir.mkdir(parents=True, exist_ok=True)
                artefact_path = run_dir / "result.txt"
                timeout_message = f"Task timed out after {timeout} seconds. Limited recordings captured."
                artefact_path.write_text(timeout_message, encoding="utf-8")
                
                return BrowserTaskResult(
                    success=False,
                    message=timeout_message,
                    video_path=artefact_path,
                )
    
    # Run the async function
    return asyncio.run(run_with_timeout())


def run_prompts(
    csv_path: Path,
    output_base_dir: Path,
    enable_credentials: bool = False,
    allowed_difficulties: List[str] | None = None,
    task_timeout: Optional[float] = None,
    output_csv_path: Path | None = None,
) -> None:
    """
    Run browser agent for each prompt in the CSV and save results.
    
    Args:
        csv_path: Path to the input CSV file with prompts
        output_base_dir: Base directory where agent outputs will be saved
        enable_credentials: If True, execute prompts that require credentials
        allowed_difficulties: List of difficulty levels to execute (empty list = all)
        task_timeout: Timeout in seconds for each task (None = no timeout)
        output_csv_path: Path to save the results CSV. If None, saves next to input CSV.
    """
    load_dotenv()
    
    if allowed_difficulties is None:
        allowed_difficulties = []
    
    # Read prompts
    print(f"Reading prompts from: {csv_path}")
    prompts = read_prompts_csv(csv_path)
    print(f"Found {len(prompts)} prompts in CSV")
    
    # Filter prompts based on credentials flag and difficulty
    prompts_to_run = []
    skipped_prompts = []  # Store (prompt, reason) for skipped prompts
    
    for p in prompts:
        should_run, skip_reason = should_execute_prompt(p, enable_credentials, allowed_difficulties)
        if should_run:
            prompts_to_run.append(p)
        else:
            skipped_prompts.append((p, skip_reason))
    
    skipped = len(skipped_prompts)
    
    if skipped > 0:
        print(f"Skipping {skipped} prompts:")
        skip_reasons = {}
        for _, reason in skipped_prompts:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        for reason, count in skip_reasons.items():
            print(f"  - {count} prompts ({reason})")
        if not enable_credentials and any("credentials" in r for _, r in skipped_prompts):
            print("  (set ENABLE_CREDENTIALS=True to run credential-required prompts)")
        if allowed_difficulties:
            print(f"  (allowed difficulties: {', '.join(allowed_difficulties)})")
    print(f"Will execute {len(prompts_to_run)} prompts")
    
    # Initialize the browser adapter
    adapter = BrowserUseAdapter(video_output_dir=output_base_dir)
    
    # Prepare results
    results: List[Dict[str, Any]] = []
    
    # Run each prompt
    for idx, prompt_row in enumerate(tqdm(prompts_to_run, desc="Running prompts"), start=1):
        prompt_text = prompt_row.get("prompt", "")
        if not prompt_text:
            print(f"Warning: Empty prompt at row {idx}, skipping")
            continue
        
        print(f"\n[{idx}/{len(prompts_to_run)}] Running prompt: {prompt_text[:80]}...")
        if task_timeout:
            print(f"  Timeout: {task_timeout} seconds")
        
        try:
            # Run the agent with timeout
            result: BrowserTaskResult = run_agent_with_timeout(
                adapter, 
                prompt_text, 
                timeout=task_timeout
            )
            
            # Extract output folder name
            output_folder = extract_output_folder(result)
            
            # Create result row with all original columns plus new ones
            result_row = prompt_row.copy()
            result_row["output_folder"] = output_folder
            result_row["success"] = str(result.success).lower()
            result_row["message"] = result.message
            result_row["video_path"] = str(result.video_path)
            
            results.append(result_row)
            
            print(f"  Success: {result.success}")
            print(f"  Output folder: {output_folder}")
            if not result.success and "timed out" in result.message.lower():
                print(f"  ⚠️  Task timed out - recordings and steps are still available")
            
        except Exception as exc:
            print(f"  Error executing prompt: {exc!r}")
            # Still record the row with error information
            result_row = prompt_row.copy()
            result_row["output_folder"] = ""
            result_row["success"] = "false"
            result_row["message"] = f"Error: {exc!r}"
            result_row["video_path"] = ""
            results.append(result_row)
    
    # Add skipped prompts to results (with empty output fields)
    for prompt_row, skip_reason in skipped_prompts:
        result_row = prompt_row.copy()
        result_row["output_folder"] = ""
        result_row["success"] = "skipped"
        result_row["message"] = f"Skipped ({skip_reason})"
        result_row["video_path"] = ""
        results.append(result_row)
    
    # Determine output CSV path
    if output_csv_path is None:
        output_csv_path = csv_path.parent / f"{csv_path.stem}_results.csv"
    
    # Write results CSV
    print(f"\nWriting results to: {output_csv_path}")
    fieldnames = list(prompts[0].keys()) + ["output_folder", "success", "message", "video_path"]
    
    with output_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    
    print(f"Results saved to: {output_csv_path}")
    print(f"Total prompts processed: {len(results)}")
    print(f"Successful: {sum(1 for r in results if r.get('success') == 'true')}")
    print(f"Failed: {sum(1 for r in results if r.get('success') == 'false')}")
    print(f"Skipped: {sum(1 for r in results if r.get('success') == 'skipped')}")


def main() -> None:
    """Main entry point with hardcoded configuration."""
    # Validate input CSV exists
    if not CSV_PATH.exists():
        print(f"Error: CSV file not found: {CSV_PATH}")
        return
    
    # Create output directory if it doesn't exist
    OUTPUT_BASE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Determine output CSV path
    output_csv_path = OUTPUT_CSV_PATH
    if output_csv_path is None:
        output_csv_path = CSV_PATH.parent / f"{CSV_PATH.stem}_results.csv"
    
    # Run the prompts
    run_prompts(
        csv_path=CSV_PATH,
        output_base_dir=OUTPUT_BASE_DIR,
        enable_credentials=ENABLE_CREDENTIALS,
        allowed_difficulties=ALLOWED_DIFFICULTIES,
        task_timeout=TASK_TIMEOUT,
        output_csv_path=output_csv_path,
    )


if __name__ == "__main__":
    main()

