import os
import requests

DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com"
DEFAULT_XAI_BASE_URL = "https://api.x.ai"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com"

def _build_prompt(source_ci: str, target_ci: str, content: str, feedback: str | None = None) -> str:
    # Special case for retry (source_ci will be 'github-actions-draft')
    is_retry = source_ci == 'github-actions-draft'
    
    if is_retry and feedback:
        # For retry: the feedback contains everything (previous attempt, errors, original source)
        return (
            "You are a CI/CD migration expert.\n\n"
            "TASK: Fix the GitHub Actions YAML that has validation errors.\n\n"
            "CRITICAL REQUIREMENTS:\n"
            "1. You MUST output ONLY valid GitHub Actions YAML syntax\n"
            "2. DO NOT output Travis CI or any other CI syntax\n"
            "3. DO NOT include any explanations, comments, or markdown\n"
            "4. DO NOT wrap output in code blocks (```yaml)\n"
            "5. Fix ALL errors listed below\n"
            "6. Maintain the workflow logic and structure\n\n"
            "COMMON FIXES NEEDED:\n"
            "- Services must be a MAPPING (key: value), not a sequence (- items)\n"
            "  WRONG: services:\\n      - name: mysql\n"
            "  CORRECT: services:\\n      mysql:\\n        image: mysql:latest\n"
            "- Use @v4 for actions (not @v3): actions/checkout@v4, actions/setup-java@v4\n"
            "- Use $(command) instead of backticks `command`\n"
            "- Quote shell variables: \"$(which rst2html.py)\" not `which rst2html.py`\n"
            "- Quote environment variables in shell: \"$BRANCH\" not $BRANCH\n"
            "- Quote GitHub expressions: \"${{ github.workspace }}\" when used in shell\n"
            "- GitHub context properties: Use ${{ github.workspace }} NOT ${{ github.home }}\n"
            "- For home directory cache: Use $HOME or actions/cache@v4, NOT ${{ github.home }}\n"
            "- Available context: github.workspace, github.ref, github.ref_name, github.actor, etc.\n\n"
            + feedback + "\n\n"
            "Now generate the CORRECTED GitHub Actions YAML (and NOTHING else):"
        )
    
    feedback_block = ""
    if feedback and feedback.strip():
        feedback_block = (
            "\n\n=== VALIDATION FEEDBACK ===\n"
            "The previous GitHub Actions YAML you generated had the following issues:\n\n"
            f"{feedback.strip()}\n\n"
            "Please generate a NEW GitHub Actions YAML that fixes these issues.\n"
            "DO NOT return the Travis CI source - you must return VALID GitHub Actions YAML.\n"
            "=== END FEEDBACK ===\n\n"
        )
    
    target_name = "GitHub Actions workflow" if target_ci == "github-actions" else target_ci
    
    # Check if content contains multiple services (indicated by separator comments)
    has_multiple_services = '# Source:' in content and content.count('# ==========================================') > 2
    
    multi_service_note = ""
    if has_multiple_services:
        multi_service_note = (
            "\n\nNOTE: The configuration below contains CI/CD configs from MULTIPLE services.\n"
            "Your task is to consolidate ALL of them into ONE comprehensive GitHub Actions workflow.\n"
            "Combine all jobs, steps, and logic from all services into a single, well-structured workflow.\n\n"
        )
    
    return (
        "You are a CI/CD migration expert.\n\n"
        f"TASK: Convert the configuration(s) below into a {target_name}.\n\n"
        "CRITICAL REQUIREMENTS:\n"
        f"1. You MUST output ONLY valid {target_name} YAML syntax\n"
        "2. DO NOT include any explanations, comments, or markdown\n"
        "3. DO NOT wrap output in code blocks (```yaml)\n"
        "4. Preserve all build, test, deploy, and service logic from ALL source configs\n"
        "5. Use proper GitHub Actions syntax with jobs, steps, and actions\n"
        "6. Services must be mappings: services:\\n  mysql:\\n    image: mysql:latest\n"
        "7. Use latest action versions: actions/checkout@v4, actions/setup-java@v4\n"
        "8. Use $(command) not backticks for shell substitution\n"
        "9. Combine similar jobs intelligently (e.g., merge multiple 'build' jobs)\n"
        "10. Preserve environment variables, secrets, and dependencies from all sources\n\n"
        + multi_service_note
        + feedback_block +
        "SOURCE CI/CD CONFIGURATION(S) TO CONVERT:\n"
        "---\n"
        f"{content}\n"
        "---\n\n"
        f"Now generate ONE comprehensive {target_name} YAML that includes ALL the logic above (and NOTHING else):"
    )


def _normalize_base_url(base_url: str | None, default_base: str) -> str:
    url = (base_url or "").strip()
    if not url:
        url = default_base
    return url.rstrip("/")


def _ollama_generate(*, base_url: str | None, model: str, prompt: str, timeout_s: int = 300) -> str:
    base = _normalize_base_url(base_url, DEFAULT_OLLAMA_BASE_URL)
    url = f"{base}/api/generate"
    resp = requests.post(
        url,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout_s,
    )
    resp.raise_for_status()
    result = (resp.json().get("response") or "").strip()
    # Strip markdown code blocks if present
    if result.startswith("```yaml"):
        result = result[7:]
    elif result.startswith("```"):
        result = result[3:]
    if result.endswith("```"):
        result = result[:-3]
    return result.strip()


def _openai_compatible_chat(*, base_url: str | None, api_key: str, model: str, system: str, user: str, timeout_s: int = 300) -> str:
    base = _normalize_base_url(base_url, DEFAULT_OPENAI_BASE_URL)
    # Support base URLs like https://api.openai.com or https://api.openai.com/v1
    if base.endswith("/v1"):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"

    print(f"[LLM] Calling {url} with model={model}")

    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        },
        timeout=timeout_s,
    )

    # Check for errors and provide detailed message
    if resp.status_code != 200:
        try:
            error_data = resp.json()
            error_msg = error_data.get('error', {}).get('message', '') or str(error_data)
        except Exception:
            error_msg = resp.text or f"HTTP {resp.status_code}"
        print(f"[LLM] API Error: {error_msg}")
        raise ValueError(f"API Error ({resp.status_code}): {error_msg}")
    data = resp.json()
    try:
        result = (data["choices"][0]["message"]["content"] or "").strip()
        # Strip markdown code blocks if present
        if result.startswith("```yaml"):
            result = result[7:]
        elif result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        return result.strip()
    except Exception:
        # Best-effort fallback if provider returns a different envelope
        return (str(data) or "").strip()


def _anthropic_chat(*, base_url: str | None, api_key: str, model: str, system: str, user: str, timeout_s: int = 300) -> str:
    """Anthropic Claude API using Messages API format"""
    base = _normalize_base_url(base_url, DEFAULT_ANTHROPIC_BASE_URL)
    url = f"{base}/v1/messages"

    print(f"[LLM] Calling Anthropic {url} with model={model}")

    resp = requests.post(
        url,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": [
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        },
        timeout=timeout_s,
    )

    if resp.status_code != 200:
        try:
            error_data = resp.json()
            error_msg = error_data.get('error', {}).get('message', '') or str(error_data)
        except Exception:
            error_msg = resp.text or f"HTTP {resp.status_code}"
        print(f"[LLM] Anthropic API Error: {error_msg}")
        raise ValueError(f"Anthropic API Error ({resp.status_code}): {error_msg}")
    
    data = resp.json()
    try:
        result = (data["content"][0]["text"] or "").strip()
        # Strip markdown code blocks if present
        if result.startswith("```yaml"):
            result = result[7:]
        elif result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        return result.strip()
    except Exception as e:
        print(f"[LLM] Error parsing Anthropic response: {e}")
        return (str(data) or "").strip()


def _google_chat(*, base_url: str | None, api_key: str, model: str, system: str, user: str, timeout_s: int = 300) -> str:
    """Google Gemini API using generateContent endpoint"""
    base = _normalize_base_url(base_url, DEFAULT_GOOGLE_BASE_URL)
    # Gemini API format: /v1/models/{model}:generateContent
    url = f"{base}/v1/models/{model}:generateContent"

    print(f"[LLM] Calling Google Gemini {url}")

    # Combine system and user prompts for Gemini
    combined_prompt = f"{system}\n\n{user}"

    resp = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
        },
        params={"key": api_key},
        json={
            "contents": [
                {
                    "parts": [
                        {"text": combined_prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 4096,
            }
        },
        timeout=timeout_s,
    )

    if resp.status_code != 200:
        try:
            error_data = resp.json()
            error_msg = error_data.get('error', {}).get('message', '') or str(error_data)
        except Exception:
            error_msg = resp.text or f"HTTP {resp.status_code}"
        print(f"[LLM] Google API Error: {error_msg}")
        raise ValueError(f"Google API Error ({resp.status_code}): {error_msg}")
    
    data = resp.json()
    try:
        result = (data["candidates"][0]["content"]["parts"][0]["text"] or "").strip()
        # Strip markdown code blocks if present
        if result.startswith("```yaml"):
            result = result[7:]
        elif result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        return result.strip()
    except Exception as e:
        print(f"[LLM] Error parsing Google response: {e}")
        return (str(data) or "").strip()


def _detect_wrong_format(output: str, source_ci: str, target_ci: str) -> bool:
    """Detect if LLM returned source format instead of target format"""
    output_lower = output.lower()
    
    # If converting TO GitHub Actions, check for Travis CI keywords
    if target_ci == "github-actions" and source_ci.lower() in ["travis-ci", "travis ci"]:
        # Travis CI specific keywords that shouldn't be in GitHub Actions
        travis_keywords = ["language:", "dist:", "before_script:", "after_failure:", "skip_cleanup:"]
        if any(keyword in output_lower for keyword in travis_keywords):
            return True
    
    # If converting TO GitHub Actions, it MUST have these keywords
    if target_ci == "github-actions":
        required_gha = ["name:", "on:", "jobs:"]
        if not all(keyword in output_lower for keyword in required_gha):
            return True
    
    return False


def convert_pipeline(
    *,
    provider: str,
    model: str,
    source_ci: str,
    target_ci: str,
    content: str,
    base_url: str | None = None,
    api_key: str | None = None,
    validation_feedback: str | None = None,
) -> str:
    prompt = _build_prompt(source_ci, target_ci, content, validation_feedback)

    provider_norm = (provider or "ollama").strip().lower()
    result = ""
    
    if provider_norm == "ollama":
        result = _ollama_generate(base_url=base_url, model=model, prompt=prompt)
    elif provider_norm == "anthropic":
        if not api_key:
            raise ValueError(f"api_key is required for provider '{provider_norm}'")
        result = _anthropic_chat(
            base_url=base_url,
            api_key=api_key,
            model=model,
            system="You are a CI/CD migration expert. You MUST output only the target CI/CD format requested.",
            user=prompt,
        )
    elif provider_norm == "google":
        if not api_key:
            raise ValueError(f"api_key is required for provider '{provider_norm}'")
        result = _google_chat(
            base_url=base_url,
            api_key=api_key,
            model=model,
            system="You are a CI/CD migration expert. You MUST output only the target CI/CD format requested.",
            user=prompt,
        )
    elif provider_norm in ("openai", "xai", "groq", "generic"):
        if not api_key:
            raise ValueError(f"api_key is required for provider '{provider_norm}'")

        if provider_norm == "xai":
            effective_base = _normalize_base_url(base_url, DEFAULT_XAI_BASE_URL)
        elif provider_norm == "groq":
            effective_base = _normalize_base_url(base_url, DEFAULT_GROQ_BASE_URL)
        elif provider_norm == "generic":
            # For generic provider, base_url is required
            if not base_url:
                raise ValueError("base_url is required for generic provider")
            effective_base = _normalize_base_url(base_url, "")
        else:
            effective_base = _normalize_base_url(base_url, DEFAULT_OPENAI_BASE_URL)

        result = _openai_compatible_chat(
            base_url=effective_base,
            api_key=api_key,
            model=model,
            system="You are a CI/CD migration expert. You MUST output only the target CI/CD format requested.",
            user=prompt,
        )
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    
    # Validate that we got the right format
    if _detect_wrong_format(result, source_ci, target_ci):
        raise ValueError(
            f"LLM returned {source_ci} format instead of {target_ci}. "
            f"The output must be valid {target_ci} YAML with proper syntax (name, on, jobs for GitHub Actions)."
        )
    
    return result


def convert_pipeline_ollama(source_ci: str, target_ci: str, content: str) -> str:
    # Backward-compatible wrapper
    return convert_pipeline(
        provider="ollama",
        model="gemma3:12b",
        source_ci=source_ci,
        target_ci=target_ci,
        content=content,
        base_url=None,
        api_key=None,
    )
