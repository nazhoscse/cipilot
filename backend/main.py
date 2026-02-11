from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import ConversionRequest, ConversionResponse, ValidateGithubActionsRequest, ValidationResult, RetryConversionRequest
from llm_converter import convert_pipeline
import uvicorn
import tempfile
import subprocess
import requests

try:
    import yaml  # PyYAML
except Exception:  # pragma: no cover
    yaml = None

app = FastAPI(title="CI/CD Converter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cipilot.com",
        "https://www.cipilot.com",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5200",
        "https://github.com"
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "CI/CD Converter API",
        "version": "1.0.0",
        "docs": "http://localhost:5200/docs",
        "endpoints": {
            "POST /convert-cicd": "Convert CI/CD configurations",
            "POST /validate-github-actions": "Validate GitHub Actions YAML (PyYAML + actionlint)"
        }
    }


def _validate_yaml(yaml_text: str) -> tuple[bool, str | None]:
    if yaml is None:
        return False, "PyYAML is not installed. Install with: pip install pyyaml"
    try:
        yaml.safe_load(yaml_text)
        return True, None
    except Exception as e:
        return False, str(e)


def _run_actionlint(yaml_text: str) -> tuple[bool, str | None]:
    # actionlint expects a file path.
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=True) as f:
            f.write(yaml_text)
            f.flush()
            proc = subprocess.run(
                ["actionlint", f.name],
                capture_output=True,
                text=True,
                timeout=30,
            )
        output = (proc.stdout or "") + (proc.stderr or "")
        
        # Analyze severity - only pass if ALL issues are info-level shellcheck warnings
        if output:
            # Check for actual errors (syntax-check, expression, etc.)
            has_syntax_error = '[syntax-check]' in output
            has_expression_error = '[expression]' in output
            has_type_error = '[type-check]' in output
            has_severity_error = ':error:' in output.lower()
            has_severity_warning = ':warning:' in output.lower()
            
            # Only consider it info-level if it's ONLY shellcheck info warnings
            is_only_shellcheck_info = (
                ':info:' in output.lower() and 
                '[shellcheck]' in output and
                not has_syntax_error and
                not has_expression_error and
                not has_type_error and
                not has_severity_error and
                not has_severity_warning
            )
            
            if is_only_shellcheck_info:
                # Info-level shellcheck suggestions don't fail validation
                severity_note = "\n\n[Note: Only INFO-level shellcheck suggestions found. These are style recommendations, not errors.]"
                return True, (output.strip() + severity_note)
            
            return proc.returncode == 0, output.strip() or None
        
        return proc.returncode == 0, output.strip() or None
    except FileNotFoundError:
        return False, "actionlint is not installed or not on PATH. Install: https://github.com/rhysd/actionlint"
    except subprocess.TimeoutExpired:
        return False, "actionlint timed out"
    except Exception as e:
        return False, str(e)


def _validate_github_actions_yaml(yaml_text: str) -> ValidationResult:
    yaml_ok, yaml_err = _validate_yaml(yaml_text)
    actionlint_ok, actionlint_out = _run_actionlint(yaml_text) if yaml_ok else (False, "Skipped actionlint due to YAML parse failure")
    return ValidationResult(
        yamlOk=yaml_ok,
        yamlError=yaml_err,
        actionlintOk=actionlint_ok,
        actionlintOutput=actionlint_out,
    )


@app.post("/validate-github-actions", response_model=ValidationResult)
async def validate_github_actions(request: ValidateGithubActionsRequest):
    return _validate_github_actions_yaml(request.yaml)


@app.post("/retry-conversion", response_model=ConversionResponse)
async def retry_conversion(request: RetryConversionRequest):
    """Endpoint to retry conversion with user feedback"""
    try:
        llm = request.llmSettings
        provider = (llm.provider if llm else 'ollama')
        model = (llm.model if llm else 'gemma3:12b')
        base_url = (llm.baseUrl if llm else None)
        api_key = (llm.apiKey if llm else None)

        if provider in ("openai", "xai") and not api_key:
            raise HTTPException(status_code=400, detail=f"Missing apiKey for provider '{provider}'")

        # Build comprehensive feedback including previous attempt
        comprehensive_feedback = (
            f"PREVIOUS GITHUB ACTIONS YAML ATTEMPT (that had errors):\n"
            f"---\n"
            f"{request.previousGitHubActionsAttempt}\n"
            f"---\n\n"
            f"ERRORS/ISSUES WITH ABOVE YAML:\n"
            f"{request.feedback}\n\n"
            f"ORIGINAL TRAVIS CI SOURCE (for reference only):\n"
            f"---\n"
            f"{request.originalTravisConfig}\n"
            f"---\n\n"
            f"TASK: Fix the GitHub Actions YAML above to resolve all errors. "
            f"You can reference the Travis CI source for logic, but you MUST output valid GitHub Actions YAML."
        )

        converted = convert_pipeline(
            provider=provider,
            model=model,
            source_ci='github-actions-draft',
            target_ci=request.targetPlatform,
            content=request.previousGitHubActionsAttempt,
            base_url=base_url,
            api_key=api_key,
            validation_feedback=comprehensive_feedback,
        )

        validation = None
        if request.targetPlatform == 'github-actions':
            validation = _validate_github_actions_yaml(converted)

        # Increment attempts from the request
        current_attempts = (request.currentAttempts or 1) + 1
        
        print(f"[RETRY] Previous attempts: {request.currentAttempts}, New attempts: {current_attempts}")

        return ConversionResponse(
            convertedConfig=converted,
            message="Retry conversion completed",
            status="success",
            originalServices=['travis-ci'],
            targetPlatform=request.targetPlatform,
            providerUsed=provider,
            modelUsed=model,
            attempts=current_attempts,
            validation=validation,
        )

    except Exception as e:
        print(f"Error during retry conversion: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e) or "Failed to retry conversion")
    
@app.post("/convert-cicd", response_model=ConversionResponse)
async def convert_cicd(request: ConversionRequest):
    """Endpoint to convert CI/CD configurations"""

    try:
        print(f"Received conversion request for repository: {request.repository.owner}/{request.repository.name} on branch {request.repository.branch}")
        print(f"Detected services: {request.detectedServices}")
        
        has_github_actions = 'GitHub Actions' in request.detectedServices

        llm = request.llmSettings
        provider = (llm.provider if llm else 'ollama')
        model = (llm.model if llm else 'gemma3:12b')
        base_url = (llm.baseUrl if llm else None)
        api_key = (llm.apiKey if llm else None)

        if provider in ("openai", "xai", "groq") and not api_key:
            raise HTTPException(status_code=400, detail=f"Missing apiKey for provider '{provider}'")
        
        # Determine target platform from request, or fallback to old logic
        if request.targetPlatform:
            target_platform = request.targetPlatform
            # Determine source platform based on what configs we have
            if target_platform == 'github-actions':
                # Converting TO GitHub Actions, so source is non-GitHub-Actions CI
                available_sources = [s for s in request.detectedServices if s != 'GitHub Actions']
                src_platform = available_sources[0] if available_sources else request.detectedServices[0]
            else:
                # Converting TO Travis CI, so source is GitHub Actions
                src_platform = 'GitHub Actions' if 'GitHub Actions' in request.detectedServices else request.detectedServices[0]
        else:
            # Fallback to old logic for backward compatibility
            has_github_actions = 'GitHub Actions' in request.detectedServices
            if has_github_actions:
                # If GitHub Actions is detected, convert to Travis CI
                src_platform = 'github-actions'
                target_platform = 'travis-ci'
            else:
                # Default: convert to GitHub Actions
                src_platform = request.detectedServices[0]
                target_platform = 'github-actions'
        
        # Combine all source configs from all detected services
        all_contents = []
        source_services = []
        
        for service_name, src_config in request.existingConfigs.items():
            # Skip if this is the target platform
            if service_name == 'GitHub Actions' and target_platform == 'github-actions':
                continue
            if service_name == 'Travis CI' and target_platform == 'travis-ci':
                continue
            
            source_services.append(service_name)
                
            # Handle new multi-file structure
            if 'files' in src_config and isinstance(src_config['files'], list):
                for file_info in src_config['files']:
                    file_path = file_info.get('path', 'unknown')
                    content = file_info.get('content', '')
                    if content.strip():
                        all_contents.append(
                            f"# ==========================================\n"
                            f"# Source: {service_name}\n"
                            f"# File: {file_path}\n"
                            f"# ==========================================\n"
                            f"{content}"
                        )
            elif 'content' in src_config:
                # Legacy single-file structure
                content = src_config.get('content', '')
                if content.strip():
                    all_contents.append(
                        f"# ==========================================\n"
                        f"# Source: {service_name}\n"
                        f"# ==========================================\n"
                        f"{content}"
                    )
        
        pipeline_content = '\n\n'.join(all_contents) if all_contents else ''
        
        # Use descriptive source name for multiple services
        if len(source_services) > 1:
            src_display_name = f"Multiple CI services ({', '.join(source_services)})"
        elif source_services:
            src_display_name = source_services[0]
        else:
            src_display_name = src_platform  # Fallback
        
        converted = convert_pipeline(
            provider=provider,
            model=model,
            source_ci=src_display_name,
            target_ci=target_platform,
            content=pipeline_content,
            base_url=base_url,
            api_key=api_key,
        )

        attempts = 1
        validation = None
        if target_platform == 'github-actions':
            validation = _validate_github_actions_yaml(converted)
            if (not validation.yamlOk) or (not validation.actionlintOk):
                attempts = 2
                feedback_parts = []
                if not validation.yamlOk:
                    feedback_parts.append(f"YAML parse error: {validation.yamlError}")
                if not validation.actionlintOk:
                    feedback_parts.append(f"actionlint output: {validation.actionlintOutput}")
                feedback = "\n".join([p for p in feedback_parts if p])

                converted_retry = convert_pipeline(
                    provider=provider,
                    model=model,
                    source_ci=src_platform,
                    target_ci=target_platform,
                    content=pipeline_content,
                    base_url=base_url,
                    api_key=api_key,
                    validation_feedback=feedback,
                )
                converted = converted_retry
                validation = _validate_github_actions_yaml(converted)
            
        return ConversionResponse(
            convertedConfig=converted,
            message=f"Received conversion request for repository: {request.repository.owner}/{request.repository.name} on branch {request.repository.branch}",
            status="success",
            originalServices=request.detectedServices,
            targetPlatform=target_platform,
            providerUsed=provider,
            modelUsed=model,
            attempts=attempts,
            validation=validation,
        )
        
    except requests.exceptions.HTTPError as e:
        error_msg = str(e)
        if '429' in error_msg or 'Too Many Requests' in error_msg:
            print(f"Rate limit error: {error_msg}")
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "Rate Limit Exceeded",
                    "message": f"The LLM provider ({provider}) has rate limited your requests. This often happens when migrating multiple large CI configurations. Please try: 1) Wait a few minutes and try again, 2) Switch to a different LLM provider (Ollama, OpenAI, or xAI) in the extension options, or 3) Migrate services one at a time.",
                    "provider": provider,
                    "suggestion": "Switch to Ollama (local) or OpenAI for better rate limits"
                }
            )
        else:
            print(f"HTTP error during conversion: {error_msg}")
            raise HTTPException(status_code=500, detail=f"LLM API error: {error_msg}")
    except ValueError as e:
        # ValueError is raised by llm_converter for API errors
        error_msg = str(e)
        print(f"LLM Error during conversion: {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)
    except Exception as e:
        print(f"Error during conversion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to convert CI/CD configuration: {str(e)}")
        

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5200, reload=True) 