"""Declared authorship and operation attribution; never an authentication source."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from . import config, context, compatibility
from .credentials import clean_env
from .github import remote_repository

START = '<!-- aipipe:actor:start -->'
END = '<!-- aipipe:actor:end -->'
ROLES = {'developer': {'developer'}, 'reviewer': {'delivery'}, 'planner': {'delivery'},
         'maintainer': {'developer', 'delivery', 'owner'}}


def text(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(field + ' must be non-empty single-line text (max 200 characters)')
    if any(c in value for c in '<>'):
        raise ValueError(field + ' must not contain angle brackets')
    return value


def validate(actor, repo=None):
    if not isinstance(actor, dict) or actor.get('schema_version') != 1:
        raise ValueError('unsupported execution identity schema')
    if set(actor)-{'schema_version','agent_id','repository','tool','model','role','credential_role','session','created_at','operation','sha'}:
        raise ValueError('identity contains unknown fields; never put credentials in an identity file')
    try:
        if str(uuid.UUID(actor['agent_id'])) != actor['agent_id']:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError('identity.agent_id must be a canonical UUID') from None
    for key in ('tool', 'model', 'repository'):
        text(actor.get(key), 'identity.'+key)
    config.repository(actor)
    if repo and actor['repository'].lower() != repo.lower():
        raise ValueError('execution identity belongs to a different repository')
    if actor.get('role') not in ROLES or actor.get('credential_role') not in ROLES[actor['role']]:
        raise ValueError('execution role and credential role do not match')
    if actor.get('session') is not None:
        text(actor['session'], 'identity.session')
    return actor


def load(path, repo=None, credential_role=None):
    if path is None:
        return None
    actor=validate(json.loads(Path(path).expanduser().read_text()),repo)
    if credential_role and actor['credential_role'] != credential_role:
        raise ValueError('identity credential_role differs from the operation role; no credential was read')
    return actor


def project_repo(root, data):
    if data.get('repository'):
        return config.repository(data)
    result=subprocess.run(['git','remote','get-url','origin'],cwd=root,text=True,capture_output=True)
    repo=remote_repository(result.stdout) if result.returncode == 0 else None
    if not repo:
        raise ValueError('configure repository or a GitHub origin before creating execution identity')
    return repo


def create(args):
    root,path=context.resolve(args.project,args.config)
    data,_=config.read_config(path)
    compatibility.enforce(root,data)
    actor=validate({'schema_version':1,'agent_id':str(uuid.uuid4()),'repository':project_repo(root,data),
                    'tool':args.tool,'model':args.model,'role':args.work_role,
                    'credential_role':args.credential_role,'session':args.session,
                    'created_at':datetime.now(timezone.utc).isoformat()})
    directory=root/'.aipipe/.runtime/agents'
    if not directory.resolve().is_relative_to(root):
        raise ValueError('identity directory escapes project')
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/(actor['agent_id']+'.json')
    with target.open('x') as out:
        json.dump(actor,out,ensure_ascii=False,indent=2);out.write('\n')
    print(json.dumps({'identity_file':str(target),'identity':actor},ensure_ascii=False,indent=2))
    return 0


def label(actor):
    return actor['tool']+' / '+actor['model']


def email(actor):
    # Reserved invalid domain: this declares an author, not a GitHub account affiliation.
    return actor['agent_id']+'@agents.aipipe.invalid'


def trailers(actor, issue, prefix='Aipipe'):
    return [f'{prefix}-Agent: {actor["agent_id"]}',f'{prefix}-Tool: {actor["tool"]}',
            f'{prefix}-Model: {actor["model"]}',f'{prefix}-Role: {actor["role"]}',
            f'{prefix}-Credential-Role: {actor["credential_role"]}',f'{prefix}-Issue: {actor["repository"]}#{issue}']


def commit(args):
    root,path=context.resolve(args.project,args.config)
    data,_=config.read_config(path);compatibility.enforce(root,data)
    repo=project_repo(root,data)
    actor=load(args.identity,repo)
    author=load(args.author_identity,repo) if args.author_identity else actor
    coauthors=[load(p,repo) for p in args.coauthor_identity]
    if args.issue <= 0:
        raise ValueError('commit requires a positive Issue number')
    message=args.message_file.read_text().strip()
    if not message or START in message or re.search(r'(?im)^(Aipipe(?:-[\w]+)*|Co-authored-by):',message):
        raise ValueError('provide a message without generated identity trailers; use explicit author identity options')
    # Rebase/cherry-pick/amend need explicit preservation of original authors, not this ordinary-commit path.
    for name in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply'):
        result=subprocess.run(['git','rev-parse','--git-path',name],cwd=root,text=True,capture_output=True,check=True)
        candidate=Path(result.stdout.strip())
        if not candidate.is_absolute():candidate=root/candidate
        if candidate.exists():raise ValueError('complete the Git operation preserving its original authors; ordinary aipipe commit is unavailable')
    env=clean_env(os.environ,data)
    for name in list(env):
        if name.startswith(('GIT_AUTHOR_','GIT_COMMITTER_')):env.pop(name)
    env.update(GIT_AUTHOR_NAME=label(author),GIT_AUTHOR_EMAIL=email(author),
               GIT_COMMITTER_NAME=label(actor)+' ['+actor['role']+']',GIT_COMMITTER_EMAIL=email(actor))
    lines=trailers(author,args.issue)
    if actor['agent_id'] != author['agent_id']:lines+=trailers(actor,args.issue,'Aipipe-Operator')
    for other in coauthors:
        lines+=['Co-authored-by: '+label(other)+' <'+email(other)+'>']+trailers(other,args.issue,'Aipipe-Contributor')
    wanted=message+'\n\n'+'\n'.join(lines)+'\n'
    # stdin avoids a secret-bearing environment in a shell or accidental shell interpolation.
    result=subprocess.run(['git','commit','--cleanup=verbatim','-F','-'],cwd=root,env=env,input=wanted,text=True)
    if result.returncode:return result.returncode
    result=subprocess.run(['git','log','-1','--format=%an%x00%ae%x00%cn%x00%ce%x00%B'],cwd=root,env=env,text=True,capture_output=True,check=True)
    fields=result.stdout.split('\0',4)
    if fields[:4] != [label(author),email(author),env['GIT_COMMITTER_NAME'],email(actor)] or fields[4].strip()!=wanted.strip():
        raise ValueError('commit was created but metadata differs (possibly a hook); inspect HEAD before pushing; no retry')
    print('Recorded code author '+label(author)+'; operator '+label(actor)+'; agent '+actor['agent_id'])
    return 0


def block(actor, operation, sha=None):
    record=dict(actor,operation=text(operation,'operation'))
    if sha is not None:
        if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('operation SHA must be a full commit SHA')
        record['sha']=sha
    return START+'\n### 执行身份（声明）\n```json\n'+json.dumps(record,ensure_ascii=False,sort_keys=True,indent=2)+'\n```\n'+END


def split(body):
    """Only validated, generated trailing blocks are metadata; malformed markers fail closed."""
    body=body or '';records=[]
    while END in body or START in body:
        start=body.rfind(START)
        match=re.fullmatch(re.escape(START)+r'\n### 执行身份（声明）\n```json\n(.*?)\n```\n'+re.escape(END)+r'\s*',body[start:],re.S) if start>=0 else None
        if not match:raise ValueError('malformed execution identity block; preserve or repair the complete generated block')
        record=validate(json.loads(match.group(1)))
        text(record.get('operation'),'operation')
        if record.get('sha') is not None and not re.fullmatch('[0-9a-f]{40}',record['sha']):raise ValueError('invalid recorded SHA')
        records.insert(0,record);body=body[:start].rstrip('\r\n')
    return body,records


def annotate(body,actor,operation,sha=None,previous=None):
    core,records=split(body)
    if previous is not None:
        _,earlier=split(previous)
        records=earlier+records
    output=core.rstrip()
    records.append(dict(actor,operation=operation,**({'sha':sha} if sha else {})))
    seen=set()
    for record in records:
        key=json.dumps(record,sort_keys=True)
        if key in seen:continue
        seen.add(key)
        base={k:v for k,v in record.items() if k not in ('operation','sha')}
        output+='\n\n'+block(base,record['operation'],record.get('sha'))
    return output+'\n'


def canonical(response):
    if isinstance(response,list):return [canonical(x) for x in response]
    if isinstance(response,dict):
        return {k:(split(v)[0].rstrip('\r\n')+'\n' if k in ('body','description') and isinstance(v,str) and START in v else v)
                for k,v in response.items()}
    return response


def required(data,actor):
    if data.get('attribution',{}).get('required') and not actor:
        raise ValueError('execution identity required; create one with aipipe identity create and pass --identity FILE')


def writing(args):
    if args.action=='push':return True
    if args.action=='publish':return args.apply
    if args.action=='api':return args.method!='GET'
    if args.action=='github':
        argv=args.args[1:] if args.args[:1]==['--'] else args.args
        return len(argv)>1 and argv[1] not in ('view','list','status','checks','diff')
    return False


def value(argv,names):
    found=[];kept=[];i=0
    while i<len(argv):
        arg=argv[i]
        if arg in names:
            if i+1>=len(argv):raise ValueError('missing value for '+arg)
            found.append(argv[i+1]);i+=2;continue
        equal=next((name for name in names if arg.startswith(name+'=')),None)
        if equal:found.append(arg[len(equal)+1:]);i+=1;continue
        kept.append(arg);i+=1
    if len(found)>1:raise ValueError('duplicate '+names[0]+' option')
    return (found[0] if found else None),kept


def github_arguments(argv,actor,client,repo):
    """Prepare body metadata for gh writes; return argv and temporary files to remove."""
    argv=list(argv[1:] if argv[:1]==['--'] else argv)
    if len(argv)<2:return argv,[]
    kind,operation=argv[:2]
    if operation in ('view','list','status','checks','diff'):return argv,[]
    body_path,argv=value(argv,['--body-file','-F'])
    body,argv=value(argv,['--body','-b'])
    if body is not None and body_path is not None:raise ValueError('use only one body input')
    if body_path=='-':raise ValueError('use an explicit body file for attributed operations')
    if body_path:body=Path(body_path).read_text()
    number=argv[2] if len(argv)>2 and argv[2].isdigit() else None
    sha=None;previous=None
    if kind=='pr' and operation in ('review','merge'):
        if not number:raise ValueError('attributed review/merge requires an explicit PR number')
        pr=client.request('repos/'+repo+'/pulls/'+number);sha=pr['head']['sha']
        expected,without=value(argv,['--match-head-commit'])
        if not expected or expected!=sha:raise ValueError('review/merge requires --match-head-commit equal to current PR head')
        # gh pr review has no match-head flag; submit review via the REST path below.
        if operation=='review':
            flags=[x for x in ('--approve','--request-changes','--comment') if x in argv]
            if len(flags)!=1:raise ValueError('select exactly one review decision')
            event={'--approve':'APPROVE','--request-changes':'REQUEST_CHANGES','--comment':'COMMENT'}[flags[0]]
            if actor['role']!='reviewer' and event!='COMMENT':raise ValueError('approval or rejection requires a reviewer identity')
            if body is None or not body.strip():raise ValueError('review requires an actual acceptance report body')
            allowed=[kind,operation,number,flags[0]]
            if without!=allowed:raise ValueError('unsupported attributed review arguments; use PR number, decision, --match-head-commit and --body-file')
            payload={'body':annotate(body,actor,'review:'+event,sha),'event':event,'commit_id':sha}
            return ('review',number,payload),[]
        if '--squash' not in argv:raise ValueError('attributed merge currently requires --squash')
        if '--admin' in argv or '--auto' in argv:
            raise ValueError('attributed merge is immediate and SHA-bound; wait for native checks/approval, do not use --auto or --admin')
        if actor['role']!='reviewer' or actor['credential_role']!='delivery':
            raise ValueError('attributed merge requires reviewer / delivery identity')
        if without!=[kind,operation,number,'--squash']:
            raise ValueError('unsupported attributed merge arguments; use PR number, --squash, --match-head-commit and --body-file')
        # Keep authorship from all branch commits in the squash message, independent of PR summary edits.
        from .github import paginate
        commits=paginate(client,'repos/'+repo+'/pulls/'+number+'/commits')
        if isinstance(pr.get('commits'),int) and len(commits)!=pr['commits']:
            raise ValueError('GitHub commit list is incomplete; preserve authors before merging')
        authors=[]
        for entry in commits:
            commit=entry.get('commit',{});author=commit.get('author',{})
            item=entry['sha']+' '+author.get('name','unknown')+' <'+author.get('email','unknown')+'>'
            attribution=[line for line in commit.get('message','').splitlines() if line.startswith(('Aipipe-','Co-authored-by:'))]
            authors.append(item+'\n'+'\n'.join(attribution))
        previous=pr.get('body') or ''
        core,_=split(body if body is not None else previous)
        body=core+'\n\n## 原提交作者\n\n'+'\n\n'.join(authors)
        payload={'sha':sha,'merge_method':'squash','commit_message':annotate(body,actor,'pr:merge',sha,previous)}
        return ('merge',number,payload),[]
    if kind in ('pr','issue') and operation=='edit' and number:
        resource='issues' if kind=='issue' else 'pulls'
        previous=client.request('repos/'+repo+'/'+resource+'/'+number).get('body')
    if operation in ('create','edit','comment','review','merge') and kind in ('pr','issue'):
        if body is None:raise ValueError('attributed operation requires --body-file or --body; no interactive body inference')
        annotated=annotate(body,actor,kind+':'+operation,sha,previous)
        fd,path=tempfile.mkstemp(prefix='aipipe-body-',suffix='.md')
        with os.fdopen(fd,'w') as out:out.write(annotated)
        argv+=['--body-file',path]
        return argv,[path]
    if kind in ('pr','issue') and operation in ('close','reopen'):
        comment,argv=value(argv,['--comment','-c'])
        return [*argv,'--comment',annotate(comment or ('Requested '+operation),actor,kind+':'+operation)],[]
    if body is not None:raise ValueError('body attribution is unsupported for this gh operation; use repository api with an explicit body')
    # Push and ancillary state changes are linked to the attributed commit/Review; no extra comment service.
    return argv,[]


def api_payload(path,method,payload,actor,client,repo):
    if method=='GET':return payload
    payload=dict(payload or {})
    previous=None;sha=None
    # Reviews always bind to a head, even when the caller chooses the generic API.
    match=re.fullmatch(r'pulls/(\d+)/reviews',path)
    if match and method=='POST':
        sha=client.request('repos/'+repo+'/pulls/'+match[1])['head']['sha']
        if payload.get('commit_id')!=sha:raise ValueError('review commit_id must equal current PR head')
        if payload.get('event') in ('APPROVE','REQUEST_CHANGES') and actor['role']!='reviewer':raise ValueError('review decision requires reviewer identity')
    if path.endswith('/merge'):
        raise ValueError('use attributed github pr merge for author-preserving squash metadata')
    resource=re.fullmatch(r'(issues|pulls|milestones)/[1-9][0-9]*',path)
    if resource and method=='PATCH':
        field='description' if resource[1]=='milestones' else 'body'
        if field not in payload:payload[field]=client.request('repos/'+repo+'/'+path).get(field) or ''
    if match and method=='POST' and not payload.get('body'):
        raise ValueError('review needs a substantive report body')
    for field in ('body','description'):
        if field not in payload:continue
        if not isinstance(payload[field],str):raise ValueError('operation '+field+' must be text')
        if method=='PATCH':previous=client.request('repos/'+repo+'/'+path).get(field)
        payload[field]=annotate(payload[field],actor,'api:'+method+' '+path,sha,previous)
    return payload


def verify_commits(root, data, actor, published_base=None):
    """Opt-in rollout baseline exempts history, never silently rewrites it."""
    policy=data.get('attribution',{})
    if not policy.get('required'):return
    if subprocess.check_output(['git','rev-parse','--is-shallow-repository'],cwd=root,text=True).strip()=='true':
        raise ValueError('attribution verification requires complete Git history; fetch full history before push')
    exclusions=[]
    if published_base:
        if not re.fullmatch('[0-9a-f]{40}',published_base):raise ValueError('published base must be a full SHA')
        subprocess.run(['git','cat-file','-e',published_base+'^{commit}'],cwd=root,check=True,capture_output=True)
        common=subprocess.run(['git','merge-base',published_base,'HEAD'],cwd=root,capture_output=True)
        if common.returncode:raise ValueError('HEAD has no shared history with the published default branch')
        exclusions.append(published_base)
    baseline=policy.get('legacy_before')
    if baseline:
        if not re.fullmatch('[0-9a-f]{40}',baseline):raise ValueError('attribution.legacy_before must be a full SHA')
        ancestor=subprocess.run(['git','merge-base','--is-ancestor',baseline,'HEAD'],cwd=root,capture_output=True)
        if ancestor.returncode==0:exclusions.append(baseline)
        elif not published_base:raise ValueError('attribution rollout baseline must be an ancestor of HEAD without a published default branch')
        # Squash replaces the branch ancestry. Already published main is exempt;
        # an obsolete rollout SHA grants no exemption to any new branch commit.
    selection=['HEAD']+(['--not',*exclusions] if exclusions else [])
    result=subprocess.run(['git','rev-list','--reverse',*selection],cwd=root,text=True,capture_output=True,check=True)
    for sha in result.stdout.splitlines():
        result=subprocess.run(['git','show','-s','--format=%an%x00%ae%x00%B',sha],cwd=root,text=True,capture_output=True,check=True)
        name,mail,body=result.stdout.split('\0',2)
        values={}
        for key in ('Agent','Tool','Model','Role','Credential-Role','Issue'):
            matches=re.findall(r'^Aipipe-'+key+r': (.+)$',body,re.M)
            if len(matches)!=1:raise ValueError(sha+': missing or conflicting author metadata; use aipipe commit for new work')
            values[key]=matches[0]
        recorded={'schema_version':1,'agent_id':values['Agent'],'tool':values['Tool'],'model':values['Model'],
                  'role':values['Role'],'credential_role':values['Credential-Role'],'repository':actor['repository']}
        validate(recorded)
        if name!=label(recorded) or mail!=email(recorded):raise ValueError(sha+': author does not match recorded code writer')
        if not re.fullmatch(re.escape(actor['repository'])+r'#[1-9][0-9]*',values['Issue']):raise ValueError(sha+': wrong Issue repository in author metadata')
