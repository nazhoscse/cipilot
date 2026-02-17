"""
Pipeline Runner - Orchestrates the batch migration process
"""
import asyncio
import time
from datetime import datetime
from typing import List, Optional, Set
from pathlib import Path
import threading
import sys

# Handle both module and script imports
if __name__ == "__main__" or "." not in __name__:
    from config import PipelineConfig, StrictnessLevel
    from models import (
        RepoInput, RepoResult, PipelineStats, StageStatus,
        DetectionResult, MigrationResult, ValidationResult,
        DoubleCheckResult, PullRequestResult
    )
    from stages.detect import detect_ci, check_rate_limit
    from stages.migrate import migrate_ci
    from stages.validate import validate_yaml
    from stages.double_check import semantic_double_check
    from stages.pull_request import create_pull_request
    from reporters.csv_reporter import CSVReporter
    from reporters.console_progress import ConsoleProgress
else:
    from .config import PipelineConfig, StrictnessLevel
    from .models import (
        RepoInput, RepoResult, PipelineStats, StageStatus,
        DetectionResult, MigrationResult, ValidationResult,
        DoubleCheckResult, PullRequestResult
    )
    from .stages import detect_ci, migrate_ci, validate_yaml, semantic_double_check, create_pull_request
    from .stages.detect import check_rate_limit
    from .reporters import CSVReporter, ConsoleProgress


class PATRotator:
    """Manages multiple GitHub PATs with automatic rotation on rate limit"""
    
    def __init__(self, pats: List[str]):
        self.pats = pats
        self.current_index = 0
        self._lock = threading.Lock()
        self._rate_limited: Set[int] = set()
    
    def get_pat(self) -> Optional[str]:
        """Get current PAT, rotating if needed"""
        with self._lock:
            if not self.pats:
                return None
            
            # Find a non-rate-limited PAT
            attempts = 0
            while attempts < len(self.pats):
                if self.current_index not in self._rate_limited:
                    return self.pats[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.pats)
                attempts += 1
            
            # All rate limited, clear and try again
            self._rate_limited.clear()
            return self.pats[self.current_index]
    
    def mark_rate_limited(self):
        """Mark current PAT as rate limited and rotate"""
        with self._lock:
            self._rate_limited.add(self.current_index)
            self.current_index = (self.current_index + 1) % len(self.pats)
    
    def check_and_rotate_if_needed(self) -> bool:
        """Check rate limit and rotate if low. Returns True if ok to proceed."""
        pat = self.get_pat()
        if not pat:
            return False
        
        remaining, reset_time = check_rate_limit(pat)
        
        if remaining < 100:  # Low on requests
            self.mark_rate_limited()
            # Check if we have another PAT
            new_pat = self.get_pat()
            if new_pat != pat:
                return True
            # All PATs are low, wait a bit
            wait_time = max(0, reset_time - time.time())
            if wait_time > 0 and wait_time < 3600:  # Max 1 hour wait
                print(f"\n⏳ Rate limit low, waiting {int(wait_time)}s...")
                time.sleep(min(wait_time, 60))  # Wait max 60s at a time
        
        return True


class PipelineRunner:
    """Main pipeline orchestrator"""
    
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.pat_rotator = PATRotator(config.github_pats)
        self.csv_reporter: Optional[CSVReporter] = None
        self.progress: Optional[ConsoleProgress] = None
        self.results: List[RepoResult] = []
        self._stop_requested = False
    
    def load_repos(self, input_path: str) -> List[RepoInput]:
        """Load repositories from CSV or JSON file"""
        path = Path(input_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")
        
        repos: List[RepoInput] = []
        
        if path.suffix.lower() == ".json":
            import json
            with open(path, "r") as f:
                data = json.load(f)
            
            for item in data:
                if isinstance(item, str):
                    repos.append(RepoInput(repo_url=item))
                elif isinstance(item, dict):
                    repos.append(RepoInput(
                        repo_url=item.get("repo_url", item.get("url", "")),
                        target_branch=item.get("target_branch", self.config.target_branch)
                    ))
        else:
            # Assume CSV
            import csv
            with open(path, "r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    repo_url = row.get("repo_url", row.get("url", row.get("repo", "")))
                    if repo_url:
                        repos.append(RepoInput(
                            repo_url=repo_url.strip(),
                            target_branch=row.get("target_branch", self.config.target_branch)
                        ))
        
        return repos
    
    def run(self, repos: List[RepoInput]) -> List[RepoResult]:
        """Run the pipeline on all repos"""
        
        # Setup CSV reporter
        self.csv_reporter = CSVReporter(
            self.config.output_file,
            include_yaml_content=True
        )
        
        # Handle resume
        processed_repos: Set[str] = set()
        if self.config.resume:
            processed_repos = self.csv_reporter.load_processed_repos()
            print(f"📂 Resuming: {len(processed_repos)} repos already processed")
            repos = [r for r in repos if r.repo_url not in processed_repos]
        
        if not repos:
            print("✅ All repos already processed!")
            return []
        
        # Initialize CSV (creates headers if new file)
        self.csv_reporter.initialize()
        
        # Setup progress display
        self.progress = ConsoleProgress(len(repos))
        
        # Process repos
        if self.config.max_concurrent > 1:
            # Parallel processing
            asyncio.run(self._run_parallel(repos))
        else:
            # Sequential processing
            self._run_sequential(repos)
        
        # Show final summary
        if self.progress:
            self.progress.finish()
        
        return self.results
    
    def _run_sequential(self, repos: List[RepoInput]):
        """Process repos one at a time"""
        for repo in repos:
            if self._stop_requested:
                break
            
            # _process_repo now returns a LIST (one result per detected CI)
            results_for_repo = self._process_repo(repo)
            self.results.extend(results_for_repo)
            
            # CSV writing is now done inside _process_repo per CI config
            # Update progress for each result
            if self.progress:
                for result in results_for_repo:
                    self.progress.complete_repo(result.overall_status)
    
    async def _run_parallel(self, repos: List[RepoInput]):
        """Process repos in parallel with concurrency limit"""
        semaphore = asyncio.Semaphore(self.config.max_concurrent)
        
        async def process_with_semaphore(repo: RepoInput) -> List[RepoResult]:
            async with semaphore:
                # Run in thread pool to not block
                loop = asyncio.get_event_loop()
                results_for_repo = await loop.run_in_executor(None, self._process_repo, repo)
                
                # CSV writing is done inside _process_repo
                # Update progress for each result
                if self.progress:
                    for result in results_for_repo:
                        self.progress.complete_repo(result.overall_status)
                
                return results_for_repo
        
        tasks = [process_with_semaphore(repo) for repo in repos]
        nested_results = await asyncio.gather(*tasks)
        # Flatten list of lists
        self.results = [r for results_list in nested_results for r in results_list]
    
    def _process_repo(self, repo: RepoInput) -> List[RepoResult]:
        """
        Process a single repository through all stages.
        Returns a LIST of results - one per detected CI config.
        Each CI config gets its own migration and PR.
        """
        results: List[RepoResult] = []
        
        try:
            # Check PAT availability
            pat = self.pat_rotator.get_pat()
            if not pat:
                # Return single failure result
                result = RepoResult(input=repo)
                result.started_at = datetime.now()
                result.overall_status = "failed"
                result.error_message = "No GitHub PAT available"
                return [self._finalize_result(result)]
            
            # Check rate limit
            self.pat_rotator.check_and_rotate_if_needed()
            pat = self.pat_rotator.get_pat()
            
            # Stage 1: Detection (finds ALL CI configs)
            if self.progress:
                self.progress.update_current(repo.full_name, "detecting")
            
            detection_result = detect_ci(
                repo=repo,
                github_pat=pat,
                retries=self.config.max_retries,
                retry_delay=self.config.retry_delay_seconds
            )
            
            if detection_result.status == StageStatus.FAILED:
                if self.progress:
                    self.progress.increment_stat("detection_failed")
                result = RepoResult(input=repo)
                result.started_at = datetime.now()
                result.detection = detection_result
                result.overall_status = "failed"
                result.error_message = detection_result.error
                return [self._finalize_result(result)]
            
            if not detection_result.detected_configs:
                if self.progress:
                    self.progress.increment_stat("no_ci_found")
                result = RepoResult(input=repo)
                result.started_at = datetime.now()
                result.detection = detection_result
                result.overall_status = "failed"
                result.error_message = "No CI configuration found"
                return [self._finalize_result(result)]
            
            # Found CI configs - process EACH one separately
            num_configs = len(detection_result.detected_configs)
            if self.progress:
                self.progress.increment_stat("detected", num_configs)
            
            for config in detection_result.detected_configs:
                ci_result = self._process_single_ci(
                    repo=repo,
                    ci_config=config,
                    all_detected=[c.ci_type for c in detection_result.detected_configs]
                )
                results.append(ci_result)
                
                # Write each result to CSV immediately
                if self.csv_reporter:
                    self.csv_reporter.write_result(ci_result)
            
            return results
            
        except Exception as e:
            result = RepoResult(input=repo)
            result.started_at = datetime.now()
            result.overall_status = "failed"
            result.error_message = str(e)
            return [self._finalize_result(result)]
    
    def _process_single_ci(self, repo: RepoInput, ci_config, all_detected: List[str]) -> RepoResult:
        """Process a single CI config for a repo through migrate → validate → double-check → PR"""
        from models import DetectedConfig, DetectionResult
        
        result = RepoResult(input=repo)
        result.started_at = datetime.now()
        
        # Store all detected CIs in this repo for CSV reference
        result.all_detected_in_repo = all_detected
        
        # Create detection result for this specific CI
        result.detection = DetectionResult(
            status=StageStatus.SUCCESS,
            detected_configs=[ci_config]
        )
        
        try:
            # Stage 2: Migration
            if self.progress:
                self.progress.update_current(f"{repo.full_name} ({ci_config.ci_type})", "migrating")
            
            result.migration = migrate_ci(
                source_yaml=ci_config.source_yaml,
                source_ci=ci_config.ci_type,
                target_ci="github-actions",
                config=self.config,
                retries=self.config.max_retries,
                retry_delay=self.config.retry_delay_seconds
            )
            
            if result.migration.status == StageStatus.FAILED:
                if self.progress:
                    self.progress.increment_stat("migration_failed")
                result.overall_status = "failed"
                result.error_message = result.migration.error
                return self._finalize_result(result)
            
            if self.progress:
                self.progress.increment_stat("migrated")
            
            # Stage 3: Validation (Linting)
            if self.progress:
                self.progress.update_current(f"{repo.full_name} ({ci_config.ci_type})", "validating")
            
            result.validation = validate_yaml(
                yaml_content=result.migration.migrated_yaml
            )
            
            lint_passed = result.validation.lint_valid
            if lint_passed:
                if self.progress:
                    self.progress.increment_stat("lint_passed")
            else:
                if self.progress:
                    self.progress.increment_stat("lint_failed")
            
            # Stage 4: Double-Check (if applicable)
            should_double_check = self.config.should_run_double_check(lint_passed)
            
            if should_double_check:
                if self.progress:
                    self.progress.update_current(f"{repo.full_name} ({ci_config.ci_type})", "double-check")
                
                result.double_check = semantic_double_check(
                    source_yaml=ci_config.source_yaml,
                    migrated_yaml=result.migration.migrated_yaml,
                    source_ci=ci_config.ci_type,
                    target_ci="github-actions",
                    config=self.config,
                    retries=self.config.max_retries,
                    retry_delay=self.config.retry_delay_seconds
                )
                
                if result.double_check.passed:
                    if self.progress:
                        self.progress.increment_stat("double_check_passed")
                else:
                    if self.progress:
                        self.progress.increment_stat("double_check_failed")
            else:
                result.double_check.status = StageStatus.SKIPPED
                if self.progress:
                    self.progress.increment_stat("double_check_skipped")
            
            # Stage 5: Pull Request (if applicable)
            # Branch name includes CI type to avoid conflicts: cipilot/migrated-travis-to-gha
            double_check_passed = result.double_check.passed or result.double_check.status == StageStatus.SKIPPED
            should_create_pr = self.config.should_create_pr(lint_passed, double_check_passed)
            
            if should_create_pr:
                if self.progress:
                    self.progress.update_current(f"{repo.full_name} ({ci_config.ci_type})", "creating PR")
                
                # Get fresh PAT
                pat = self.pat_rotator.get_pat()
                
                result.pull_request = create_pull_request(
                    repo=repo,
                    migrated_yaml=result.migration.migrated_yaml,
                    source_ci=ci_config.ci_type,
                    github_pat=pat,
                    branch_prefix=self.config.pr_branch_prefix,
                    retries=self.config.max_retries,
                    retry_delay=self.config.retry_delay_seconds,
                    dry_run=(self.config.strictness == StrictnessLevel.DRY_RUN)
                )
                
                if result.pull_request.status == StageStatus.SUCCESS:
                    if self.progress:
                        self.progress.increment_stat("prs_created")
                elif result.pull_request.status == StageStatus.SKIPPED:
                    if self.progress:
                        self.progress.increment_stat("prs_skipped")
                else:
                    if self.progress:
                        self.progress.increment_stat("prs_failed")
            else:
                result.pull_request.status = StageStatus.SKIPPED
                reason_parts = []
                if not lint_passed:
                    reason_parts.append("lint failed")
                if not double_check_passed:
                    reason_parts.append("double-check failed")
                if self.config.strictness == StrictnessLevel.DRY_RUN:
                    reason_parts.append("dry run mode")
                result.pull_request.skipped_reason = ", ".join(reason_parts) if reason_parts else "config"
                
                if self.progress:
                    self.progress.increment_stat("prs_skipped")
            
            # Determine overall status
            if result.pull_request.status == StageStatus.SUCCESS:
                result.overall_status = "success"
            elif lint_passed and (double_check_passed or not should_double_check):
                result.overall_status = "partial"  # Migration OK but no PR
            else:
                result.overall_status = "partial"
            
        except Exception as e:
            result.overall_status = "failed"
            result.error_message = str(e)
        
        return self._finalize_result(result)
    
    def _finalize_result(self, result: RepoResult) -> RepoResult:
        """Finalize result with timing"""
        result.completed_at = datetime.now()
        if result.started_at:
            result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
        return result
    
    def stop(self):
        """Request pipeline stop"""
        self._stop_requested = True
