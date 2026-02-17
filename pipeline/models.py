"""
Data models for pipeline processing
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class RepoInput:
    """Input repository to process"""
    repo_url: str
    target_branch: str = "main"
    
    @property
    def owner(self) -> str:
        """Extract owner from repo URL"""
        url = self.repo_url.replace("https://github.com/", "").replace("http://github.com/", "")
        parts = url.strip("/").split("/")
        return parts[0] if len(parts) >= 2 else ""
    
    @property
    def name(self) -> str:
        """Extract repo name from repo URL"""
        url = self.repo_url.replace("https://github.com/", "").replace("http://github.com/", "")
        parts = url.strip("/").split("/")
        return parts[1] if len(parts) >= 2 else url
    
    @property
    def full_name(self) -> str:
        """Get owner/repo format"""
        return f"{self.owner}/{self.name}"


@dataclass
class DetectionResult:
    """Result of CI detection stage"""
    status: StageStatus = StageStatus.PENDING
    detected_ci: Optional[str] = None
    source_yaml: Optional[str] = None
    source_path: Optional[str] = None
    error: Optional[str] = None
    all_detected: List[str] = field(default_factory=list)  # All CIs found


@dataclass
class MigrationResult:
    """Result of migration stage"""
    status: StageStatus = StageStatus.PENDING
    migrated_yaml: Optional[str] = None
    source_ci: Optional[str] = None
    target_ci: str = "github-actions"
    attempts: int = 0
    error: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of validation (lint) stage"""
    status: StageStatus = StageStatus.PENDING
    yaml_valid: bool = False
    lint_valid: bool = False
    lint_errors: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class DoubleCheckResult:
    """Result of semantic double-check stage"""
    status: StageStatus = StageStatus.PENDING
    passed: bool = False
    reasons: List[str] = field(default_factory=list)
    missing_features: List[str] = field(default_factory=list)
    hallucinated_steps: List[str] = field(default_factory=list)
    confidence: float = 0.0
    error: Optional[str] = None


@dataclass
class PullRequestResult:
    """Result of PR creation stage"""
    status: StageStatus = StageStatus.PENDING
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    fork_url: Optional[str] = None
    branch_name: Optional[str] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None


@dataclass
class RepoResult:
    """Complete result for a single repository"""
    input: RepoInput
    detection: DetectionResult = field(default_factory=DetectionResult)
    migration: MigrationResult = field(default_factory=MigrationResult)
    validation: ValidationResult = field(default_factory=ValidationResult)
    double_check: DoubleCheckResult = field(default_factory=DoubleCheckResult)
    pull_request: PullRequestResult = field(default_factory=PullRequestResult)
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    
    # Overall status
    overall_status: str = "pending"
    error_message: Optional[str] = None
    
    def to_csv_row(self) -> Dict[str, Any]:
        """Convert to CSV row dictionary"""
        return {
            "repo_url": self.input.repo_url,
            "repo_full_name": self.input.full_name,
            "target_branch": self.input.target_branch,
            
            # Detection
            "detected_ci": self.detection.detected_ci or "",
            "all_detected_ci": ",".join(self.detection.all_detected),
            "detection_status": self.detection.status.value,
            "source_path": self.detection.source_path or "",
            
            # Migration
            "migration_status": self.migration.status.value,
            "migration_attempts": self.migration.attempts,
            "source_yaml_length": len(self.detection.source_yaml or ""),
            "migrated_yaml_length": len(self.migration.migrated_yaml or ""),
            
            # Validation
            "yaml_valid": self.validation.yaml_valid,
            "lint_valid": self.validation.lint_valid,
            "lint_errors": "; ".join(self.validation.lint_errors),
            "validation_status": self.validation.status.value,
            
            # Double Check
            "double_check_status": self.double_check.status.value,
            "double_check_passed": self.double_check.passed,
            "double_check_confidence": self.double_check.confidence,
            "double_check_reasons": "; ".join(self.double_check.reasons),
            "missing_features": "; ".join(self.double_check.missing_features),
            "hallucinated_steps": "; ".join(self.double_check.hallucinated_steps),
            
            # Pull Request
            "pr_status": self.pull_request.status.value,
            "pr_url": self.pull_request.pr_url or "",
            "pr_number": self.pull_request.pr_number or "",
            "fork_url": self.pull_request.fork_url or "",
            "branch_name": self.pull_request.branch_name or "",
            "pr_skipped_reason": self.pull_request.skipped_reason or "",
            
            # Overall
            "overall_status": self.overall_status,
            "error_message": self.error_message or "",
            "duration_seconds": round(self.duration_seconds, 2),
            "started_at": self.started_at.isoformat() if self.started_at else "",
            "completed_at": self.completed_at.isoformat() if self.completed_at else "",
            
            # Full YAML content (for detailed analysis)
            "source_yaml": self.detection.source_yaml or "",
            "migrated_yaml": self.migration.migrated_yaml or "",
        }


@dataclass
class PipelineStats:
    """Aggregate statistics for the pipeline run"""
    total: int = 0
    processed: int = 0
    
    # Detection
    detected: int = 0
    no_ci_found: int = 0
    detection_failed: int = 0
    
    # Migration
    migrated: int = 0
    migration_failed: int = 0
    
    # Validation
    lint_passed: int = 0
    lint_failed: int = 0
    
    # Double Check
    double_check_passed: int = 0
    double_check_failed: int = 0
    double_check_skipped: int = 0
    
    # PRs
    prs_created: int = 0
    prs_skipped: int = 0
    prs_failed: int = 0
    
    # Overall
    success: int = 0
    partial: int = 0
    failed: int = 0
    
    # Timing
    start_time: Optional[datetime] = None
    elapsed_seconds: float = 0.0
    
    @property
    def remaining(self) -> int:
        return self.total - self.processed
    
    @property
    def progress_percent(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.processed / self.total) * 100
