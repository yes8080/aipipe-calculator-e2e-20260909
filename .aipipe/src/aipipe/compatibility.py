"""Describe the running CLI and enforce the project's minimum compatible version."""
import json
from pathlib import Path
import re
import sys
from . import __version__


def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d+\.\d+\.\d+',value):
        raise ValueError('CLI versions must use stable MAJOR.MINOR.PATCH numbers')
    return tuple(map(int,value.split('.')))


def describe(root, data):
    root=Path(root); path=root/'.aipipe/compatibility.json'
    resource=json.loads(path.read_text()) if path.is_file() else {}
    if not isinstance(resource,dict):raise ValueError('compatibility.json must contain an object')
    requirements=[x for x in (resource.get('minimum_cli_version'),data.get('compatibility',{}).get('minimum_cli_version')) if x is not None]
    minimum=max(requirements,key=version) if requirements else None
    current=version(__version__)
    resource_version=resource.get('resource_version')
    if resource_version is not None:version(resource_version)
    bundled=None; source=root/'.aipipe/src/aipipe/__init__.py'
    if source.is_file():
        match=re.search(r'^__version__\s*=\s*[\'"]([0-9]+\.[0-9]+\.[0-9]+)[\'"]',source.read_text(),re.M)
        if match:bundled=match.group(1)
    warnings=[]
    if not resource_version:warnings.append('Project resource version is unknown; inspect existing Skills before upgrading.')
    if resource_version and resource_version!=__version__:warnings.append('CLI and project resources differ; inspect compatibility and local customizations before upgrading.')
    if bundled and bundled!=__version__:warnings.append('Bundled source differs from the running CLI; choose one verified entrypoint.')
    return {'version':__version__,'minimum_cli_version':minimum,'resource_version':resource_version,
            'bundled_version':bundled,'entrypoint':str(Path(sys.argv[0]).resolve()),
            'implementation':str(Path(__file__).resolve().parent),'python':sys.executable,
            'compatible':minimum is None or current>=version(minimum),'warnings':warnings}


def enforce(root, data):
    result=describe(root,data)
    if not result['compatible']:
        raise ValueError('running aipipe '+result['version']+' is older than project minimum '+result['minimum_cli_version']+'; upgrade the selected entrypoint before executing')
    return result
