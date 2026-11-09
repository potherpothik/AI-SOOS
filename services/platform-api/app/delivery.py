"""Pull request text and the GitHub call. The token never enters the stored body."""

from collections.abc import Callable
from dataclasses import dataclass

from app.errors import MissingSecretError


@dataclass(frozen=True)
class PullRequest:
    url: str
    body: dict[str, object]


def parse_github_repo(url: str) -> tuple[str, str]:
    cleaned = url.strip().removesuffix(".git")
    if cleaned.startswith("git@github.com:"):
        owner_repo = cleaned.split(":", 1)[1]
    elif "github.com/" in cleaned:
        owner_repo = cleaned.split("github.com/", 1)[1]
    else:
        message = "repository URL must be a GitHub repository"
        raise ValueError(message)
    parts = owner_repo.strip("/").split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        message = "repository URL must be a GitHub repository"
        raise ValueError(message)
    return parts[0], parts[1]


def build_pr_body(
    *,
    summary: str,
    files: list[str],
    tests: str,
    scans: str,
    cost_usd: float,
    limitations: str,
) -> str:
    file_lines = "\n".join(f"- {name}" for name in files) or "- none"
    return (
        f"## Summary\n\n{summary}\n\n"
        f"## Files\n\n{file_lines}\n\n"
        f"## Tests\n\n{tests}\n\n"
        f"## Scans\n\n{scans}\n\n"
        f"## Cost\n\nUSD {cost_usd:.4f}\n\n"
        f"## Limitations\n\n{limitations}\n"
    )


def pull_request_call(repo_url: str, branch: str, title: str, body: str) -> PullRequest:
    owner, name = parse_github_repo(repo_url)
    return PullRequest(
        url=f"https://api.github.com/repos/{owner}/{name}/pulls",
        body={
            "title": title,
            "head": branch,
            "base": "main",
            "body": body,
        },
    )


def open_pull_request(
    token: str,
    repo_url: str,
    branch: str,
    title: str,
    body: str,
    poster: Callable[[str, PullRequest], str] | None = None,
) -> str:
    if not token:
        raise MissingSecretError("AISOOS_GITHUB_TOKEN")
    request = pull_request_call(repo_url, branch, title, body)
    if poster is None:
        return _post(token, request)
    return poster(token, request)


def _post(token: str, request: PullRequest) -> str:
    import httpx

    response = httpx.post(
        request.url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json=request.body,
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    url = payload.get("html_url") if isinstance(payload, dict) else None
    if isinstance(url, str):
        return url
    return request.url
