"""Keep the installed tool and the selected project separate."""
from pathlib import Path


def resolve(project=None, config=None, create=False):
    if config is not None:
        path = Path(config).expanduser().resolve()
        if path.parent.name != ".aipipe":
            raise ValueError("configuration must be inside the target project's .aipipe directory")
        root = path.parent.parent
        if project is not None and Path(project).expanduser().resolve() != root:
            raise ValueError("--project and --config select different projects")
    elif project is not None:
        root = Path(project).expanduser().resolve()
        path = root / ".aipipe/project.json"
    else:
        root = Path.cwd().resolve()
        for candidate in (root, *root.parents):
            path = candidate / ".aipipe/project.json"
            if path.is_file():
                if path.resolve().parent.parent != candidate:
                    raise ValueError("configuration symlink escapes the selected project")
                return candidate, path
            if (candidate / ".git").exists():
                root = candidate
                break
        if not create:
            raise ValueError("no project configuration found; use --project PATH or aipipe init")
        path = root / ".aipipe/project.json"
    if path.resolve().parent.parent != root or path.resolve().parent.name != ".aipipe":
        raise ValueError("configuration symlink escapes the selected project")
    if not create and not path.is_file():
        raise ValueError(f"missing configuration: {path}; use aipipe init")
    return root, path


def asset(relative):
    packaged = Path(__file__).parent / "resources" / relative
    if packaged.exists():
        return packaged
    source = Path(__file__).resolve().parents[2] / relative
    if source.exists():
        return source
    raise ValueError(f"missing packaged aipipe resource: {relative}")
