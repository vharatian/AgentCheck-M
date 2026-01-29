from __future__ import annotations

"""
High-level browser agent abstraction plus a concrete adapter
around the local `browser-use` library.

The adapter does **not** parse the prompt – it forwards the prompt
to a `browser_use.Agent` powered by Gemini via `ChatGoogle`.

Run:
    python browser_agent.py
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

import asyncio
from datetime import datetime

from dotenv import load_dotenv  # type: ignore
from browser_use import Agent, Browser  # type: ignore
from browser_use.llm.google.chat import ChatGoogle  # type: ignore


# =========================
# Abstract Browser Agent
# =========================


@dataclass
class BrowserTaskResult:
    """Result returned by a browser agent run."""

    success: bool
    message: str
    video_path: Path


class BrowserAgent(ABC):
    """
    Abstract base class for browser agents.

    A browser agent receives a natural-language prompt describing an action
    that should be carried out in a real browser, performs the action,
    and records a video of the execution.
    """

    def __init__(self, video_output_dir: str | Path) -> None:
        self.video_output_dir = Path(video_output_dir)
        self.video_output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def run(self, prompt: str) -> BrowserTaskResult:
        """
        Execute the given prompt in a browser and record a video.

        Implementations must:
        - Open a browser
        - Interpret and execute the task described by `prompt`
        - Optionally persist artefacts under `self.video_output_dir`
        - Return a BrowserTaskResult with a path to saved artefacts
        """


# =========================
# Concrete BrowserUse Adapter
# =========================


class BrowserUseAdapter:
    def __init__(self, video_output_dir: str | Path, model_name: str = "gemini-flash-latest") -> None:
        self.video_output_dir = Path(video_output_dir)
        self.video_output_dir.mkdir(parents=True, exist_ok=True)
        self.model_name = model_name

    def run(self, prompt: str):
        return asyncio.run(self._run_async(prompt))

    async def _maybe_await(self, maybe_coro):
        if asyncio.iscoroutine(maybe_coro):
            return await maybe_coro
        return maybe_coro

    def _extract_agent_steps(self, agent: Optional[Agent], prompt: str, timeout_occurred: bool = False) -> str:
        """
        Extract steps/actions from the agent object.
        
        Args:
            agent: The Agent instance (may be None)
            prompt: The original prompt
            timeout_occurred: Whether a timeout occurred
        
        Returns:
            String containing the steps taken by the agent
        """
        if agent is None:
            return "No agent instance available to extract steps from."
        
        steps_parts = []
        
        # Add header
        if timeout_occurred:
            steps_parts.append("⚠️ Task timed out. Steps executed before timeout:")
        else:
            steps_parts.append("Steps executed:")
        steps_parts.append("=" * 80)
        steps_parts.append(f"Prompt: {prompt}")
        steps_parts.append("")
        
        # Try to extract steps from various possible attributes
        # The browser-use library may store steps in different places
        try:
            # Try common attribute names
            if hasattr(agent, 'history') and agent.history:
                steps_parts.append("Agent History:")
                for i, step in enumerate(agent.history, 1):
                    steps_parts.append(f"  Step {i}: {step}")
                steps_parts.append("")
            
            if hasattr(agent, 'actions') and agent.actions:
                steps_parts.append("Agent Actions:")
                for i, action in enumerate(agent.actions, 1):
                    steps_parts.append(f"  Action {i}: {action}")
                steps_parts.append("")
            
            if hasattr(agent, 'steps') and agent.steps:
                steps_parts.append("Agent Steps:")
                for i, step in enumerate(agent.steps, 1):
                    steps_parts.append(f"  Step {i}: {step}")
                steps_parts.append("")
            
            if hasattr(agent, 'execution_log') and agent.execution_log:
                steps_parts.append("Execution Log:")
                for i, log_entry in enumerate(agent.execution_log, 1):
                    steps_parts.append(f"  Log {i}: {log_entry}")
                steps_parts.append("")
            
            # Try to get the string representation of the agent
            agent_str = str(agent)
            if agent_str and agent_str != f"<Agent task={prompt}>":
                steps_parts.append("Agent State:")
                steps_parts.append(agent_str)
                steps_parts.append("")
            
            # Try to access browser_session actions if available
            if hasattr(agent, 'browser_session'):
                browser_session = agent.browser_session
                if hasattr(browser_session, 'actions') and browser_session.actions:
                    steps_parts.append("Browser Session Actions:")
                    for i, action in enumerate(browser_session.actions, 1):
                        steps_parts.append(f"  Action {i}: {action}")
                    steps_parts.append("")
        
        except Exception as exc:
            steps_parts.append(f"Error extracting steps: {exc!r}")
            steps_parts.append("")
        
        # If we couldn't find steps, try to at least show agent attributes
        if len(steps_parts) <= 4:  # Only header and prompt
            steps_parts.append("Available agent attributes:")
            if agent:
                attrs = [attr for attr in dir(agent) if not attr.startswith('_')]
                steps_parts.append(f"  {', '.join(attrs[:20])}")  # Show first 20
            steps_parts.append("")
        
        # Add footer
        if timeout_occurred:
            steps_parts.append("=" * 80)
            steps_parts.append("Note: Task was interrupted due to timeout. Partial execution recorded.")
        
        return "\n".join(steps_parts)

    async def _run_async(self, prompt: str, timeout: Optional[float] = None):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.video_output_dir / ts
        run_dir.mkdir(parents=True, exist_ok=True)

        llm = ChatGoogle(model=self.model_name)

        # record_video_dir is a Browser/BrowserSession parameter :contentReference[oaicite:1]{index=1}
        browser_session = Browser(
            record_video_dir=str(run_dir),
            keep_alive=False,          # important for proper cleanup :contentReference[oaicite:2]{index=2}
            headless=False,            # optional, but nice for debugging
            # record_video_size={"width": 1280, "height": 720},  # optional
        )

        artefact_path = run_dir / "result.txt"
        success = False
        message = ""
        video_path: Optional[Path] = None
        agent: Optional[Agent] = None

        try:
            # Some versions want explicit start; harmless if it's a no-op.
            if hasattr(browser_session, "start"):
                await self._maybe_await(browser_session.start())

            agent = Agent(task=prompt, llm=llm, browser_session=browser_session)
            
            # Run agent with timeout if specified
            if timeout is not None:
                try:
                    result = await asyncio.wait_for(agent.run(), timeout=timeout)
                    success = True
                    message = str(result)
                    artefact_path.write_text(message, encoding="utf-8")
                except asyncio.TimeoutError:
                    # Timeout occurred - extract steps from the agent
                    message = self._extract_agent_steps(agent, prompt, timeout_occurred=True)
                    artefact_path.write_text(message, encoding="utf-8")
            else:
                result = await agent.run()
                success = True
                message = str(result)
                artefact_path.write_text(message, encoding="utf-8")

        except asyncio.TimeoutError:
            # Timeout occurred - try to extract steps from the agent
            message = self._extract_agent_steps(agent, prompt, timeout_occurred=True)
            artefact_path.write_text(message, encoding="utf-8")
        except Exception as exc:
            # Try to extract steps even on other exceptions
            if agent is not None:
                try:
                    steps_message = self._extract_agent_steps(agent, prompt, timeout_occurred=False)
                    message = f"{steps_message}\n\nbrowser-use task failed: {exc!r}"
                except Exception:
                    message = f"browser-use task failed: {exc!r}"
            else:
                message = f"browser-use task failed: {exc!r}"
            artefact_path.write_text(message, encoding="utf-8")

        finally:
            # THIS is what makes the video actually land on disk. :contentReference[oaicite:3]{index=3}
            # Prefer graceful stop() (flushes artifacts) over kill().
            try:
                if hasattr(browser_session, "stop"):
                    await self._maybe_await(browser_session.stop())
            except Exception:
                if hasattr(browser_session, "kill"):
                    await self._maybe_await(browser_session.kill())

        # Now the file should exist (if recording is working).
        # Look for common video extensions recursively.
        candidates = sorted(
            [p for p in run_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}],
            key=lambda p: p.stat().st_mtime,
        )
        if candidates:
            video_path = candidates[-1]

        # Prefer returning the video path if available; otherwise fall back to
        # the textual artefact so callers always get a meaningful Path.
        final_path = video_path or artefact_path

        return BrowserTaskResult(
            success=success,
            message=message,
            video_path=final_path if final_path is not None else run_dir,
        )


# =========================
# Simple manual test entrypoint
# =========================


def main() -> None:
    """
    Minimal example using BrowserUseAdapter with Gemini via ChatGoogle.

    Make sure your `.env` has:
        GOOGLE_API_KEY=your_gemini_key
    """
    load_dotenv()

    video_dir = Path("./recordings")
    sample_prompt = (
        # "open https://www.booking.com and filter the afordable and clean hotels in Amsterdam which are within walkable distance from the city center for the new year 2026"
        "open https://www.booking.com and filter hotels in Amsterdam for the new year 2026"
    )

    adapter = BrowserUseAdapter(video_output_dir=video_dir)
    result = adapter.run(sample_prompt)

    print(f"Success: {result.success}")
    print(f"Message: {result.message}")
    print(f"Video saved to: {result.video_path}")


if __name__ == "__main__":
    main()


