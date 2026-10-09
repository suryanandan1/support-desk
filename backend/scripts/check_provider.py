"""Check which Gemini models your API key can use.

Usage (from backend/, with the virtual environment active):
    python scripts/check_provider.py

Prints every chat-capable and embedding-capable model available to the key in
backend/.env, then confirms that GEMINI_CHAT_MODEL and GEMINI_EMBEDDING_MODEL exist.
Exit code: 0 = both configured models found, 1 = setup problem, 2 = model missing.
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make "app" importable

from app.core.config import get_settings  # noqa: E402

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _get(url: str, api_key: str, timeout: float) -> dict[str, Any]:
    # The key goes in a header, not the URL, so it never shows up in logs or proxies.
    request = urllib.request.Request(url, headers={"x-goog-api-key": api_key})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _api_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        return json.load(exc)["error"]["message"]
    except Exception:  # noqa: BLE001 - any unreadable body falls back to the reason
        return str(exc.reason)


def list_models(api_key: str, timeout: float) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    page_token = ""
    while True:
        query = {"pageSize": "1000"}
        if page_token:
            query["pageToken"] = page_token
        data = _get(f"{API_BASE}/models?{urllib.parse.urlencode(query)}", api_key, timeout)
        models.extend(data.get("models", []))
        page_token = data.get("nextPageToken", "")
        if not page_token:
            return models


def model_exists(name: str, api_key: str, timeout: float) -> bool:
    """Look the model up directly; this also resolves aliases such as *-latest."""
    try:
        _get(f"{API_BASE}/models/{urllib.parse.quote(name)}", api_key, timeout)
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def _print_group(title: str, models: list[dict[str, Any]]) -> None:
    print(f"\n{title} ({len(models)}):")
    for model in sorted(models, key=lambda m: m["name"]):
        print(f"  {model['name'].removeprefix('models/'):<45} {model.get('displayName', '')}")


def main() -> int:
    settings = get_settings()
    api_key = settings.gemini_api_key.get_secret_value().strip() if settings.gemini_api_key else ""
    if not api_key:
        print("GEMINI_API_KEY is empty in backend/.env.")
        print("Create a free key at https://aistudio.google.com/apikey and add it there.")
        return 1

    timeout = settings.llm_timeout_seconds
    try:
        models = list_models(api_key, timeout)
        configured = {
            "GEMINI_CHAT_MODEL": settings.gemini_chat_model,
            "GEMINI_EMBEDDING_MODEL": settings.gemini_embedding_model,
        }
        found = {var: model_exists(name, api_key, timeout) for var, name in configured.items()}
    except urllib.error.HTTPError as exc:
        print(f"Gemini API error (HTTP {exc.code}): {_api_error_message(exc)}")
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach the Gemini API: {exc.reason}")
        return 1

    def supports(model: dict[str, Any], method: str) -> bool:
        return method in model.get("supportedGenerationMethods", [])

    _print_group("Chat models", [m for m in models if supports(m, "generateContent")])
    _print_group("Embedding models", [m for m in models if supports(m, "embedContent")])

    print("\nConfigured models:")
    for var, name in configured.items():
        print(f"  {var:<24} {name:<35} {'OK' if found[var] else 'NOT FOUND'}")
    if not all(found.values()):
        print("\nPick a model from the lists above and set it in backend/.env.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
