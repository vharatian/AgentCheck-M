"""
LLM Client for OpenRouter API

Uses OpenRouter to access Gemini and other models.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Any, Optional

import requests
from dotenv import load_dotenv


# OpenRouter Configuration
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-3-flash-preview"


class LLMClient:
    """
    OpenRouter API client for LLM calls.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.3,
        max_tokens: int = 8192
    ):
        load_dotenv()
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found. Set in .env or pass as argument.")
        
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost",  # Required by OpenRouter
            "X-Title": "Site Mapper"
        }
    
    def generate(self, prompt: str, system_prompt: str = None) -> str:
        """
        Generate a response from the LLM.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            
        Returns:
            LLM response text
        """
        messages = []
        
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        
        response = requests.post(
            OPENROUTER_API_URL,
            headers=self.headers,
            json=payload,
            timeout=60
        )
        
        if response.status_code != 200:
            raise Exception(f"OpenRouter API error: {response.status_code} - {response.text[:200]}")
        
        result = response.json()
        
        # Extract content from response
        choices = result.get("choices", [])
        if not choices:
            raise Exception("No response from LLM")
        
        return choices[0].get("message", {}).get("content", "")
    
    def generate_json(self, prompt: str, system_prompt: str = None) -> Dict[str, Any]:
        """
        Generate a JSON response from the LLM.
        
        Args:
            prompt: User prompt (should request JSON output)
            system_prompt: Optional system prompt
            
        Returns:
            Parsed JSON dict
        """
        response_text = self.generate(prompt, system_prompt)
        return self._parse_json(response_text)
    
    def _parse_json(self, text: str) -> Dict[str, Any]:
        """Parse JSON from LLM response, handling code fences."""
        text = text.strip()
        
        # Remove code fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # Try to find JSON in the response
            import re
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except:
                    pass
            return {"error": f"Failed to parse JSON: {str(e)[:100]}"}


# Convenience function
def ask_llm(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """Quick helper to ask the LLM a question."""
    client = LLMClient(model=model)
    return client.generate(prompt)
