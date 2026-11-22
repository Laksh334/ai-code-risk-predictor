import re

# Accepts e.g.  https://github.com/psf/requests
#               github.com/psf/requests.git
#               https://www.github.com/psf/requests/tree/main/src
_GITHUB_URL = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<repo>[A-Za-z0-9._-]+?)"
    r"(?:\.git)?(?:/.*)?$"
)


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Return (owner, repo) from a GitHub URL, or None if it isn't one."""
    match = _GITHUB_URL.match(url.strip())
    if not match or match["repo"] in {".", ".."}:
        return None
    return match["owner"], match["repo"]
