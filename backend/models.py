from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class Repository(BaseModel):
    owner: str
    name: str
    branch: str = "main"


class LLMSettings(BaseModel):
    provider: str = "ollama"  # ollama | openai | xai | groq
    model: str = "gemma3:12b"
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None


class ValidationResult(BaseModel):
    yamlOk: bool
    yamlError: Optional[str] = None
    actionlintOk: bool
    actionlintOutput: Optional[str] = None
    # Agentic Double Check - semantic verification by LLM
    doubleCheckOk: Optional[bool] = None
    doubleCheckReasons: Optional[List[str]] = None
    doubleCheckSkipped: Optional[bool] = None  # True if YAML/lint failed


class ConversionRequest(BaseModel):
    repository: Repository
    detectedServices: List[str]
    existingConfigs: Optional[Dict[str, Any]] = {}
    targetPlatform: Optional[str] = None  # github-actions | travis-ci
    llmSettings: Optional[LLMSettings] = None


class ValidateGithubActionsRequest(BaseModel):
    yaml: str
    originalConfig: Optional[str] = None  # For Double Check semantic verification
    llmSettings: Optional[LLMSettings] = None


class RetryConversionRequest(BaseModel):
    originalTravisConfig: str
    previousGitHubActionsAttempt: str
    targetPlatform: str
    feedback: str
    llmSettings: Optional[LLMSettings] = None
    currentAttempts: Optional[int] = 1
    
class ConversionResponse(BaseModel):
    status: str
    message: str
    convertedConfig: str
    originalServices: List[str]
    targetPlatform: str
    providerUsed: Optional[str] = None
    modelUsed: Optional[str] = None
    attempts: int = 1
    validation: Optional[ValidationResult] = None


class DetectionRequest(BaseModel):
    """Request to detect CI platform from YAML content"""
    yaml_content: str
    file_path: Optional[str] = None  # Optional file path for context
    repo_owner: Optional[str] = None
    repo_name: Optional[str] = None
    repo_branch: Optional[str] = None
    detected_services: Optional[List[str]] = None  # Pre-detected service names from frontend


class DetectionResponse(BaseModel):
    """Response with detected CI platform(s)"""
    detected_platforms: List[str]
    confidence: Optional[float] = None
    file_path: Optional[str] = None