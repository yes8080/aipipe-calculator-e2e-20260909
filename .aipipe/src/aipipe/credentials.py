"""Role credential lookup and child process environments."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from .config import repository
TOKEN_VARS = {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"}

def outside(path, root):
    root = Path(root).resolve()
    path = Path(path).expanduser().resolve()
    if path == root or root in path.parents:
        raise ValueError("credential registry and token files must be outside the checkout")
    return path


def credential(config, root, role, registry_path, env):
    ref = config.get("apps", {}).get(role, {}).get("credential_ref")
    if not ref:
        raise ValueError(f"configure apps.{role}.credential_ref")
    registry = json.loads(outside(registry_path, root).read_text())
    entry = registry.get("credentials", {}).get(ref)
    if not isinstance(entry, dict):
        raise ValueError(f"credential reference not registered: {ref}")
    if entry.get("expires_at"):
        expires = datetime.fromisoformat(entry["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
            raise ValueError("credential expired or expiration lacks timezone; ask Owner to reissue, then resume")
    if entry.get("kind") == "env":
        value = env.get(entry.get("name", ""), "")
    elif entry.get("kind") == "token_file":
        path = outside(entry["path"], root)
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise ValueError("token file must not be accessible to group or others (use 0600)")
        value = path.read_text().strip()
    else:
        raise ValueError("credential kind must be env or token_file; the runner never loads App private keys")
    if not value or any(c.isspace() for c in value):
        raise ValueError("credential is missing or malformed; personal gh login will not be used")
    return value


def clean_env(env, config):
    result = dict(env)
    remove = TOKEN_VARS | set(config.get("execution", {}).get("strip_env", []))
    for key in list(result):
        if key in remove or key.startswith("AIPIPE_") or key == "GH_DEBUG":
            result.pop(key, None)
    return result


def authenticated_env(config, root, role, registry, env):
    value = credential(config, root, role, registry, env)
    result = clean_env(env, config)
    result.update(GH_TOKEN=value, GH_HOST="github.com", GH_REPO=repository(config),
                  GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    return result
