#!/usr/bin/env python3
"""
Secure API client for OpenAI and xAI chat completions.
Reads API keys from environment variables - never hardcodes or logs secrets.
"""

import os
import json
import requests
from typing import Optional

# Configuration
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
XAI_ENDPOINT = "https://api.x.ai/v1/chat/completions"
OPENAI_MODEL = "gpt-4o"
XAI_MODEL = "grok-3-latest"
TIMEOUT_SECONDS = 60


def get_api_key(env_var: str) -> str:
    """Securely retrieve API key from environment variable."""
    key = os.environ.get(env_var)
    if not key:
        raise ValueError(f"Missing environment variable: {env_var}")
    return key


def call_openai(prompt: str, system_prompt: Optional[str] = None) -> dict:
    """
    Call OpenAI chat completion API.
    Returns: {"success": bool, "content": str, "error": str|None}
    """
    try:
        api_key = get_api_key("OPENAI_API_KEY")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = requests.post(
            OPENAI_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": OPENAI_MODEL,
                "messages": messages,
                "max_tokens": 2000,
                "temperature": 0.7
            },
            timeout=TIMEOUT_SECONDS
        )

        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return {"success": True, "content": content, "error": None}

    except requests.exceptions.Timeout:
        return {"success": False, "content": "", "error": "Request timeout"}
    except requests.exceptions.RequestException as e:
        # Sanitize error to avoid leaking sensitive info
        error_msg = str(e)
        if "api_key" in error_msg.lower() or "bearer" in error_msg.lower():
            error_msg = "Authentication or request error (details sanitized)"
        return {"success": False, "content": "", "error": error_msg}
    except Exception as e:
        return {"success": False, "content": "", "error": f"Unexpected error: {type(e).__name__}"}


def call_xai(prompt: str, system_prompt: Optional[str] = None) -> dict:
    """
    Call xAI (Grok) chat completion API.
    Returns: {"success": bool, "content": str, "error": str|None}
    """
    try:
        api_key = get_api_key("XAI_API_KEY")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = requests.post(
            XAI_ENDPOINT,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": XAI_MODEL,
                "messages": messages,
                "max_tokens": 2000,
                "temperature": 0.7
            },
            timeout=TIMEOUT_SECONDS
        )

        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return {"success": True, "content": content, "error": None}

    except requests.exceptions.Timeout:
        return {"success": False, "content": "", "error": "Request timeout"}
    except requests.exceptions.RequestException as e:
        error_msg = str(e)
        if "api_key" in error_msg.lower() or "bearer" in error_msg.lower():
            error_msg = "Authentication or request error (details sanitized)"
        return {"success": False, "content": "", "error": error_msg}
    except Exception as e:
        return {"success": False, "content": "", "error": f"Unexpected error: {type(e).__name__}"}


if __name__ == "__main__":
    # Test connectivity (without revealing keys)
    print("API Client loaded. Keys will be read from environment at call time.")
    print(f"OpenAI endpoint: {OPENAI_ENDPOINT}")
    print(f"xAI endpoint: {XAI_ENDPOINT}")
