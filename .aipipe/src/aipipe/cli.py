"""aipipe: independent Skills, project configuration and GitHub operations."""
import argparse
import json
import os
from pathlib import Path
import sys
from . import __version__, config, context, initialize, owner_auth, runner, readiness, identity, status
from .credentials import credential


def common(p):
    p.add_argument('--project', type=Path, default=argparse.SUPPRESS, help='target project directory; default: discover from current directory')
    p.add_argument('--config', type=Path, default=argparse.SUPPRESS, help='explicit .aipipe/project.json')
    p.add_argument('--credentials', type=Path, default=argparse.SUPPRESS, help='external credential registry')


def parser():
    p = argparse.ArgumentParser(prog='aipipe', description=__doc__, epilog='Examples: aipipe init; aipipe init apps --help; aipipe run test. No model or coding client is launched.')
    common(p)
    p.set_defaults(project=None, config=None, credentials=Path.home()/'.config/aipipe/credentials.json')
    p.add_argument('--version', action='version', version='aipipe '+__version__)
    sub = p.add_subparsers(dest='action', required=True)
    def command(name, help):
        child = sub.add_parser(name, help=help)
        common(child)
        return child
    command('inspect', 'inspect local configuration without reading credentials')
    stat = command('status', 'read-only handoff status for one Issue or PR')
    target = stat.add_mutually_exclusive_group(required=True)
    target.add_argument('--issue', type=int)
    target.add_argument('--pr', type=int)
    stat.add_argument('--role', required=True, choices=('developer','delivery'))
    stat.add_argument('--offline', action='store_true', help='do not read credentials or GitHub; remote facts are unknown')
    stat.add_argument('--json', action='store_true', help='print the versioned status object as JSON')
    ident=command('identity','create or inspect a declared tool/model execution identity')
    ident_sub=ident.add_subparsers(dest='identity_action',required=True)
    creator=ident_sub.add_parser('create');common(creator)
    creator.add_argument('--tool',required=True)
    creator.add_argument('--model',required=True,help='actual model ID, or unknown; never infer from preferences')
    creator.add_argument('--role',dest='work_role',required=True,choices=tuple(identity.ROLES))
    creator.add_argument('--credential-role',required=True,choices=('developer','delivery','owner'))
    creator.add_argument('--session')
    show=ident_sub.add_parser('show');show.add_argument('--identity',required=True,type=Path)
    show.add_argument('--operation',help='render a record to include in a planning/maintenance document')
    commit=command('commit','commit staged changes with declared code authors and operator identity')
    commit.add_argument('--identity',required=True,type=Path)
    commit.add_argument('--author-identity',type=Path)
    commit.add_argument('--coauthor-identity',action='append',default=[],type=Path)
    commit.add_argument('--issue',required=True,type=int)
    commit.add_argument('--message-file',required=True,type=Path)
    product = command('run', 'execute a configured native build/test command')
    product.add_argument('name')
    for name in ('github', 'api', 'push'):
        cmd = command(name, {'github':'run gh issue/pr/run/workflow using one App role', 'api':'repository-relative REST operation', 'push':'push an explicit branch using the Developer/Delivery App'}[name])
        cmd.add_argument('--role', required=True, choices=('developer','delivery'))
        cmd.add_argument('--identity',type=Path)
        if name == 'github':
            cmd.add_argument('--result-json', action='store_true', help='for attributed PR review/merge, print one structured result JSON object')
            cmd.add_argument('args', nargs=argparse.REMAINDER)
        elif name == 'api':
            cmd.add_argument('path')
            cmd.add_argument('--method', default='GET', choices=('GET','POST','PATCH','PUT','DELETE'))
            cmd.add_argument('--input', type=Path)
        else:
            cmd.add_argument('branch')
    meta = command('metadata', 'check or reconcile Issue stages and PR labels/milestones')
    target = meta.add_mutually_exclusive_group(required=True)
    target.add_argument('--issue', type=int)
    target.add_argument('--pr', type=int)
    meta.add_argument('--role', choices=('developer','delivery','owner'), default='developer')
    meta.add_argument('--apply', action='store_true')
    meta.add_argument('--identity', type=Path)
    pub = command('publish', 'preview a batch offline; --apply publishes through Delivery')
    pub.add_argument('--plan', type=Path, required=True)
    pub.add_argument('--design-ref', required=True)
    pub.add_argument('--apply', action='store_true')
    pub.add_argument('--identity',type=Path)
    cfg = command('config', 'generate, update or validate project configuration')
    cfgsub = cfg.add_subparsers(dest='config_action', required=True)
    setter = cfgsub.add_parser('set', help='merge non-secret fields; preserve unrelated configuration')
    common(setter); config.add_options(setter)
    validator = cfgsub.add_parser('validate'); common(validator)
    auth = command('auth', 'inspect credentials or issue short-lived App tokens (Owner)')
    authsub = auth.add_subparsers(dest='auth_action', required=True)
    status = authsub.add_parser('status'); common(status)
    status.add_argument('--role', choices=('developer','delivery'))
    trust = authsub.add_parser('trust-app', help='Owner preview/save exact shared App trust outside project')
    common(trust)
    trust.add_argument('--role', required=True, choices=('developer','delivery'))
    trust.add_argument('--app-owner', required=True)
    trust.add_argument('--permissions-file', required=True, type=Path)
    trust.add_argument('--private-key', type=Path)
    trust.add_argument('--apply', action='store_true')
    token = authsub.add_parser('issue-token'); common(token); owner_auth.add_options(token)
    doctor = command('doctor', 'verify role identities, repository access and handoff prerequisites')
    doctor.add_argument('--offline', action='store_true', help='local planning/development/review only; no credentials or GitHub access')
    doctor.add_argument('--for', dest='purpose', choices=('plan','publish','develop','review','handoff'), default='handoff')
    release = command('release', 'release an existing milestone only after handoff checks')
    release.add_argument('--milestone', type=int, required=True)
    release.add_argument('--plan', type=Path, required=True)
    release.add_argument('--design-ref', required=True)
    release.add_argument('--apply', action='store_true')
    release.add_argument('--identity',type=Path)
    init = command('init', 'interactive or parameter-driven repo/apps/credentials/checks setup')
    initialize.add_options(init)
    return p


def dispatch(args):
    if args.action=='metadata':
        from . import metadata
        return metadata.run(args)
    if args.action=='status':return status.run(args)
    if args.action=='identity':
        if args.identity_action=='create':return identity.create(args)
        actor=identity.load(args.identity)
        print(identity.block(actor,args.operation) if args.operation else json.dumps(actor,ensure_ascii=False,indent=2))
        return 0
    if args.action=='commit':return identity.commit(args)
    if args.action == 'doctor':
        return readiness.run(args)
    if args.action == 'release':
        return readiness.release(args)
    if args.action == 'init':
        return initialize.run(args)
    if args.action == 'config':
        if args.config_action == 'set':
            return config.apply(args)
        root, path = context.resolve(args.project,args.config)
        config.read_config(path)
        print('Valid schema_version=1 configuration: '+str(path))
        return 0
    if args.action == 'auth':
        if args.auth_action == 'trust-app':return owner_auth.trust(args)
        if args.auth_action == 'issue-token':
            return owner_auth.issue(args)
        root,path=context.resolve(args.project,args.config)
        data,_=config.read_config(path)
        failures=0
        for role in ([args.role] if args.role else ('developer','delivery')):
            try:
                credential(data,root,role,args.credentials,os.environ)
                print(role+': configured, credential available (not remotely verified)')
            except (ValueError,OSError,KeyError):
                print(role+': missing, expired or invalid local credential')
                failures+=1
        return 1 if failures else 0
    return runner.execute(args)


def main(argv=None):
    args = None
    try:
        args = parser().parse_args(argv)
        return dispatch(args)
    except KeyboardInterrupt:
        print('Cancelled; existing GitHub resources were preserved.',file=sys.stderr)
        return 130
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print('Stopped: '+str(exc),file=sys.stderr)
        return 2
