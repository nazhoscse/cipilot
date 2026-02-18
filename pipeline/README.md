# CIPilot Batch Pipeline

Mass CI/CD migrations for thousands of repositories with a single command.

## Features

- **Batch Processing**: Process thousands of repos from CSV/JSON input
- **Multi-CI Detection**: Detects ALL CI configs per repo, creates separate PR for each
- **Multi-PAT Support**: Rotate GitHub tokens from different accounts for higher rate limits
- **Configurable Strictness**: Control when PRs are created
- **Resume Capability**: Continue from where you left off
- **Real-time Progress**: Live dashboard showing migration progress
- **Detailed Reporting**: CSV output with per-repo, per-CI status

## Installation

```bash
cd pipeline
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

```env
# GitHub PATs from DIFFERENT accounts for rate limit stacking (5000/hr each)
GITHUB_PATS=ghp_from_account1,ghp_from_account2

# LLM Configuration
LLM_PROVIDER=xai
LLM_MODEL=grok-4-1-fast-reasoning
LLM_API_KEY=your-api-key
```

> **Note:** Multiple PATs from the same account share the 5000/hr limit. Use PATs from different GitHub accounts for additive rate limits.

## Usage

### Basic Usage

```bash
python run.py --input repos.csv --output results.csv
```

### With Options

```bash
python run.py \
  --input repos.csv \
  --output results.csv \
  --strictness permissive \
  --github-pats "$PAT1,$PAT2" \
  --provider xai \
  --model grok-4-1-fast-reasoning \
  --concurrent 2 \
  --retries 3
```

### Dry Run (No PRs)

```bash
python run.py --input repos.csv --output results.csv --dry-run
```

### Resume Previous Run

```bash
python run.py --input repos.csv --output results.csv --resume
```

## Input Format

### CSV

```csv
repo_url,target_branch
owner/repo1,main
owner/repo2,master
```

> **Note:** If `target_branch` is incorrect, the pipeline auto-detects the actual default branch from GitHub.

### JSON

```json
[
  {"repo_url": "owner/repo1", "target_branch": "main"},
  {"repo_url": "owner/repo2"}
]
```

## Strictness Levels

| Level | Lint Must Pass | Double-Check Must Pass | PR Created When |
|-------|---------------|------------------------|-----------------|
| `strict` | ✅ | ✅ | Both pass |
| `lint_only` | ✅ | ❌ | Lint passes |
| `permissive` | ❌ | ❌ | Always (for feedback) |
| `dry_run` | N/A | N/A | Never |

## PR Format

PRs created by the pipeline use the same format as the web application:

- **Branch**: `{prefix}-{ci_type}-to-gha-{timestamp}`
- **Commit**: `ci: add GitHub Actions workflow (migrated by CIPilot)`
- **Title**: `[CIPilot] Migrate {CI Name} to GitHub Actions`
- **Body**: Full markdown with summary, changes, about, and validation sections

## Output Columns

| Column | Description |
|--------|-------------|
| `repo_url` | Input repository |
| `detected_ci` | circleci, travis, gitlab, etc. |
| `all_detected_ci` | All CIs found in repo |
| `migration_status` | success/failed/skipped |
| `lint_valid` | true/false |
| `lint_errors` | actionlint error messages |
| `double_check_passed` | true/false |
| `double_check_confidence` | 0.0-1.0 |
| `pr_status` | success/skipped/failed |
| `pr_url` | GitHub PR URL |
| `pr_error` | Error message if PR failed |
| `overall_status` | success/partial/failed |
