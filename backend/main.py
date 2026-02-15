from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from models import ConversionRequest, ConversionResponse, ValidateGithubActionsRequest, ValidationResult, RetryConversionRequest, DetectionRequest, DetectionResponse
from llm_converter import convert_pipeline, semantic_verify_migration
from agentic_pipeline import run_conversion_pipeline
from analytics import analytics_service
import uvicorn
import tempfile
import subprocess
import requests
import time
import re
from typing import Optional, List

try:
    import yaml  # PyYAML
except Exception:  # pragma: no cover
    yaml = None


# Lifespan for startup/shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize analytics
    try:
        await analytics_service.initialize()
        print("[STARTUP] Analytics service initialized")
    except Exception as e:
        print(f"[STARTUP] Analytics initialization failed (non-critical): {e}")
    
    yield
    
    # Shutdown: Close analytics
    try:
        await analytics_service.close()
        print("[SHUTDOWN] Analytics service closed")
    except Exception as e:
        print(f"[SHUTDOWN] Error closing analytics: {e}")


app = FastAPI(title="CI/CD Converter API", lifespan=lifespan)

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


# Helper to extract analytics headers from request
def _get_analytics_context(request: Request) -> dict:
    """Extract anonymous analytics context from request headers"""
    return {
        'user_id': request.headers.get('X-Analytics-User-ID'),
        'session_id': request.headers.get('X-Analytics-Session-ID'),  # Client-provided session hint
        'ip_address': request.headers.get('X-Forwarded-For', request.client.host if request.client else None),
        'user_agent': request.headers.get('User-Agent'),
        'country': request.headers.get('CF-IPCountry'),  # Cloudflare header
        'timezone': request.headers.get('X-Timezone'),
        'referrer': request.headers.get('Referer'),
    }


async def _get_or_create_session(analytics_ctx: dict) -> tuple[str, int]:
    """
    Get or create an active session for the user.
    
    Returns (user_id, session_id) tuple.
    Uses 30-min inactivity timeout to determine if a new session should be created.
    """
    user_id = analytics_ctx.get('user_id')
    if not user_id:
        # Generate anonymous user ID if not provided
        import uuid
        user_id = f"anon_{uuid.uuid4().hex[:12]}"
    
    # Get or create active session with timeout tracking
    session_id = await analytics_service.get_or_create_active_session(
        user_id=user_id,
        ip_address=analytics_ctx.get('ip_address'),
        user_agent=analytics_ctx.get('user_agent'),
        country=analytics_ctx.get('country'),
        timezone=analytics_ctx.get('timezone'),
        referrer=analytics_ctx.get('referrer'),
    )
    
    return user_id, session_id


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "CI/CD Converter API",
        "version": "1.0.0",
        "docs": "http://localhost:5200/docs",
        "endpoints": {
            "POST /convert-cicd": "Convert CI/CD configurations",
            "POST /detect-ci": "Detect CI platform from YAML content",
            "POST /validate-github-actions": "Validate GitHub Actions YAML (PyYAML + actionlint)",
            "GET /analytics/health": "Check analytics service health",
            "GET /analytics/stats": "Get aggregated statistics (admin)",
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
        
        # Analyze severity - determine what's a hard failure vs a soft warning
        if output:
            # Check for actual breaking errors - these should ALWAYS fail
            has_syntax_error = '[syntax-check]' in output
            has_expression_error = '[expression]' in output
            has_type_error = '[type-check]' in output
            has_runner_label_error = '[runner-label]' in output  # Invalid runner name
            has_action_error = '[action]' in output  # Action-related errors
            
            # Check if it's ONLY "action is too old" warning (the only non-blocking case)
            is_only_action_too_old = (
                ('action is too old' in output.lower() or 'is too old to run' in output.lower()) and
                not has_syntax_error and
                not has_expression_error and
                not has_type_error and
                not has_runner_label_error
            )
            
            # Check for shellcheck info-only (also non-blocking)
            is_only_shellcheck_info = (
                ':info:' in output.lower() and 
                '[shellcheck]' in output and
                not has_syntax_error and
                not has_expression_error and
                not has_type_error and
                not has_runner_label_error and
                not has_action_error
            )
            
            # Only these specific cases are non-blocking
            if is_only_action_too_old or is_only_shellcheck_info:
                severity_note = "\n\n[Note: Non-blocking warnings found. Consider updating action versions to @v4.]"
                return True, (output.strip() + severity_note)
            
            # Everything else fails
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
        # Double check fields will be populated by _semantic_double_check
        doubleCheckOk=None,
        doubleCheckReasons=None,
        doubleCheckSkipped=not (yaml_ok and actionlint_ok),  # Skip if YAML/lint failed
    )


def _semantic_double_check(
    *,
    source_config: str,
    generated_config: str,
    source_ci: str,
    target_ci: str,
    provider: str,
    model: str,
    base_url: str | None = None,
    api_key: str | None = None,
) -> tuple[bool, list[str]]:
    """
    Perform agentic semantic verification of CI/CD migration.
    
    Returns:
        tuple[bool, list[str]]: (passed, reasons)
    """
    print(f"[DOUBLE-CHECK] Starting semantic verification with {provider}/{model}")
    
    result = semantic_verify_migration(
        provider=provider,
        model=model,
        source_config=source_config,
        generated_config=generated_config,
        source_ci=source_ci,
        target_ci=target_ci,
        base_url=base_url,
        api_key=api_key,
    )
    
    passed = result.get("passed", False)
    reasons = result.get("reasons", [])
    missing = result.get("missing_features", [])
    hallucinated = result.get("hallucinated_steps", [])
    confidence = result.get("confidence", 0.0)
    
    # Filter out allowed additions that shouldn't be considered hallucinations
    allowed_additions = [
        'actions/checkout', 'checkout', 'actions/checkout@v4', 'actions/checkout@v3',
        'actions/setup-', 'setup-node', 'setup-python', 'setup-java', 'setup-go',
    ]
    filtered_hallucinated = [
        h for h in hallucinated 
        if not any(allowed.lower() in h.lower() for allowed in allowed_additions)
    ]
    
    # If hallucinations were filtered out, update passed status
    if hallucinated and not filtered_hallucinated:
        print(f"[DOUBLE-CHECK] Filtered out allowed additions from hallucinated list: {hallucinated}")
        passed = True  # Override to pass since remaining issues were allowed additions
    
    print(f"[DOUBLE-CHECK] Result: passed={passed}, confidence={confidence}")
    print(f"[DOUBLE-CHECK] Reasons: {reasons}")
    if missing:
        print(f"[DOUBLE-CHECK] Missing features: {missing}")
    if filtered_hallucinated:
        print(f"[DOUBLE-CHECK] Additional steps not in source: {filtered_hallucinated}")
    
    # Build user-friendly reasons (avoid "HALLUCINATED" terminology)
    all_reasons = list(reasons)
    if filtered_hallucinated:
        all_reasons.append(f"Additional steps not in source: {', '.join(filtered_hallucinated)}")
    if missing:
        all_reasons.append(f"Missing from source: {', '.join(missing)}")
        # If there are missing features, we should fail the check
        if not filtered_hallucinated:
            # Only fail for missing features if they seem significant
            significant_missing = [m for m in missing if any(kw in m.lower() for kw in ['docker', 'container', 'image', 'service', 'environment', 'env', 'command', 'script', 'step'])]
            if significant_missing:
                print(f"[DOUBLE-CHECK] Significant missing features detected, failing: {significant_missing}")
                passed = False
    if confidence > 0:
        all_reasons.append(f"Confidence: {confidence:.0%}")
    
    return passed, all_reasons


def _detect_ci_platform(yaml_content: str, file_path: Optional[str] = None) -> List[str]:
    """
    Detect CI/CD platform from YAML content based on keywords and structure.
    Returns a list of detected platform names.
    """
    detected = []
    content_lower = yaml_content.lower()
    
    # GitHub Actions detection
    github_indicators = [
        'runs-on:', 'uses:', 'github.event', 'workflow_dispatch',
        'pull_request:', 'push:', 'jobs:', 'steps:'
    ]
    if (file_path and '.github/workflows' in file_path) or \
       any(ind in content_lower for ind in github_indicators[:4]):
        # Check for common GitHub Actions patterns
        if 'jobs:' in content_lower and ('runs-on:' in content_lower or 'uses:' in content_lower):
            detected.append('GitHub Actions')
    
    # Travis CI detection
    travis_indicators = [
        'travis', 'dist:', 'sudo:', 'language:', 'before_install:',
        'before_script:', 'script:', 'after_success:', 'deploy:'
    ]
    if (file_path and '.travis.yml' in file_path) or \
       (any(ind in content_lower for ind in travis_indicators) and 'language:' in content_lower):
        detected.append('Travis CI')
    
    # CircleCI detection
    circleci_indicators = [
        'version: 2', 'circleci', 'orbs:', 'executors:',
        'docker:', 'machine:', 'macos:', 'workflows:'
    ]
    if (file_path and '.circleci/config' in file_path) or \
       ('version:' in content_lower and any(ind in content_lower for ind in circleci_indicators)):
        if 'jobs:' in content_lower and 'docker:' in content_lower:
            detected.append('CircleCI')
    
    # GitLab CI detection
    gitlab_indicators = [
        'gitlab', 'stages:', 'image:', 'before_script:',
        'script:', 'artifacts:', 'cache:', '.gitlab-ci'
    ]
    if (file_path and '.gitlab-ci.yml' in file_path) or \
       ('stages:' in content_lower and 'script:' in content_lower):
        detected.append('GitLab CI')
    
    # Jenkins detection (Jenkinsfile)
    jenkins_indicators = [
        'pipeline', 'agent', 'stages', 'stage(', 'steps {',
        'sh ', 'bat ', 'echo ', 'jenkinsfile'
    ]
    if (file_path and 'jenkinsfile' in file_path.lower()) or \
       ('pipeline' in content_lower and 'agent' in content_lower and 'stages' in content_lower):
        detected.append('Jenkins')
    
    # Azure Pipelines detection
    azure_indicators = [
        'trigger:', 'pool:', 'vmimage:', 'azure-pipelines',
        'stages:', 'jobs:', 'steps:', 'task:'
    ]
    if (file_path and 'azure-pipelines' in file_path.lower()) or \
       ('pool:' in content_lower and 'vmimage:' in content_lower):
        detected.append('Azure Pipelines')
    
    # Bitbucket Pipelines detection  
    bitbucket_indicators = [
        'bitbucket-pipelines', 'pipelines:', 'default:', 'step:'
    ]
    if (file_path and 'bitbucket-pipelines' in file_path.lower()) or \
       ('pipelines:' in content_lower and 'step:' in content_lower):
        detected.append('Bitbucket Pipelines')
    
    return detected if detected else ['Unknown']


@app.post("/detect-ci", response_model=DetectionResponse)
async def detect_ci(request: DetectionRequest, http_request: Request, background_tasks: BackgroundTasks):
    """Detect CI platform from YAML content"""
    start_time = time.time()
    analytics_ctx = _get_analytics_context(http_request)
    
    # Use pre-detected services from frontend if provided, otherwise detect from YAML
    detected_platforms = request.detected_services if request.detected_services else _detect_ci_platform(request.yaml_content, request.file_path)
    processing_time_ms = int((time.time() - start_time) * 1000)
    
    # Get or create session with 30-min timeout tracking
    user_id, session_id = await _get_or_create_session(analytics_ctx)
    
    # Log detection to dedicated detection_logs table (in background)
    background_tasks.add_task(
        analytics_service.log_detection,
        user_id=user_id,
        session_id=session_id,
        repo_owner=request.repo_owner,
        repo_name=request.repo_name,
        repo_branch=request.repo_branch,
        detected_services=detected_platforms,
        detection_count=len([p for p in detected_platforms if p != 'Unknown']),
        detection_source='api',
        detection_data={
            'file_path': request.file_path,
            'yaml_length': len(request.yaml_content),
            'processing_time_ms': processing_time_ms,
        }
    )
    
    return DetectionResponse(
        detected_platforms=detected_platforms,
        confidence=0.9 if 'Unknown' not in detected_platforms else 0.3,
        file_path=request.file_path,
    )


@app.post("/validate-github-actions", response_model=ValidationResult)
async def validate_github_actions(request: ValidateGithubActionsRequest):
    print(f"[VALIDATE] Received request - yaml length: {len(request.yaml)}, has originalConfig: {bool(request.originalConfig)}, has llmSettings: {bool(request.llmSettings)}")
    
    validation = _validate_github_actions_yaml(request.yaml)
    print(f"[VALIDATE] YAML ok: {validation.yamlOk}, Lint ok: {validation.actionlintOk}")
    
    # Agentic Double Check - only if YAML/lint passed AND we have original config
    if validation.yamlOk and validation.actionlintOk and request.originalConfig:
        llm = request.llmSettings
        provider = (llm.provider if llm else 'ollama')
        model = (llm.model if llm else 'gemma3:12b')
        base_url = (llm.baseUrl if llm else None)
        api_key = (llm.apiKey if llm else None)
        
        print(f"[VALIDATE DOUBLE-CHECK] Running semantic verification with {provider}/{model}...")
        double_check_ok, double_check_reasons = _semantic_double_check(
            source_config=request.originalConfig,
            generated_config=request.yaml,
            source_ci="Original CI",
            target_ci="github-actions",
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
        validation.doubleCheckOk = double_check_ok
        validation.doubleCheckReasons = double_check_reasons
        validation.doubleCheckSkipped = False
        print(f"[VALIDATE DOUBLE-CHECK] Result: passed={double_check_ok}")
    elif not (validation.yamlOk and validation.actionlintOk):
        print(f"[VALIDATE] Skipping Double Check - YAML/lint failed")
        validation.doubleCheckSkipped = True
    else:
        print(f"[VALIDATE] Skipping Double Check - no originalConfig provided")
        validation.doubleCheckSkipped = True
    
    return validation


@app.post("/retry-conversion", response_model=ConversionResponse)
async def retry_conversion(request: RetryConversionRequest, http_request: Request):
    """Endpoint to retry conversion with user feedback"""
    analytics_ctx = _get_analytics_context(http_request)
    
    # Get or create session with 30-min timeout tracking
    user_id, session_id = await _get_or_create_session(analytics_ctx)
    
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
            
            # Agentic Double Check - only if YAML and lint both passed
            if validation.yamlOk and validation.actionlintOk:
                print("[RETRY DOUBLE-CHECK] YAML and lint passed, performing semantic verification...")
                double_check_ok, double_check_reasons = _semantic_double_check(
                    source_config=request.originalTravisConfig,
                    generated_config=converted,
                    source_ci="Original CI",
                    target_ci=request.targetPlatform,
                    provider=provider,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                )
                validation.doubleCheckOk = double_check_ok
                validation.doubleCheckReasons = double_check_reasons
                validation.doubleCheckSkipped = False
            else:
                validation.doubleCheckSkipped = True

        # Increment attempts from the request
        current_attempts = (request.currentAttempts or 1) + 1
        
        print(f"[RETRY] Previous attempts: {request.currentAttempts}, New attempts: {current_attempts}")
        
        # Determine final status for analytics
        final_status = "success"
        if validation:
            if not validation.yamlOk:
                final_status = "failed"
            elif not validation.actionlintOk:
                final_status = "partial"
            elif validation.doubleCheckOk is False:
                final_status = "partial"
        
        # Log retry analytics in background
        analytics_service.log_migration_background(
            user_id=user_id,
            session_id=session_id,
            repo_owner=None,  # Not available in retry request
            repo_name=None,
            repo_branch=None,
            source_ci_services=['travis-ci'],
            target_platform=request.targetPlatform,
            source_yaml=request.originalTravisConfig,
            converted_yaml=converted,
            provider_used=provider,
            model_used=model,
            attempts=current_attempts,
            validation_yaml_ok=validation.yamlOk if validation else None,
            validation_lint_ok=validation.actionlintOk if validation else None,
            validation_double_check_ok=validation.doubleCheckOk if validation else None,
            final_status=final_status,
        )

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
async def convert_cicd(request: ConversionRequest, http_request: Request, background_tasks: BackgroundTasks):
    """Endpoint to convert CI/CD configurations"""
    start_time = time.time()
    analytics_ctx = _get_analytics_context(http_request)
    
    # Get or create session with 30-min timeout tracking
    user_id, session_id = await _get_or_create_session(analytics_ctx)

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
        
        # Use LangGraph agentic pipeline for conversion with automatic retry
        if target_platform == 'github-actions':
            print("[LANGGRAPH] Using agentic pipeline for GitHub Actions conversion")
            
            result = run_conversion_pipeline(
                source_config=pipeline_content,
                source_ci=src_display_name,
                target_ci=target_platform,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                max_attempts=3,
            )
            
            converted = result['generated_yaml']
            attempts = result['attempts']
            
            validation = ValidationResult(
                yamlOk=result['yaml_ok'],
                yamlError=result['yaml_error'],
                actionlintOk=result['actionlint_ok'],
                actionlintOutput=result['actionlint_output'],
                doubleCheckOk=result['double_check_ok'],
                doubleCheckReasons=result['double_check_reasons'],
                doubleCheckSkipped=result['double_check_skipped'],
            )
        else:
            # Non-GitHub Actions target - use simple conversion (no LangGraph)
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
        
        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Determine final status
        final_status = "success"
        if validation:
            if not validation.yamlOk:
                final_status = "failed"
            elif not validation.actionlintOk:
                final_status = "partial"
            elif validation.doubleCheckOk is False:
                final_status = "partial"
        
        # Log analytics in background (fire and forget - won't slow down response)
        background_tasks.add_task(
            analytics_service.log_migration,
            user_id=user_id,
            session_id=session_id,
            repo_owner=request.repository.owner,
            repo_name=request.repository.name,
            repo_branch=request.repository.branch,
            source_ci_services=request.detectedServices,
            target_platform=target_platform,
            source_yaml=pipeline_content,  # Store source YAML
            converted_yaml=converted,  # Store converted YAML
            provider_used=provider,  # Just the name, no API key
            model_used=model,
            attempts=attempts,
            validation_yaml_ok=validation.yamlOk if validation else None,
            validation_lint_ok=validation.actionlintOk if validation else None,
            validation_double_check_ok=validation.doubleCheckOk if validation else None,
            final_status=final_status,
            processing_time_ms=processing_time_ms,
        )
            
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


# Analytics endpoints
@app.get("/analytics/health")
async def analytics_health():
    """Check if analytics service is healthy"""
    healthy = await analytics_service.health_check()
    return {
        "status": "healthy" if healthy else "unavailable",
        "service": "analytics",
    }


@app.get("/analytics/stats")
async def analytics_stats():
    """Get aggregated migration statistics (for admin/dashboard)"""
    stats = await analytics_service.get_stats()
    return stats


@app.post("/analytics/session")
async def create_analytics_session(http_request: Request):
    """
    Create a new analytics session for tracking.
    Called from frontend when user first visits.
    Returns session_id to be used in subsequent requests.
    """
    analytics_ctx = _get_analytics_context(http_request)
    user_id = analytics_ctx.get('user_id')
    
    if not user_id:
        return {"error": "X-Analytics-User-ID header required", "session_id": None}
    
    # Ensure user exists
    await analytics_service.get_or_create_user(user_id)
    
    # Create session
    session_id = await analytics_service.create_session(
        user_id=user_id,
        ip_address=analytics_ctx.get('ip_address'),
        user_agent=analytics_ctx.get('user_agent'),
        country=analytics_ctx.get('country'),
        timezone=analytics_ctx.get('timezone'),
        referrer=analytics_ctx.get('referrer'),
    )
    
    return {"session_id": session_id, "user_id": user_id}
        

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5200, reload=True) 