"""
CSV Reporter - Write results to CSV file
"""
import csv
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import RepoResult, RepoInput


class CSVReporter:
    """Handles CSV output for pipeline results"""
    
    # Core columns (always present)
    CORE_COLUMNS = [
        "repo_url",
        "repo_full_name", 
        "target_branch",
        "detected_ci",
        "all_detected_ci",
        "detection_status",
        "source_path",
        "migration_status",
        "migration_attempts",
        "yaml_valid",
        "lint_valid",
        "lint_errors",
        "validation_status",
        "double_check_status",
        "double_check_passed",
        "double_check_confidence",
        "double_check_reasons",
        "missing_features",
        "hallucinated_steps",
        "pr_status",
        "pr_url",
        "pr_number",
        "pr_skipped_reason",
        "pr_error",
        "fork_url",
        "branch_name",
        "overall_status",
        "error_message",
        "duration_seconds",
        "started_at",
        "completed_at",
    ]
    
    # Extended columns (large content, optional)
    EXTENDED_COLUMNS = [
        "source_yaml",
        "migrated_yaml",
        "fork_url",
        "branch_name",
        "source_yaml_length",
        "migrated_yaml_length",
    ]
    
    def __init__(
        self,
        output_path: str,
        include_yaml_content: bool = False,
    ):
        self.output_path = Path(output_path)
        self.include_yaml_content = include_yaml_content
        self._initialized = False
        self._processed_repos: Set[str] = set()
        
        # Select columns
        self.columns = self.CORE_COLUMNS.copy()
        if include_yaml_content:
            self.columns.extend(self.EXTENDED_COLUMNS)
    
    def initialize(self):
        """Initialize CSV file with headers"""
        if self._initialized:
            return
        
        # Create parent directory if needed
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write headers
        with open(self.output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.columns, extrasaction="ignore")
            writer.writeheader()
        
        self._initialized = True
    
    def write_result(self, result: RepoResult):
        """Append a single result to CSV"""
        if not self._initialized:
            self.initialize()
        
        row = result.to_csv_row()
        
        # Track processed repos
        self._processed_repos.add(result.input.repo_url)
        
        with open(self.output_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.columns, extrasaction="ignore")
            writer.writerow(row)
    
    def write_results(self, results: List[RepoResult]):
        """Write multiple results"""
        for result in results:
            self.write_result(result)
    
    def load_processed_repos(self) -> Set[str]:
        """Load already processed repos from existing CSV (for resume)"""
        if not self.output_path.exists():
            return set()
        
        processed = set()
        try:
            with open(self.output_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    repo_url = row.get("repo_url", "")
                    if repo_url:
                        processed.add(repo_url)
        except Exception:
            pass
        
        return processed
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics from CSV"""
        if not self.output_path.exists():
            return {}
        
        stats = {
            "total": 0,
            "success": 0,
            "partial": 0,
            "failed": 0,
            "prs_created": 0,
        }
        
        try:
            with open(self.output_path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    stats["total"] += 1
                    status = row.get("overall_status", "")
                    if status == "success":
                        stats["success"] += 1
                    elif status == "partial":
                        stats["partial"] += 1
                    else:
                        stats["failed"] += 1
                    
                    if row.get("pr_url"):
                        stats["prs_created"] += 1
        except Exception:
            pass
        
        return stats


def create_detailed_yaml_csv(
    results: List[RepoResult],
    output_path: str
):
    """Create a separate CSV with full YAML content for detailed analysis"""
    columns = [
        "repo_full_name",
        "detected_ci",
        "source_yaml",
        "migrated_yaml",
        "double_check_passed",
        "double_check_confidence",
    ]
    
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        
        for result in results:
            row = {
                "repo_full_name": result.input.full_name,
                "detected_ci": result.detection.detected_ci or "",
                "source_yaml": result.detection.source_yaml or "",
                "migrated_yaml": result.migration.migrated_yaml or "",
                "double_check_passed": result.double_check.passed,
                "double_check_confidence": result.double_check.confidence,
            }
            writer.writerow(row)
