"""
Pull Request Stage - Create migration PR via fork
"""
import requests
import time
import base64
from typing import Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import RepoInput, PullRequestResult, StageStatus


def create_pull_request(
    repo: RepoInput,
    migrated_yaml: str,
    source_ci: str,
    github_pat: str,
    branch_prefix: str = "cipilot/migrated",
    retries: int = 3,
    retry_delay: int = 5,
    dry_run: bool = False,
) -> PullRequestResult:
    """
    Create a PR with migrated workflow:
    1. Fork the repository (if not already forked)
    2. Create a new branch
    3. Add/update the workflow file
    4. Create PR from fork to original
    
    Reuses same logic as backend GitHub API calls.
    """
    result = PullRequestResult()
    
    if dry_run:
        result.status = StageStatus.SKIPPED
        result.skipped_reason = "Dry run mode - PR not created"
        result.branch_name = f"{branch_prefix}-{source_ci}-to-gha"
        return result
    
    headers = {
        "Authorization": f"token {github_pat}",
        "Accept": "application/vnd.github.v3+json",
    }
    
    # Get authenticated user
    user_resp = requests.get("https://api.github.com/user", headers=headers, timeout=30)
    if user_resp.status_code != 200:
        result.status = StageStatus.FAILED
        result.error = f"Failed to get authenticated user: {user_resp.text}"
        return result
    
    username = user_resp.json().get("login")
    
    for attempt in range(retries):
        try:
            # Step 1: Fork the repository
            fork_owner, fork_error = _ensure_fork(repo, username, headers)
            if not fork_owner:
                result.status = StageStatus.FAILED
                result.error = fork_error
                return result
            
            result.fork_url = f"https://github.com/{fork_owner}/{repo.name}"
            
            # Step 2: Get default branch SHA
            branch_sha, branch_error = _get_branch_sha(repo, fork_owner, repo.target_branch, headers)
            if not branch_sha:
                result.status = StageStatus.FAILED
                result.error = branch_error
                return result
            
            # Step 3: Create new branch
            branch_name = f"{branch_prefix}-{source_ci}-to-gha"
            result.branch_name = branch_name
            
            branch_created, branch_err = _create_branch(
                fork_owner, repo.name, branch_name, branch_sha, headers
            )
            if not branch_created:
                result.status = StageStatus.FAILED
                result.error = branch_err
                return result
            
            # Step 4: Create/update workflow file
            workflow_path = ".github/workflows/ci.yml"
            file_created, file_err = _create_or_update_file(
                fork_owner, repo.name, branch_name, workflow_path, migrated_yaml, headers
            )
            if not file_created:
                result.status = StageStatus.FAILED
                result.error = file_err
                return result
            
            # Step 5: Create PR
            pr_url, pr_number, pr_err = _create_pr(
                repo, fork_owner, username, branch_name, source_ci, headers
            )
            if not pr_url:
                result.status = StageStatus.FAILED
                result.error = pr_err
                return result
            
            result.status = StageStatus.SUCCESS
            result.pr_url = pr_url
            result.pr_number = pr_number
            return result
            
        except Exception as e:
            result.error = str(e)
            if attempt < retries - 1:
                time.sleep(retry_delay)
                continue
    
    result.status = StageStatus.FAILED
    return result


def _ensure_fork(
    repo: RepoInput,
    username: str,
    headers: dict
) -> Tuple[Optional[str], Optional[str]]:
    """Ensure fork exists, create if needed. Returns (fork_owner, error)"""
    
    # Check if fork already exists
    fork_url = f"https://api.github.com/repos/{username}/{repo.name}"
    resp = requests.get(fork_url, headers=headers, timeout=30)
    
    if resp.status_code == 200:
        fork_data = resp.json()
        if fork_data.get("fork") and fork_data.get("parent", {}).get("full_name") == repo.full_name:
            return username, None
    
    # Create fork
    create_url = f"https://api.github.com/repos/{repo.full_name}/forks"
    resp = requests.post(create_url, headers=headers, timeout=60)
    
    if resp.status_code in (200, 202):
        # Wait for fork to be ready
        time.sleep(3)
        return username, None
    
    return None, f"Failed to create fork: {resp.text}"


def _get_branch_sha(
    repo: RepoInput,
    fork_owner: str,
    branch: str,
    headers: dict
) -> Tuple[Optional[str], Optional[str]]:
    """Get SHA of branch. Returns (sha, error)"""
    
    # Try fork first, then original repo
    for owner in [fork_owner, repo.owner]:
        url = f"https://api.github.com/repos/{owner}/{repo.name}/git/refs/heads/{branch}"
        resp = requests.get(url, headers=headers, timeout=30)
        
        if resp.status_code == 200:
            return resp.json().get("object", {}).get("sha"), None
    
    return None, f"Branch '{branch}' not found"


def _create_branch(
    owner: str,
    repo_name: str,
    branch_name: str,
    sha: str,
    headers: dict
) -> Tuple[bool, Optional[str]]:
    """Create a new branch. Returns (success, error)"""
    
    # Check if branch already exists
    check_url = f"https://api.github.com/repos/{owner}/{repo_name}/git/refs/heads/{branch_name}"
    resp = requests.get(check_url, headers=headers, timeout=30)
    
    if resp.status_code == 200:
        # Branch exists, delete and recreate
        requests.delete(check_url, headers=headers, timeout=30)
    
    # Create branch
    create_url = f"https://api.github.com/repos/{owner}/{repo_name}/git/refs"
    data = {
        "ref": f"refs/heads/{branch_name}",
        "sha": sha
    }
    resp = requests.post(create_url, headers=headers, json=data, timeout=30)
    
    if resp.status_code in (200, 201):
        return True, None
    
    return False, f"Failed to create branch: {resp.text}"


def _create_or_update_file(
    owner: str,
    repo_name: str,
    branch: str,
    file_path: str,
    content: str,
    headers: dict
) -> Tuple[bool, Optional[str]]:
    """Create or update file in repo. Returns (success, error)"""
    
    url = f"https://api.github.com/repos/{owner}/{repo_name}/contents/{file_path}"
    
    # Check if file exists (to get sha for update)
    existing_sha = None
    resp = requests.get(url, headers=headers, params={"ref": branch}, timeout=30)
    if resp.status_code == 200:
        existing_sha = resp.json().get("sha")
    
    # Create/update file
    data = {
        "message": f"Migrate CI/CD to GitHub Actions\n\nMigrated by CIPilot batch pipeline",
        "content": base64.b64encode(content.encode()).decode(),
        "branch": branch
    }
    if existing_sha:
        data["sha"] = existing_sha
    
    resp = requests.put(url, headers=headers, json=data, timeout=30)
    
    if resp.status_code in (200, 201):
        return True, None
    
    return False, f"Failed to create file: {resp.text}"


def _create_pr(
    repo: RepoInput,
    fork_owner: str,
    username: str,
    branch_name: str,
    source_ci: str,
    headers: dict
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Create PR from fork to original. Returns (pr_url, pr_number, error)"""
    
    url = f"https://api.github.com/repos/{repo.full_name}/pulls"
    
    ci_name = source_ci.replace("-", " ").title()
    
    data = {
        "title": f"[CIPilot] Migrate {ci_name} to GitHub Actions",
        "body": f"""## CI/CD Migration

This PR migrates the existing **{ci_name}** configuration to **GitHub Actions**.

### Generated by CIPilot Batch Pipeline

- Source CI: {ci_name}
- Target CI: GitHub Actions
- Migration Tool: [CIPilot](https://cipilot.com)

### What's Changed
- Added `.github/workflows/ci.yml` with equivalent GitHub Actions workflow

### Please Review
- [ ] Workflow triggers are correct
- [ ] Environment variables are properly configured
- [ ] Secrets are referenced correctly
- [ ] Build/test commands are accurate

---
*This PR was automatically generated. Please review carefully before merging.*
""",
        "head": f"{fork_owner}:{branch_name}",
        "base": repo.target_branch,
    }
    
    resp = requests.post(url, headers=headers, json=data, timeout=30)
    
    if resp.status_code in (200, 201):
        pr_data = resp.json()
        return pr_data.get("html_url"), pr_data.get("number"), None
    
    # Check if PR already exists
    if resp.status_code == 422 and "already exists" in resp.text.lower():
        return None, None, "PR already exists for this branch"
    
    return None, None, f"Failed to create PR: {resp.text}"
