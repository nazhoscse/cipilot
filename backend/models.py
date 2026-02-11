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


class ConversionRequest(BaseModel):
    repository: Repository
    detectedServices: List[str]
    existingConfigs: Optional[Dict[str, Any]] = {}
    targetPlatform: Optional[str] = None  # github-actions | travis-ci
    llmSettings: Optional[LLMSettings] = None


class ValidateGithubActionsRequest(BaseModel):
    yaml: str


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