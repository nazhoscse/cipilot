"""
GHA Fix Agent - LLM-based workflow error fixing

Uses LLM to analyze GHA workflow errors and generate fixes.
"""
import re
from typing import Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import PipelineConfig


FIX_SYSTEM_PROMPT = """You are an expert at fixing GitHub Actions workflow files.

Given a YAML workflow file and error logs from a failed GitHub Actions run, analyze the error and provide a fixed version of the workflow.

Rules:
1. Only fix the specific error indicated in the logs
2. Preserve all other functionality
3. Do not add unnecessary changes
4. Ensure the output is valid YAML
5. Keep the same overall structure and intent

Output ONLY the corrected YAML content, nothing else. No explanations, no markdown code blocks, just the raw YAML."""


FIX_USER_PROMPT = """The following GitHub Actions workflow failed with this error:

### Error Logs:
```
{error_logs}
```

### Original Workflow YAML:
```yaml
{workflow_yaml}
```

Please provide the corrected workflow YAML that fixes this error."""


def fix_workflow_from_error(
    workflow_yaml: str,
    error_logs: str,
    config: PipelineConfig,
    retries: int = 3,
    retry_delay: float = 2.0,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Use LLM to fix a workflow based on error logs.
    
    Args:
        workflow_yaml: The original workflow YAML that failed
        error_logs: Relevant portion of error logs from GHA run
        config: Pipeline configuration with LLM settings
        retries: Number of retry attempts
        retry_delay: Delay between retries in seconds
        
    Returns:
        Tuple of (fixed_yaml, error_message) - fixed_yaml is None on failure
    """
    import time
    from openai import OpenAI
    
    # Longer timeout for reasoning models (they need more time to think)
    api_timeout = 300.0  # 5 minutes
    
    # Initialize LLM client based on provider
    if config.llm_provider == "openai":
        client = OpenAI(api_key=config.llm_api_key, timeout=api_timeout)
    elif config.llm_provider == "azure":
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=config.llm_api_key,
            api_version="2024-02-01",
            azure_endpoint=config.llm_base_url,
            timeout=api_timeout,
        )
    elif config.llm_provider == "xai":
        client = OpenAI(
            api_key=config.llm_api_key,
            base_url="https://api.x.ai/v1",
            timeout=api_timeout,
        )
    else:
        # Generic OpenAI-compatible provider
        client = OpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            timeout=api_timeout,
        )
    
    print(f"[GHA Repair Agent] Using {config.llm_provider}/{config.llm_model}")
    
    user_prompt = FIX_USER_PROMPT.format(
        error_logs=error_logs[:3000],  # Truncate to avoid token limits
        workflow_yaml=workflow_yaml,
    )
    
    last_error = None
    
    for attempt in range(retries):
        try:
            print(f"[GHA Repair Agent] Generating fix (attempt {attempt + 1}/{retries})...")
            response = client.chat.completions.create(
                model=config.llm_model,
                messages=[
                    {"role": "system", "content": FIX_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,  # Low temperature for more deterministic fixes
                max_tokens=4096,
            )
            
            fixed_yaml = response.choices[0].message.content
            print(f"[GHA Repair Agent] ✓ Received fix ({len(fixed_yaml) if fixed_yaml else 0} chars)")
            
            if not fixed_yaml:
                last_error = "LLM returned empty response"
                continue
            
            # Clean up the response
            fixed_yaml = clean_yaml_response(fixed_yaml)
            
            # Basic validation - check if it looks like valid YAML
            if not validate_yaml_basic(fixed_yaml):
                last_error = "LLM response is not valid YAML"
                continue
            
            return fixed_yaml, None
            
        except Exception as e:
            last_error = str(e)
            if attempt < retries - 1:
                time.sleep(retry_delay)
    
    return None, f"Failed to fix workflow after {retries} attempts: {last_error}"


def clean_yaml_response(response: str) -> str:
    """
    Clean up LLM response to extract pure YAML.
    
    Args:
        response: Raw LLM response
        
    Returns:
        Cleaned YAML content
    """
    # Remove markdown code blocks if present
    response = response.strip()
    
    # Remove ```yaml ... ``` blocks
    if response.startswith("```"):
        lines = response.split("\n")
        # Find start and end of code block
        start_idx = 0
        end_idx = len(lines)
        
        for i, line in enumerate(lines):
            if line.startswith("```") and i == 0:
                start_idx = 1
            elif line.startswith("```") and i > 0:
                end_idx = i
                break
        
        response = "\n".join(lines[start_idx:end_idx])
    
    return response.strip()


def validate_yaml_basic(yaml_content: str) -> bool:
    """
    Basic YAML validation without full parsing.
    
    Args:
        yaml_content: YAML content to validate
        
    Returns:
        True if content looks like valid YAML
    """
    if not yaml_content:
        return False
    
    # Must have some content
    if len(yaml_content.strip()) < 10:
        return False
    
    # Should have at least one key-value pattern
    if not re.search(r"^\s*[\w-]+:", yaml_content, re.MULTILINE):
        return False
    
    # For GHA workflows, should have 'on:' or 'name:'
    if not re.search(r"^\s*(on|name|jobs):", yaml_content, re.MULTILINE):
        return False
    
    return True


async def fix_and_push_workflow(
    fork_owner: str,
    repo_name: str,
    branch_name: str,
    workflow_path: str,
    current_yaml: str,
    error_logs: str,
    github_pat: str,
    config: PipelineConfig,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Fix a workflow and push the update to the fork.
    
    Args:
        fork_owner: Owner of the forked repository
        repo_name: Repository name
        branch_name: Branch to update
        workflow_path: Path to workflow file (e.g., ".github/workflows/ci.yml")
        current_yaml: Current workflow YAML content
        error_logs: Error logs from failed run
        github_pat: GitHub PAT
        config: Pipeline configuration
        
    Returns:
        Tuple of (fixed_yaml, error_message) - fixed_yaml is None on failure
    """
    # First, get the fix from LLM
    fixed_yaml, fix_error = fix_workflow_from_error(
        workflow_yaml=current_yaml,
        error_logs=error_logs,
        config=config,
        retries=config.max_retries,
        retry_delay=config.retry_delay_seconds,
    )
    
    if not fixed_yaml:
        return None, fix_error
    
    # If no changes, return original
    if fixed_yaml.strip() == current_yaml.strip():
        return None, "LLM fix resulted in no changes"
    
    # Import update_fork_file from pull_request module
    from stages.pull_request import update_fork_file
    
    # Push the fix to the fork
    success, push_error = await update_fork_file(
        fork_owner=fork_owner,
        repo_name=repo_name,
        branch_name=branch_name,
        file_path=workflow_path,
        content=fixed_yaml,
        commit_message="fix: Auto-fix workflow based on GHA error",
        github_pat=github_pat,
    )
    
    if not success:
        return None, push_error
    
    return fixed_yaml, None
