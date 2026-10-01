"""
GitHub Integration Provider (Phase F).

Read-only capabilities (LOW risk):
  • list_repositories      → list repos for authenticated user/org
  • get_repository         → repo metadata
  • list_branches          → branches for a repo
  • list_commits           → recent commit history
  • list_issues            → open/closed issues
  • list_pull_requests     → PR list

Write capabilities (HIGH risk — ALWAYS requires approval):
  • create_issue           → open a new issue
  • create_pull_request    → open a PR

Authentication: GitHub Personal Access Token (PAT) or OAuth App token.
Credential field: github_token (PAT or OAuth token — stored encrypted)

Security:
- No arbitrary GitHub API URL execution.
- Only declared capability endpoints are called.
- write capabilities marked HIGH risk — always approval-gated.
- Path traversal prevented: repo/owner parameters validated as alphanumeric.
- No shell execution, no repository cloning, no CI/CD triggering.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

import requests

from app.integrations.provider import (
    CapabilityCategory,
    CapabilityResult,
    ConnectionTestResult,
    IntegrationProvider,
    ProviderCapability,
    RiskLevel,
)

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_MAX_ROWS = 100

# GitHub username/org and repo name safe pattern
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{1,100}$")


def _safe_name(value: str, field: str) -> str:
    """Validate a GitHub owner/repo name to prevent path traversal."""
    if not _SAFE_NAME_RE.match(value):
        raise GitHubApiError(
            f"Invalid {field}: must be alphanumeric, hyphens, underscores, or dots"
        )
    return value


@dataclass(frozen=True)
class GitHubApiError(Exception):
    safe_message: str
    original_exception: Exception | None = None

    def __str__(self) -> str:
        return self.safe_message


class GitHubProvider(IntegrationProvider):
    """EAAWP provider for GitHub REST API."""

    @property
    def provider_type(self) -> str:
        return "github"

    @property
    def display_name(self) -> str:
        return "GitHub"

    @property
    def description(self) -> str:
        return (
            "Connect GitHub to give AI employees read-only access to repositories, "
            "issues, pull requests, and code. Write operations (create issue, "
            "create PR) require explicit human approval."
        )

    @property
    def icon_hint(self) -> str:
        return "github"

    def required_credential_fields(self) -> list[str]:
        return ["github_token"]

    def get_capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability(
                key="list_repositories",
                display_name="List Repositories",
                description="List repositories accessible to the authenticated user.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["all", "public", "private", "member"], "description": "Repository type filter"},
                        "sort": {"type": "string", "enum": ["created", "updated", "pushed", "full_name"]},
                        "per_page": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
                    },
                    "required": [],
                },
            ),
            ProviderCapability(
                key="get_repository",
                display_name="Get Repository",
                description="Retrieve metadata for a specific repository.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repository owner (user or org)"},
                        "repo": {"type": "string", "description": "Repository name"},
                    },
                    "required": ["owner", "repo"],
                },
            ),
            ProviderCapability(
                key="list_branches",
                display_name="List Branches",
                description="List branches for a repository.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "per_page": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
                    },
                    "required": ["owner", "repo"],
                },
            ),
            ProviderCapability(
                key="list_commits",
                display_name="List Commits",
                description="Retrieve recent commit history for a repository branch.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "sha": {"type": "string", "description": "Branch or commit SHA"},
                        "per_page": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
                    },
                    "required": ["owner", "repo"],
                },
            ),
            ProviderCapability(
                key="list_issues",
                display_name="List Issues",
                description="List open and closed issues for a repository.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "state": {"type": "string", "enum": ["open", "closed", "all"]},
                        "per_page": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
                    },
                    "required": ["owner", "repo"],
                },
            ),
            ProviderCapability(
                key="list_pull_requests",
                display_name="List Pull Requests",
                description="List pull requests for a repository.",
                category=CapabilityCategory.READ,
                risk_level=RiskLevel.LOW,
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "state": {"type": "string", "enum": ["open", "closed", "all"]},
                        "per_page": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
                    },
                    "required": ["owner", "repo"],
                },
            ),
            ProviderCapability(
                key="create_issue",
                display_name="Create Issue",
                description=(
                    "Create a new issue in a repository. "
                    "HIGH RISK — requires human approval before execution."
                ),
                category=CapabilityCategory.WRITE,
                risk_level=RiskLevel.HIGH,
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "title": {"type": "string", "description": "Issue title", "maxLength": 500},
                        "body": {"type": "string", "description": "Issue body", "maxLength": 5000},
                        "labels": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                    },
                    "required": ["owner", "repo", "title"],
                },
            ),
            ProviderCapability(
                key="create_pull_request",
                display_name="Create Pull Request",
                description=(
                    "Create a pull request. "
                    "HIGH RISK — requires human approval before execution."
                ),
                category=CapabilityCategory.WRITE,
                risk_level=RiskLevel.HIGH,
                input_schema={
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "title": {"type": "string", "maxLength": 500},
                        "body": {"type": "string", "maxLength": 5000},
                        "head": {"type": "string", "description": "Source branch"},
                        "base": {"type": "string", "description": "Target branch"},
                    },
                    "required": ["owner", "repo", "title", "head", "base"],
                },
            ),
        ]

    async def test_connection(self, credentials: dict[str, Any]) -> ConnectionTestResult:
        try:
            token = credentials.get("github_token", "")
            data = await self._get(token, "/user", {})
            return ConnectionTestResult(
                success=True,
                account_info={
                    "connected": True,
                    "login": data.get("login", ""),
                    "name": data.get("name", ""),
                    "public_repos": data.get("public_repos", 0),
                },
                error_message=None,
            )
        except GitHubApiError as exc:
            return ConnectionTestResult(
                success=False, account_info={"connected": False}, error_message=str(exc)
            )

    async def execute(
        self,
        capability_key: str,
        credentials: dict[str, Any],
        parameters: dict[str, Any],
    ) -> CapabilityResult:
        try:
            token = credentials.get("github_token", "")

            if capability_key == "list_repositories":
                return await self._list_repositories(token, parameters)
            if capability_key == "get_repository":
                return await self._get_repository(token, parameters)
            if capability_key == "list_branches":
                return await self._list_branches(token, parameters)
            if capability_key == "list_commits":
                return await self._list_commits(token, parameters)
            if capability_key == "list_issues":
                return await self._list_issues(token, parameters)
            if capability_key == "list_pull_requests":
                return await self._list_pull_requests(token, parameters)
            if capability_key in ("create_issue", "create_pull_request"):
                return await self._execute_write(token, capability_key, parameters)
            return CapabilityResult(data=[], error=f"Unknown capability: {capability_key}")
        except GitHubApiError as exc:
            return CapabilityResult(data=[], error=str(exc))
        except Exception as exc:
            logger.exception("Unexpected GitHub execute error")
            return CapabilityResult(data=[], error=self._sanitise_error(str(exc)))

    async def _list_repositories(self, token: str, params: dict) -> CapabilityResult:
        repo_type = params.get("type", "all")
        if repo_type not in ("all", "public", "private", "member"):
            raise GitHubApiError(f"Invalid type: {repo_type}")
        per_page = min(int(params.get("per_page", 30)), _MAX_ROWS)
        repos = await self._get(token, "/user/repos", {"type": repo_type, "per_page": per_page})
        data = [
            {"name": r.get("name"), "full_name": r.get("full_name"),
             "private": r.get("private"), "language": r.get("language"),
             "stars": r.get("stargazers_count"), "open_issues": r.get("open_issues_count")}
            for r in (repos if isinstance(repos, list) else [])
        ]
        return CapabilityResult(data=data, row_count=len(data), source_label="GitHub Repositories")

    async def _get_repository(self, token: str, params: dict) -> CapabilityResult:
        owner = _safe_name(params.get("owner", ""), "owner")
        repo = _safe_name(params.get("repo", ""), "repo")
        data = await self._get(token, f"/repos/{owner}/{repo}", {})
        safe = {
            k: data.get(k) for k in
            ("name", "full_name", "description", "private", "language",
             "stargazers_count", "forks_count", "open_issues_count", "default_branch",
             "created_at", "updated_at", "pushed_at")
        }
        return CapabilityResult(data=safe, row_count=1, source_label="GitHub Repository")

    async def _list_branches(self, token: str, params: dict) -> CapabilityResult:
        owner = _safe_name(params.get("owner", ""), "owner")
        repo = _safe_name(params.get("repo", ""), "repo")
        per_page = min(int(params.get("per_page", 30)), _MAX_ROWS)
        branches = await self._get(token, f"/repos/{owner}/{repo}/branches", {"per_page": per_page})
        data = [{"name": b.get("name"), "protected": b.get("protected")} for b in (branches if isinstance(branches, list) else [])]
        return CapabilityResult(data=data, row_count=len(data), source_label="GitHub Branches")

    async def _list_commits(self, token: str, params: dict) -> CapabilityResult:
        owner = _safe_name(params.get("owner", ""), "owner")
        repo = _safe_name(params.get("repo", ""), "repo")
        per_page = min(int(params.get("per_page", 30)), _MAX_ROWS)
        query = {"per_page": per_page}
        if params.get("sha"):
            query["sha"] = params["sha"][:255]
        commits = await self._get(token, f"/repos/{owner}/{repo}/commits", query)
        data = [
            {
                "sha": c.get("sha", "")[:12],
                "message": (c.get("commit", {}).get("message", ""))[:200],
                "author": c.get("commit", {}).get("author", {}).get("name", ""),
                "date": c.get("commit", {}).get("author", {}).get("date", ""),
            }
            for c in (commits if isinstance(commits, list) else [])
        ]
        return CapabilityResult(data=data, row_count=len(data), source_label="GitHub Commits")

    async def _list_issues(self, token: str, params: dict) -> CapabilityResult:
        owner = _safe_name(params.get("owner", ""), "owner")
        repo = _safe_name(params.get("repo", ""), "repo")
        state = params.get("state", "open")
        if state not in ("open", "closed", "all"):
            raise GitHubApiError(f"Invalid state: {state}")
        per_page = min(int(params.get("per_page", 30)), _MAX_ROWS)
        issues = await self._get(token, f"/repos/{owner}/{repo}/issues", {"state": state, "per_page": per_page})
        data = [
            {
                "number": i.get("number"), "title": i.get("title", "")[:200],
                "state": i.get("state"), "created_at": i.get("created_at"),
                "user": (i.get("user") or {}).get("login", ""),
            }
            for i in (issues if isinstance(issues, list) else [])
            if "pull_request" not in i  # exclude PRs from issues list
        ]
        return CapabilityResult(data=data, row_count=len(data), source_label="GitHub Issues")

    async def _list_pull_requests(self, token: str, params: dict) -> CapabilityResult:
        owner = _safe_name(params.get("owner", ""), "owner")
        repo = _safe_name(params.get("repo", ""), "repo")
        state = params.get("state", "open")
        if state not in ("open", "closed", "all"):
            raise GitHubApiError(f"Invalid state: {state}")
        per_page = min(int(params.get("per_page", 30)), _MAX_ROWS)
        prs = await self._get(token, f"/repos/{owner}/{repo}/pulls", {"state": state, "per_page": per_page})
        data = [
            {
                "number": p.get("number"), "title": p.get("title", "")[:200],
                "state": p.get("state"), "head": (p.get("head") or {}).get("ref", ""),
                "base": (p.get("base") or {}).get("ref", ""), "created_at": p.get("created_at"),
                "user": (p.get("user") or {}).get("login", ""),
            }
            for p in (prs if isinstance(prs, list) else [])
        ]
        return CapabilityResult(data=data, row_count=len(data), source_label="GitHub Pull Requests")

    async def _execute_write(self, token: str, capability_key: str, params: dict) -> CapabilityResult:
        """
        Execute a write capability.

        Write capabilities are HIGH risk. The Integration Manager (execute_capability)
        has already verified capability grant and approval at this point.
        """
        owner = _safe_name(params.get("owner", ""), "owner")
        repo = _safe_name(params.get("repo", ""), "repo")

        if capability_key == "create_issue":
            body = {
                "title": params["title"][:500],
                "body": params.get("body", "")[:5000],
                "labels": params.get("labels", [])[:10],
            }
            result = await self._post(token, f"/repos/{owner}/{repo}/issues", body)
            return CapabilityResult(
                data={"number": result.get("number"), "url": result.get("html_url"), "title": result.get("title")},
                row_count=1, source_label="GitHub Issues",
            )

        if capability_key == "create_pull_request":
            body = {
                "title": params["title"][:500],
                "body": params.get("body", "")[:5000],
                "head": params["head"][:255],
                "base": params["base"][:255],
            }
            result = await self._post(token, f"/repos/{owner}/{repo}/pulls", body)
            return CapabilityResult(
                data={"number": result.get("number"), "url": result.get("html_url"), "title": result.get("title")},
                row_count=1, source_label="GitHub Pull Requests",
            )

        return CapabilityResult(data=[], error=f"Unknown write capability: {capability_key}")

    async def _get(self, token: str, path: str, params: dict) -> Any:
        loop = asyncio.get_running_loop()
        url = f"{_GITHUB_API}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        def _do():
            try:
                resp = requests.get(url, headers=headers, params=params, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as e:
                raise GitHubApiError(self._sanitise_error(f"GitHub API error: {e.response.status_code}"), e)
            except requests.RequestException as e:
                raise GitHubApiError(self._sanitise_error(str(e)), e)

        return await loop.run_in_executor(None, _do)

    async def _post(self, token: str, path: str, body: dict) -> dict:
        loop = asyncio.get_running_loop()
        url = f"{_GITHUB_API}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        def _do():
            try:
                resp = requests.post(url, headers=headers, json=body, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except requests.HTTPError as e:
                raise GitHubApiError(self._sanitise_error(f"GitHub API error: {e.response.status_code}"), e)
            except requests.RequestException as e:
                raise GitHubApiError(self._sanitise_error(str(e)), e)

        return await loop.run_in_executor(None, _do)
