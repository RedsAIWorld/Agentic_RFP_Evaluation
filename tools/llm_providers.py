"""
LLM Provider abstraction -- direct HTTP calls, no vendor SDKs, per Red's
stated preference for integrating APIs directly.

The Evaluation Agent (evaluation_agent.py) only ever calls
`provider.complete(system_prompt, user_prompt) -> str`. It does not know or
care which vendor is behind that call. This is what makes the application
"not architecturally dependent on a particular LLM" (the brief's AI layer
requirement: "Any JSON-capable LLM").

API keys are NEVER written to SQLite or to disk -- they live only in
Streamlit session state for the duration of the browser session, and are
passed into these functions as plain arguments.

Adding a new provider = adding one function + one branch in get_provider().
"""
import json
import requests


class LLMError(Exception):
    """Raised on any provider call failure (network, auth, malformed response)."""
    pass


class LLMProvider:
    name = "base"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
        raise NotImplementedError

    def test_connection(self) -> tuple[bool, str]:
        """Makes one cheap call to confirm the key/model combination works.
        Returns (ok, message)."""
        try:
            reply = self.complete(
                system_prompt="Reply with exactly one word.",
                user_prompt="Reply with the single word: OK",
                max_tokens=10,
            )
            if "OK" in reply.upper():
                return True, f"Connected to {self.name} ({self.model})."
            return True, f"Connected to {self.name} ({self.model}), but got an unexpected reply: {reply[:80]!r}"
        except LLMError as e:
            return False, str(e)


class AnthropicProvider(LLMProvider):
    name = "Anthropic"

    def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
                timeout=90,
            )
        except requests.RequestException as e:
            raise LLMError(f"Network error calling Anthropic: {e}")

        if resp.status_code != 200:
            raise LLMError(f"Anthropic API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        try:
            return "".join(block["text"] for block in data["content"] if block["type"] == "text")
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected Anthropic response shape: {e} -- {json.dumps(data)[:500]}")


class OpenAIProvider(LLMProvider):
    name = "OpenAI"

    def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=90,
            )
        except requests.RequestException as e:
            raise LLMError(f"Network error calling OpenAI: {e}")

        if resp.status_code != 200:
            raise LLMError(f"OpenAI API error {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"Unexpected OpenAI response shape: {e} -- {json.dumps(data)[:500]}")


PROVIDERS = {
    "Anthropic": AnthropicProvider,
    "OpenAI": OpenAIProvider,
}

DEFAULT_MODELS = {
    "Anthropic": "claude-sonnet-4-5-20250929",
    "OpenAI": "gpt-4o",
}


def get_provider(provider_name: str, api_key: str, model: str) -> LLMProvider:
    if provider_name not in PROVIDERS:
        raise LLMError(f"Unknown provider: {provider_name}")
    return PROVIDERS[provider_name](api_key=api_key, model=model)
