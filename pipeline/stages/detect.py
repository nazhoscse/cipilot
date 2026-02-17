"""
CI Detection Stage - Detect CI/CD configurations in a repository
"""
import requests
from typing import Optional, Tuple, List, Dict
import base64

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import RepoInput, DetectionResult, StageStatus
from config import CI_DETECTION_PATTERNS


def detect_ci(
    repo: RepoInput,
    github_pat: str,
    retries: int = 3,
    retry_delay: int = 5
) -> DetectionResult:
    """
    Detect CI/CD configurations in a GitHub repository.
    
    Returns DetectionResult with detected CI type and source YAML.
    """
    result = DetectionResult()
    
    headers = {
        "Authorization": f"token {github_pat}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    all_detected: List[str] = []
    primary_ci: Optional[str] = None
    primary_yaml: Optional[str] = None
    primary_path: Optional[str] = None
    
    # Priority order for detection (prefer non-GitHub Actions)
    priority_order = [
        "circleci", "travis", "gitlab", "jenkins", "azure-pipelines",
        "bitbucket", "drone", "semaphore", "buildkite", "appveyor", "codefresh"
    ]
    
    for attempt in range(retries):
        try:
            # Check each CI pattern
            for ci_type, patterns in CI_DETECTION_PATTERNS.items():
                # Skip GitHub Actions - we're migrating TO it
                if ci_type == "github-actions":
                    continue
                
                for pattern in patterns:
                    try:
                        if pattern.endswith("/"):
                            # It's a directory, list contents
                            dir_path = pattern.rstrip("/")
                            url = f"https://api.github.com/repos/{repo.full_name}/contents/{dir_path}"
                            resp = requests.get(url, headers=headers, timeout=30)
                            
                            if resp.status_code == 200:
                                files = resp.json()
                                for f in files:
                                    if f.get("name", "").endswith((".yml", ".yaml")):
                                        # Found a YAML file in the directory
                                        file_url = f.get("download_url")
                                        if file_url:
                                            file_resp = requests.get(file_url, headers=headers, timeout=30)
                                            if file_resp.status_code == 200:
                                                if ci_type not in all_detected:
                                                    all_detected.append(ci_type)
                                                if primary_ci is None or priority_order.index(ci_type) < priority_order.index(primary_ci) if primary_ci in priority_order else True:
                                                    primary_ci = ci_type
                                                    primary_yaml = file_resp.text
                                                    primary_path = f"{dir_path}/{f.get('name')}"
                                                break
                        else:
                            # It's a file
                            url = f"https://api.github.com/repos/{repo.full_name}/contents/{pattern}"
                            resp = requests.get(url, headers=headers, timeout=30)
                            
                            if resp.status_code == 200:
                                content_data = resp.json()
                                content_b64 = content_data.get("content", "")
                                if content_b64:
                                    content = base64.b64decode(content_b64).decode("utf-8")
                                    if ci_type not in all_detected:
                                        all_detected.append(ci_type)
                                    if primary_ci is None or (ci_type in priority_order and (primary_ci not in priority_order or priority_order.index(ci_type) < priority_order.index(primary_ci))):
                                        primary_ci = ci_type
                                        primary_yaml = content
                                        primary_path = pattern
                                        
                    except Exception as e:
                        # Individual file check failed, continue
                        continue
            
            # If we found something, return success
            if primary_ci:
                result.status = StageStatus.SUCCESS
                result.detected_ci = primary_ci
                result.source_yaml = primary_yaml
                result.source_path = primary_path
                result.all_detected = all_detected
                return result
            
            # No CI found
            result.status = StageStatus.SUCCESS  # Detection succeeded, just nothing found
            result.detected_ci = None
            result.all_detected = all_detected
            result.error = "No CI configuration found"
            return result
            
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                import time
                time.sleep(retry_delay)
                continue
            result.status = StageStatus.FAILED
            result.error = f"GitHub API error after {retries} attempts: {str(e)}"
            return result
        except Exception as e:
            result.status = StageStatus.FAILED
            result.error = f"Detection error: {str(e)}"
            return result
    
    return result


def check_rate_limit(github_pat: str) -> Tuple[int, int]:
    """
    Check GitHub API rate limit.
    Returns (remaining, reset_timestamp)
    """
    headers = {
        "Authorization": f"token {github_pat}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    try:
        resp = requests.get("https://api.github.com/rate_limit", headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            core = data.get("resources", {}).get("core", {})
            return core.get("remaining", 0), core.get("reset", 0)
    except:
        pass
    
    return 0, 0
