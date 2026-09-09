"""One configuration contract for generation and execution."""
import argparse
import json
import os
from pathlib import Path
import re
import tempfile

def repository(config):
    value = config.get("repository") or ""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("configure repository before GitHub operations")
    return value


def command_spec(name, command):
    """Validate one native command consistently, without shell conversion."""
    field = 'commands[' + json.dumps(name, ensure_ascii=True) + ']'
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        raise ValueError(f'{field}: command name allows letters, digits, _, . and -; use e2e as the key and put test:e2e in argv')
    if not isinstance(command, dict):
        raise ValueError(f'{field}: expected an object with cwd and argv, not a shell string; '
                         'example: {"cwd":".","argv":["npm","run","test"]}; '
                         'fix project.json or use config set --commands-file FILE; this is not an App credential error')
    argv = command.get('argv')
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
        raise ValueError(f'{field}.argv must be a non-empty string array')
    directory = command.get('cwd', '.')
    if not isinstance(directory, str) or not directory:
        raise ValueError(f'{field}.cwd must be a non-empty project-relative directory string')
    directory = Path(directory)
    if directory.is_absolute() or '..' in directory.parts:
        raise ValueError(f'{field}.cwd must be project-relative')
    return argv, directory


def product_command(config, root, name):
    if name not in config.get('commands', {}):
        raise ValueError(f"no configured command named {name}; discover the project's native entry first")
    argv, directory = command_spec(name, config['commands'][name])
    cwd = (root / directory).resolve()
    if (cwd != root and root not in cwd.parents) or not cwd.is_dir():
        raise ValueError(f'commands[{json.dumps(name)}].cwd is missing or outside the project')
    return argv, cwd


def update(config, args):
    config = json.loads(json.dumps(config))
    config.setdefault("schema_version", 1)
    if config["schema_version"] != 1:
        raise ValueError("unsupported project schema_version")
    if getattr(args,'minimum_cli_version',None):
        from .compatibility import version
        version(args.minimum_cli_version)
        config.setdefault('compatibility',{})['minimum_cli_version']=args.minimum_cli_version
    if args.repo:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
            raise ValueError("--repo must be OWNER/REPO")
        old = config.get("repository")
        if old and old.lower() != args.repo.lower():
            if not args.rebind:
                raise ValueError("repository differs; inspect it first, then use --rebind")
            # Installations and CI belong to a repository; do not copy them silently.
            config["apps"] = {}
            config["ci"] = {"required_check": None, "workflow_path": None}
            config["default_branch"] = None
        config["repository"] = args.repo
    if args.default_branch:
        if any(c.isspace() for c in args.default_branch) or ".." in args.default_branch:
            raise ValueError("invalid default branch")
        config["default_branch"] = args.default_branch
    role_values = (args.app_id, args.installation_id, args.slug, args.credential_ref)
    if any(x is not None for x in role_values) and not args.role:
        raise ValueError("App settings require --role")
    if args.role:
        role = config.setdefault("apps", {}).setdefault(args.role, {})
        if args.app_id is not None and args.app_id <= 0:
            raise ValueError("app_id must be positive")
        if args.installation_id is not None and args.installation_id <= 0:
            raise ValueError("installation_id must be positive")
        if args.app_id is not None and role.get("app_id") not in (None, args.app_id):
            if args.installation_id is None:
                role["installation_id"] = None
            if args.slug is None:
                role["slug"] = None
        for key in ("app_id", "installation_id", "slug", "credential_ref"):
            value = getattr(args, key)
            if value is not None:
                if key == "slug" and not re.fullmatch(r"[A-Za-z0-9-]+", value):
                    raise ValueError("invalid App slug")
                if key == "credential_ref" and not re.fullmatch(r"[A-Za-z0-9_./:-]{1,160}", value):
                    raise ValueError("credential_ref is a logical name, never a secret")
                role[key] = value
    if args.check_name is not None:
        if config.get('ci',{}).get('required_checks') and not getattr(args,'checks_file',None):
            raise ValueError('project uses multiple required checks; update them explicitly with --checks-file')
        config.setdefault("ci", {})["required_check"] = args.check_name
    if args.workflow_path is not None:
        path = Path(args.workflow_path)
        if path.is_absolute() or ".." in path.parts or path.parent.as_posix() != ".github/workflows" or path.suffix not in (".yml", ".yaml"):
            raise ValueError("workflow must be a file under .github/workflows/")
        config.setdefault("ci", {})["workflow_path"] = path.as_posix()
    if getattr(args,'metadata_mode',None):
        if args.metadata_mode not in ('inline','workflow'):
            raise ValueError('metadata-mode must be inline or workflow')
        config.setdefault('metadata',{})['mode']=args.metadata_mode
    if getattr(args, 'auto_report_errors', None) is not None:
        config.setdefault('error_reporting', {})['enabled'] = args.auto_report_errors == 'on'
        if args.auto_report_errors == 'on':
            from .compatibility import version
            minimum = config.setdefault('compatibility', {}).get('minimum_cli_version', '0.0.0')
            if version(minimum) < version('0.5.3'):
                config['compatibility']['minimum_cli_version'] = '0.5.3'
    if getattr(args, 'report_credential_ref', None) is not None:
        config.setdefault('error_reporting', {})['credential_ref'] = args.report_credential_ref
    if getattr(args,'checks_file',None):
        values=json.loads(args.checks_file.read_text())
        from .policy import required_checks
        required_checks({'ci':{'required_checks':values}})
        config.setdefault('ci',{})['required_checks']=values
    if args.commands_file:
        commands = json.loads(args.commands_file.read_text())
        if not isinstance(commands, dict):
            raise ValueError("commands file must contain an object keyed by command name")
        for name, command in commands.items():
            command_spec(name, command)
        config.setdefault("commands", {}).update(commands)
    if args.preferences_file:
        preferences = json.loads(args.preferences_file.read_text())
        if not isinstance(preferences, dict):
            raise ValueError("preferences file must be an object")
        config.setdefault("preferences", {}).update(preferences)
    for role_name in ("developer", "delivery"):
        config.setdefault("apps", {}).setdefault(role_name, {})
    ids = [config["apps"][r].get("app_id") for r in ("developer", "delivery")]
    if ids[0] is not None and ids[0] == ids[1]:
        raise ValueError("Developer and Delivery must use different GitHub Apps")
    return config



def validate(config):
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise ValueError('unsupported schema_version; expected 1')
    if config.get('repository'):
        repository(config)
    apps = config.get('apps', {})
    if not isinstance(apps, dict):
        raise ValueError('apps must be an object')
    ids = []
    for role in ('developer', 'delivery'):
        entry = apps.get(role, {})
        if not isinstance(entry, dict):
            raise ValueError('App role must be an object')
        for field in ('app_id', 'installation_id'):
            value = entry.get(field)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError(f'{role}.{field} must be a positive integer')
        ids.append(entry.get('app_id'))
    if ids[0] is not None and ids[0] == ids[1]:
        raise ValueError('Developer and Delivery must use different GitHub Apps')
    commands = config.get('commands', {})
    if not isinstance(commands, dict):
        raise ValueError('commands must be an object')
    for name, command in commands.items():
        command_spec(name, command)
    attribution=config.get('attribution',{})
    if not isinstance(attribution,dict) or type(attribution.get('required',False)) is not bool:
        raise ValueError('attribution.required must be a boolean')
    if attribution.get('legacy_before') is not None and (not isinstance(attribution['legacy_before'],str) or not re.fullmatch('[0-9a-f]{40}',attribution['legacy_before'])):
        raise ValueError('attribution.legacy_before must be a full SHA')
    compatibility=config.get('compatibility',{})
    if not isinstance(compatibility,dict):raise ValueError('compatibility must be an object')
    if compatibility.get('minimum_cli_version') is not None:
        from .compatibility import version
        version(compatibility['minimum_cli_version'])
    ci=config.get('ci',{})
    if not isinstance(ci,dict):raise ValueError('ci must be an object')
    if 'required_checks' in ci:
        from .policy import required_checks
        required_checks(config)
    metadata=config.get('metadata',{})
    if not isinstance(metadata,dict):raise ValueError('metadata must be an object')
    mode=metadata.get('mode','inline')
    if mode not in ('inline','workflow'):
        raise ValueError('metadata.mode must be inline or workflow')
    execution = config.get('execution', {})
    reporting = config.get('error_reporting', {})
    if not isinstance(reporting, dict) or type(reporting.get('enabled', False)) is not bool:
        raise ValueError('error_reporting.enabled must be a boolean')
    if set(reporting) - {'enabled', 'credential_ref'}:
        raise ValueError('error_reporting accepts only enabled and credential_ref; destination is yes8080/aipipe-template')
    ref = reporting.get('credential_ref')
    if (ref is not None and (not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,160}', ref))) or (reporting.get('enabled') and not ref):
        raise ValueError('enabled error_reporting requires a logical credential_ref, never a token')
    if not isinstance(execution, dict) or not isinstance(execution.get('strip_env', []), list):
        raise ValueError('execution.strip_env must be an array')
    if any(not isinstance(x, str) for x in execution.get('strip_env', [])):
        raise ValueError('execution.strip_env entries must be strings')
    return config


def read_config(path):
    path = Path(path).resolve()
    if path.parent.name != '.aipipe':
        raise ValueError('project config must be inside the project .aipipe directory')
    try:
        return validate(json.loads(path.read_text(encoding='utf-8'))), path.parent.parent
    except ValueError as exc:
        raise ValueError(f'{path}: {exc}') from exc


def save(path, data):
    validate(data)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.project-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def add_options(p):
    for name in ('repo', 'default-branch', 'slug', 'credential-ref', 'check-name', 'workflow-path', 'metadata-mode'):
        p.add_argument('--'+name)
    p.add_argument('--rebind', action='store_true')
    p.add_argument('--role', choices=('developer', 'delivery'))
    p.add_argument('--app-id', type=int)
    p.add_argument('--installation-id', type=int)
    p.add_argument('--commands-file', type=Path)
    p.add_argument('--checks-file', type=Path)
    p.add_argument('--minimum-cli-version')
    p.add_argument('--preferences-file', type=Path)
    p.add_argument('--auto-report-errors', choices=('on', 'off'), help='opt in/out of sanitized defect reports to yes8080/aipipe-template')
    p.add_argument('--report-credential-ref', help='separate external credential reference with Issues write on the report repository')


def parser():
    p = argparse.ArgumentParser(description='Merge non-secret project configuration')
    p.add_argument('--config', type=Path)
    p.add_argument('--project', type=Path)
    add_options(p)
    return p


def apply(args):
    from .context import resolve
    root, path = resolve(getattr(args, 'project', None), args.config, create=True)
    original = json.loads(path.read_text()) if path.exists() else {}
    save(path, update(original, args))
    print(f'Updated non-secret configuration: {path}')
    return 0


def main(argv=None):
    return apply(parser().parse_args(argv))
