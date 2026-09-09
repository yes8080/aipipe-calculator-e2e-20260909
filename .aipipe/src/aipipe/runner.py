"""Execute configured commands using a selected project's role credentials."""
import json
import os
import re
from pathlib import Path
import subprocess
from . import context, publish, compatibility, identity
from .config import read_config, product_command, repository
from .credentials import outside, credential, clean_env, authenticated_env
from .github import remote_repository, verify_remote, gh_command, api_command, Gh, GhError


def execute(args, run=subprocess.run, env=None):
    env = dict(os.environ if env is None else env)
    if args.action == "github" and getattr(args, 'result_json', False):
        return execute_github_result_json_startup(args, run, env)
    root, path = context.resolve(getattr(args, "project", None), args.config)
    config, root = read_config(path)
    if args.action == "inspect":
        print(json.dumps({"project": str(root), "cli": compatibility.describe(root, config), "repository": config.get("repository"),
                          "default_branch": config.get("default_branch"),
                          "commands": sorted(config.get("commands", {})), "ci": config.get("ci", {}),
                          "apps": {role: {key: entry.get(key) for key in ("app_id", "installation_id", "slug", "credential_ref")} for role, entry in config.get("apps", {}).items()},
                          "preferences": config.get("preferences", {})}, ensure_ascii=False, indent=2))
        return 0
    compatibility.enforce(root,config)
    if args.action == "run":
        command, cwd = product_command(config, root, args.name)
        return run(command, cwd=cwd, env=clean_env(env, config)).returncode
    repo = repository(config)
    actor=identity.load(getattr(args,'identity',None),repo,'delivery' if args.action=='publish' else getattr(args,'role',None))
    if identity.writing(args):identity.required(config,actor)
    if args.action == "publish":
        child_env = clean_env(env, config)
        if args.apply:
            verify_remote(config, root, run)
            child_env = authenticated_env(config, root, "delivery", args.credentials, env)
        command = ["--repo", repo, "--plan", str(args.plan.expanduser().resolve()), "--design-ref", args.design_ref]
        if args.apply:
            command.append("--apply")
        template = root / ".aipipe/templates/issue.md"
        return publish.main(command, env=child_env, template_path=template if template.is_file() else None, actor=actor)
    origin = verify_remote(config, root, run)
    child_env = authenticated_env(config, root, args.role, args.credentials, env)
    cleanup=[]
    client=Gh(env=child_env,cwd=root)
    if args.action == "github":
        gh_command(repo,args.args)  # Check repository overrides before any metadata reads.
        argv=args.args
        if actor:
            argv,cleanup=identity.github_arguments(argv,actor,client,repo)
            if isinstance(argv,tuple):
                operation,number,payload=argv
                result=submit_attributed(client,repo,operation,number,payload)
                print(json.dumps(result,ensure_ascii=False))
                if config.get('metadata',{}).get('mode','inline') == 'workflow':
                    return 0
                from .metadata import Reconciler, linked_issue
                try:
                    service=Reconciler(client,repo)
                    issue_number=linked_issue(service.get('pulls/'+number))
                    service.reconcile(issue_number,apply=True,expected_pr=int(number))
                except (ValueError,OSError,KeyError,TypeError) as exc:
                    raise ValueError(operation+' succeeded, but metadata synchronization failed; '
                                     'do not repeat the Review/merge; run aipipe metadata --pr '+number+
                                     ' --role delivery --identity FILE --apply: '+str(exc)) from None
                return 0
        command = gh_command(repo, argv)
    elif args.action == "api":
        body = args.input.expanduser().resolve() if args.input else None
        command = api_command(repo, args.path, args.method, body)
        if actor and args.method!='GET':
            payload=identity.api_payload(args.path,args.method,json.loads(body.read_text()) if body else {},actor,client,repo)
            result=client.request('repos/'+repo+'/'+args.path,args.method,payload)
            print(json.dumps(result,ensure_ascii=False));return 0
    elif args.action == "push":
        if not origin.startswith("https://github.com/"):
            raise ValueError("App push requires an HTTPS origin; personal SSH identity is not used")
        if args.branch.startswith("-") or any(c.isspace() for c in args.branch) or ":" in args.branch:
            raise ValueError("push branch must be one explicit branch name")
        if actor and config.get('attribution',{}).get('required'):
            published=fetch_published_base(root,config.get('default_branch','main'),child_env,run)
            identity.verify_commits(root,config,actor,published_base=published)
        command = [*APP_GIT,"push", "origin", f"HEAD:refs/heads/{args.branch}"]
    else:
        raise ValueError("unknown action")
    try:
        return run(command, cwd=root, env=child_env).returncode
    finally:
        for path in cleanup:Path(path).unlink(missing_ok=True)


APP_GIT = ["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]


READ_ONLY_FIELDS = {
    'merge': 'number,state,mergedAt,mergeCommit,headRefOid',
    'review': 'number,state,headRefOid,reviews',
}


def github_remainder(args):
    return list(args[1:] if args[:1] == ['--'] else args)


def result_recovery_base(root, config_path, args):
    return ['aipipe', '--project', str(root), '--config', str(config_path),
            '--credentials', str(Path(args.credentials).expanduser().resolve())]


def identity_path(args):
    return str(Path(args.identity).expanduser().resolve())


def metadata_recovery(root, config_path, args, number):
    argv = [*result_recovery_base(root, config_path, args), 'metadata', '--pr', str(number),
            '--role', args.role, '--identity', identity_path(args), '--apply']
    return {'scope':'metadata', 'argv':argv}


def read_only_recovery(root, config_path, args, operation, number, reason):
    argv = [*result_recovery_base(root, config_path, args), 'github', '--role', args.role,
            '--identity', identity_path(args), '--', 'pr', 'view', str(number),
            '--json', READ_ONLY_FIELDS[operation]]
    return {'scope':'read_only', 'argv':argv, 'reason':reason}


def no_recovery():
    return {'scope':'none', 'argv':[]}


def clean_error(exc, phase, category=None):
    if isinstance(exc, GhError):
        result = {'category': category or 'github_error', 'phase': phase}
        if exc.status is not None:
            result['status'] = exc.status
        elif exc.code is not None:
            result['status'] = 'unknown'
        return result
    return {'category': category or 'validation', 'phase': phase}


def startup_result_json(args, exc):
    result = {'schema_version':1, 'operation':'unknown',
              'primary':{'status':'failed', 'error':clean_error(exc, 'preflight')},
              'metadata':{'status':'not_run'}, 'recovery':no_recovery()}
    try:
        operation, number = operation_from_result_args(args.args)
        result['operation'] = operation
        result['pr'] = int(number)
    except (ValueError, TypeError, AttributeError):
        pass
    return result


def failed_result(operation, repo, number, error):
    return {'schema_version':1, 'operation':operation, 'repository':repo, 'pr':int(number),
            'primary':{'status':'failed', 'error':error},
            'metadata':{'status':'not_run'}, 'recovery':no_recovery()}


def unknown_result(operation, repo, number, head, error, recovery):
    primary = {'status':'unknown', 'error':error}
    if head:
        primary['head'] = head
    return {'schema_version':1, 'operation':operation, 'repository':repo, 'pr':int(number),
            'primary':primary, 'metadata':{'status':'not_run'}, 'recovery':recovery}


def merge_write_sha(result):
    if not isinstance(result, dict) or result.get('merged') is not True:
        return None
    sha = result.get('sha')
    if isinstance(sha, str) and re.fullmatch('[0-9a-f]{40}', sha):
        return sha
    return None


def response_head_sha(response):
    if not isinstance(response, dict) or not isinstance(response.get('head'), dict):
        return None
    return response['head'].get('sha')


def merge_readback_matches(current, result, payload):
    return (isinstance(current, dict) and current.get('merged') is True and
            isinstance(result, dict) and current.get('merge_commit_sha') == result.get('sha') and
            response_head_sha(current) == payload.get('sha'))


def review_write_matches(result, payload):
    return bool(isinstance(result, dict) and result.get('commit_id') == payload.get('commit_id'))


def review_readback_matches(current, payload):
    return response_head_sha(current) == payload.get('commit_id')


def operation_from_result_args(argv):
    argv = github_remainder(argv)
    if len(argv) < 2 or argv[0] != 'pr' or argv[1] not in ('review', 'merge'):
        raise ValueError('--result-json supports only attributed pr review and pr merge')
    if len(argv) < 3 or not argv[2].isdigit():
        raise ValueError('--result-json requires an explicit PR number')
    return argv[1], argv[2]


def precheck_result_args(argv):
    argv = github_remainder(argv)
    operation, number = operation_from_result_args(argv)
    body_path, argv = identity.value(argv, ['--body-file', '-F'])
    body, argv = identity.value(argv, ['--body', '-b'])
    if body is not None and body_path is not None:
        raise ValueError('use only one body input')
    if body_path == '-':
        raise ValueError('use an explicit body file for attributed operations')
    expected, without = identity.value(argv, ['--match-head-commit'])
    if not expected:
        raise ValueError('review/merge requires --match-head-commit equal to current PR head')
    if operation == 'review':
        flags = [x for x in ('--approve', '--request-changes', '--comment') if x in without]
        if len(flags) != 1:
            raise ValueError('select exactly one review decision')
        if body is None and body_path is None:
            raise ValueError('review requires an actual acceptance report body')
        if without != ['pr', 'review', number, flags[0]]:
            raise ValueError('unsupported attributed review arguments; use PR number, decision, --match-head-commit and --body-file')
    elif '--admin' in without or '--auto' in without:
        raise ValueError('attributed merge is immediate and SHA-bound; wait for native checks/approval, do not use --auto or --admin')
    elif without != ['pr', 'merge', number, '--squash']:
        raise ValueError('unsupported attributed merge arguments; use PR number, --squash, --match-head-commit and --body-file')


def execute_github_result_json_startup(args, run, env):
    try:
        root, path = context.resolve(getattr(args, "project", None), args.config)
        config, root = read_config(path)
        compatibility.enforce(root, config)
        repo = repository(config)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps(startup_result_json(args, exc), ensure_ascii=False))
        return 1
    return execute_github_result_json(args, config, root, path, repo, run, env)


def execute_github_result_json(args, config, root, config_path, repo, run, env):
    operation = 'unknown'
    number = 0
    try:
        operation, number = operation_from_result_args(args.args)
        if not args.identity:
            raise ValueError('--result-json requires --identity FILE')
        actor = identity.load(args.identity, repo, args.role)
        if identity.writing(args):
            identity.required(config, actor)
        gh_command(repo, args.args)
        precheck_result_args(args.args)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        if number:
            result = failed_result(operation, repo, number, clean_error(exc, 'preflight'))
        else:
            result = {'schema_version':1, 'operation':operation, 'repository':repo,
                      'primary':{'status':'failed', 'error':clean_error(exc, 'preflight')},
                      'metadata':{'status':'not_run'}, 'recovery':no_recovery()}
        print(json.dumps(result, ensure_ascii=False))
        return 1

    try:
        verify_remote(config, root, run)
        child_env = authenticated_env(config, root, args.role, args.credentials, env)
        client = Gh(env=child_env, cwd=root)
        argv, cleanup = identity.github_arguments(args.args, actor, client, repo)
    except (ValueError, OSError, KeyError, TypeError, AttributeError, GhError) as exc:
        result = failed_result(operation, repo, number, clean_error(exc, 'preflight'))
        print(json.dumps(result, ensure_ascii=False))
        return 1

    try:
        if not isinstance(argv, tuple) or argv[0] != operation:
            raise ValueError('--result-json supports only attributed pr review and pr merge')
        payload = argv[2]
        try:
            result = submit_attributed_result_json(client, repo, operation, number, payload,
                                                   lambda reason: read_only_recovery(root, config_path, args, operation, number, reason))
            if result['primary']['status'] != 'succeeded':
                print(json.dumps(result, ensure_ascii=False))
                return 1 if result['primary']['status'] == 'failed' else 2
        except (ValueError, OSError, KeyError, TypeError, AttributeError, GhError) as exc:
            head = payload.get('sha') or payload.get('commit_id') if isinstance(payload, dict) else None
            result = unknown_result(operation, repo, number, head,
                                    clean_error(exc, 'write', 'write_unconfirmed'),
                                    read_only_recovery(root, config_path, args, operation, number,
                                                       'write result was not confirmed'))
            print(json.dumps(result, ensure_ascii=False))
            return 2
        try:
            if config.get('metadata',{}).get('mode','inline') == 'workflow':
                result['metadata'] = {'status':'pending'}
                result['recovery'] = no_recovery()
                print(json.dumps(result, ensure_ascii=False))
                return 0
            from .metadata import Reconciler, linked_issue
            service = Reconciler(client, repo)
            issue_number = linked_issue(service.get('pulls/'+number))
            service.reconcile(issue_number, apply=True, expected_pr=int(number))
            result['metadata'] = {'status':'succeeded'}
            result['recovery'] = no_recovery()
        except (ValueError, OSError, KeyError, TypeError, AttributeError, GhError):
            result['metadata'] = {'status':'failed', 'error':{'category':'metadata_failed', 'phase':'metadata'}}
            result['recovery'] = metadata_recovery(root, config_path, args, number)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        for path in cleanup:
            Path(path).unlink(missing_ok=True)


def submit_attributed_result_json(client, repo, operation, number, payload, recovery):
    path = 'repos/'+repo+'/pulls/'+number
    head = payload.get('sha') or payload.get('commit_id')
    if operation == 'merge':
        try:
            result = client.request(path+'/merge', 'PUT', payload)
        except GhError as exc:
            status = getattr(exc, 'status', None)
            if status in (403, 422):
                return failed_result(operation, repo, number, clean_error(exc, 'write', 'github_rejected'))
            return unknown_result(operation, repo, number, head, clean_error(exc, 'write', 'write_unconfirmed'),
                                  recovery('write result was not confirmed'))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return unknown_result(operation, repo, number, head, clean_error(exc, 'write', 'write_unconfirmed'),
                                  recovery('write result was not confirmed'))
        merge_sha = merge_write_sha(result)
        if not merge_sha:
            return unknown_result(operation, repo, number, head,
                                  {'category':'invalid_success_response', 'phase':'write'},
                                  recovery('merge response did not confirm success'))
        try:
            current = client.request(path)
        except (GhError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            return unknown_result(operation, repo, number, head, clean_error(exc, 'readback', 'readback_unconfirmed'),
                                  recovery('merge readback failed'))
        if not merge_readback_matches(current, result, payload):
            return unknown_result(operation, repo, number, head,
                                  {'category':'readback_mismatch', 'phase':'readback'},
                                  recovery('merge readback did not match the write response'))
        return {'schema_version':1, 'operation':'merge', 'repository':repo, 'pr':int(number),
                'primary':{'status':'succeeded', 'head':payload['sha'], 'merge_sha':merge_sha},
                'metadata':{'status':'not_run'}, 'recovery':no_recovery()}
    if operation != 'review':
        return failed_result(operation, repo, number, {'category':'unsupported_operation', 'phase':'preflight'})
    try:
        result = client.request(path+'/reviews', 'POST', payload)
    except GhError as exc:
        status = getattr(exc, 'status', None)
        if status in (403, 422):
            return failed_result(operation, repo, number, clean_error(exc, 'write', 'github_rejected'))
        return unknown_result(operation, repo, number, head, clean_error(exc, 'write', 'write_unconfirmed'),
                              recovery('review write result was not confirmed'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return unknown_result(operation, repo, number, head, clean_error(exc, 'write', 'write_unconfirmed'),
                              recovery('review write result was not confirmed'))
    if not review_write_matches(result, payload):
        return unknown_result(operation, repo, number, head,
                              {'category':'invalid_success_response', 'phase':'write'},
                              recovery('review response did not confirm commit_id'))
    try:
        current = client.request(path)
    except (GhError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return unknown_result(operation, repo, number, head, clean_error(exc, 'readback', 'readback_unconfirmed'),
                              recovery('review readback failed'))
    if not review_readback_matches(current, payload):
        return unknown_result(operation, repo, number, head,
                              {'category':'head_changed', 'phase':'readback'},
                              recovery('PR head changed after review creation'))
    primary = {'status':'succeeded', 'head':payload['commit_id']}
    if result.get('id') is not None:
        primary['review_id'] = result['id']
    return {'schema_version':1, 'operation':'review', 'repository':repo, 'pr':int(number),
            'primary':primary, 'metadata':{'status':'not_run'}, 'recovery':no_recovery()}


def fetch_published_base(root, branch, env, run=subprocess.run):
    """Read the authenticated remote, never trust a stale local origin/main ref."""
    ref='refs/heads/'+branch
    result=run([*APP_GIT,'ls-remote','--heads','origin',ref],cwd=root,env=env,text=True,capture_output=True)
    if result.returncode:raise ValueError('cannot read published default branch; no push performed')
    lines=result.stdout.strip().splitlines()
    if not lines:return None  # Empty repository: validate all non-legacy commits.
    if len(lines)!=1:raise ValueError('ambiguous published default branch; no push performed')
    fields=lines[0].split()
    if len(fields)!=2 or fields[1]!=ref or not re.fullmatch('[0-9a-f]{40}',fields[0]):
        raise ValueError('invalid published default branch response; no push performed')
    sha=fields[0]
    result=run([*APP_GIT,'fetch','--no-tags','--no-write-fetch-head','origin',sha],cwd=root,env=env,text=True,capture_output=True)
    if result.returncode:raise ValueError('cannot fetch published default branch history; no push performed')
    return sha


def submit_attributed(client,repo,operation,number,payload):
    path='repos/'+repo+'/pulls/'+number
    if operation=='merge':
        result=client.request(path+'/merge','PUT',payload)
        if not merge_write_sha(result):
            raise ValueError('merge not confirmed; inspect PR before retrying')
        current=client.request(path)
        if not merge_readback_matches(current,result,payload):
            raise ValueError('merge readback mismatch; inspect PR before retrying')
        return result
    if operation!='review':raise ValueError('unsupported attributed operation')
    result=client.request(path+'/reviews','POST',payload)
    if not review_write_matches(result,payload):
        raise ValueError('review write could not be confirmed; inspect before retrying')
    if not review_readback_matches(client.request(path),payload):
        raise ValueError('PR head changed after review creation; re-review the new head, do not claim approval of it')
    return result


def parser():
    from .cli import parser as cli_parser
    return cli_parser()
