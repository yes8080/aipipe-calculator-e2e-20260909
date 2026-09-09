#!/usr/bin/env python3
"""Preview a batch offline; --apply creates missing GitHub items, never releases it."""
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from string import Template
import sys
import time
from urllib.parse import quote


from .context import asset
from . import identity
from .github import Gh, GhError, paginate
ROOT = Path(__file__).resolve().parent
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
READY = "aipipe:ready"


class PublishError(Exception):
    """Stop safely; do not silently overwrite or repeat writes."""


class UncertainWrite(PublishError):
    """A write may have succeeded. Reconcile its marker before another attempt."""


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise PublishError(f"{field}: expected non-empty text")


def text_list(value, field, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise PublishError(f"{field}: expected a {'possibly empty' if allow_empty else 'non-empty'} list")
    for entry in value:
        require_text(entry, field)


def validate(plan, repo, design_ref):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise PublishError("--repo must be owner/repository")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", design_ref):
        raise PublishError("--design-ref must be a full 40-character commit SHA")
    if (not isinstance(plan, dict) or not isinstance(plan.get("batch"), str)
            or not ID.fullmatch(plan["batch"])):
        raise PublishError("batch: expected a stable alphanumeric ID")
    milestone = plan.get("milestone")
    if not isinstance(milestone, dict):
        raise PublishError("milestone: expected {title, completion}")
    for key in ("title", "completion"):
        require_text(milestone.get(key), f"milestone.{key}")
    design_path = plan.get("design_path", "docs/development.md")
    require_text(design_path, "design_path")
    path = PurePosixPath(design_path)
    if (not path.parts or path.is_absolute() or ".." in path.parts
            or any(part.casefold() == ".git" for part in path.parts)
            or "\\" in design_path or re.match(r"^[A-Za-z]:", design_path)
            or any(ord(char) < 32 or ord(char) == 127 for char in design_path)):
        raise PublishError("design_path must be a safe repository-relative product design file path; "
                           "absolute paths, traversal and .git metadata are not allowed")
    slices = plan.get("slices")
    if not isinstance(slices, list) or not slices:
        raise PublishError("slices: expected a non-empty list")
    seen = set()
    for sequence, item in enumerate(slices, 1):
        if not isinstance(item, dict):
            raise PublishError("slice: expected an object")
        sid = item.get("slice_id", "")
        if not isinstance(sid, str) or not ID.fullmatch(sid) or sid in seen:
            raise PublishError(f"invalid or duplicate slice_id: {sid!r}")
        if type(item.get("sequence")) is not int or item["sequence"] != sequence:
            raise PublishError("sequences must be 1..N in file order")
        deps = item.get("depends_on")
        text_list(deps, f"{sid}.depends_on", allow_empty=True)
        if len(deps) != len(set(deps)) or not set(deps).issubset(seen):
            raise PublishError(f"{sid}: dependencies must uniquely identify earlier slices")
        for key in ("title", "goal"):
            require_text(item.get(key), f"{sid}.{key}")
        for key in ("scope", "acceptance", "test_requirements", "deliverables"):
            text_list(item.get(key), f"{sid}.{key}")
        text_list(item.get("out_of_scope", []), f"{sid}.out_of_scope", allow_empty=True)
        verification = item.get("verification")
        if not isinstance(verification, list) or not verification:
            raise PublishError(f"{sid}.verification: commands are required")
        for check in verification:
            if not isinstance(check, dict):
                raise PublishError(f"{sid}.verification: expected directory/command objects")
            require_text(check.get("directory"), f"{sid}.verification.directory")
            require_text(check.get("command"), f"{sid}.verification.command")
        seen.add(sid)


def batch_marker(plan):
    return f"<!-- aipipe:batch:{plan['batch']} -->"


def slice_marker(plan, item):
    return f"<!-- aipipe:{plan['batch']}:{item['slice_id']} -->"


def milestone_body(plan):
    return (f"{batch_marker(plan)}\naipipe:released=false\n\n"
            f"完成条件：\n{plan['milestone']['completion']}\n")


def bullets(items):
    return "\n".join(f"- {item}" for item in items) or "- 无"


def issue_body(plan, item, numbers, repo, design_ref, template, preview=False):
    dependencies = []
    for sid in item["depends_on"]:
        if sid not in numbers and not preview:
            raise PublishError(f"{item['slice_id']}: dependency {sid} has no published Issue")
        dependencies.append(f"#{numbers[sid]}" if sid in numbers else f"{sid}（发布后填入 Issue 编号）")
    commands = "\n\n".join(
        f"执行目录：`{check['directory']}`\n\n```sh\n{check['command']}\n```"
        for check in item["verification"])
    return template.substitute(
        marker=slice_marker(plan, item), batch=plan["batch"], slice_id=item["slice_id"],
        sequence=item["sequence"], dependencies=", ".join(dependencies) or "无",
        design_url=f"https://github.com/{repo}/blob/{design_ref}/{quote(plan.get('design_path', 'docs/development.md'), safe='/')}",
        goal=item["goal"], scope=bullets(item["scope"]),
        out_of_scope=bullets(item.get("out_of_scope", [])),
        acceptance="\n".join(f"- AC{n}: {entry}" for n, entry in enumerate(item["acceptance"], 1)),
        test_requirements=bullets(item["test_requirements"]),
        verification=commands, deliverables=bullets(item["deliverables"]))


def issue_title(item):
    return f"[{item['slice_id']}] {item['title']}"


class GitHub:
    def __init__(self, repo, env=None, actor=None):
        self.repo = repo
        self.actor = actor
        self.transport = Gh(env=env)

    def request(self, path, method="GET", payload=None):
        try:
            if self.actor and method!='GET' and payload and path in ('issues','milestones'):
                payload=dict(payload)
                field='body' if path=='issues' else 'description'
                payload[field]=identity.annotate(payload[field],self.actor,'publish:'+path)
            return identity.canonical(self.transport.request(f"repos/{self.repo}/{path}", method, payload))
        except GhError as exc:
            error = UncertainWrite if method != "GET" else PublishError
            raise error(f"{method} {path}: request failed; reconcile before retrying a write") from exc

    def pages(self, path):
        try:
            return paginate(self, path)
        except ValueError as exc:
            raise PublishError(str(exc)) from exc


def confirm(api, resource, identifier, expected, pause):
    """Read the object and its list entry; retry reads only, never the creation."""
    key = "name" if resource == "labels" else "number"
    suffix = "" if resource == "labels" else "?state=all"
    for attempt in range(4):
        obj = api.request(f"{resource}/{quote(str(identifier), safe='')}")
        if not isinstance(obj, dict) or any(obj.get(k) != v for k, v in expected.items()):
            raise UncertainWrite(f"{resource}/{identifier}: write confirmation differs; reconcile before proceeding")
        entries = api.pages(resource + suffix)
        if any(entry.get(key) == identifier for entry in entries):
            return obj
        if attempt < 3:
            pause(1)
    raise UncertainWrite(f"{resource}/{identifier}: object exists but is not listed; pause and reconcile")


def create(api, resource, payload, pause):
    obj = api.request(resource, "POST", payload)
    key = "name" if resource == "labels" else "number"
    if not isinstance(obj, dict) or key not in obj:
        raise UncertainWrite(f"POST {resource}: missing identifier; inspect remote state, do not blindly retry")
    expected = {k: payload[k] for k in ("name", "title", "body", "description") if k in payload}
    return confirm(api, resource, obj[key], expected, pause)


def publish(plan, repo, design_ref, template, api, pause=time.sleep, output=print):
    validate(plan, repo, design_ref)
    design = api.request(f"contents/{quote(plan.get('design_path', 'docs/development.md'), safe='/')}?ref={design_ref}")
    if not isinstance(design, dict) or design.get("type") != "file":
        raise PublishError("design-ref does not resolve to a product design file")
    milestones = api.pages("milestones?state=all")
    matches = [m for m in milestones if batch_marker(plan) in (m.get("description") or "")
               or m.get("title") == plan["milestone"]["title"]]
    if len(matches) > 1:
        raise PublishError("duplicate milestone title or batch marker; reconcile before publishing")
    milestone = matches[0] if matches else None
    released = False
    if milestone:
        description = milestone.get("description") or ""
        released = "aipipe:released=true" in description
        normalized = description.replace("aipipe:released=true", "aipipe:released=false")
        if milestone.get("title") != plan["milestone"]["title"] or normalized.rstrip('\r\n') != milestone_body(plan).rstrip('\r\n'):
            raise PublishError("existing milestone differs from plan; it will not be rewritten")

    issues = [i for i in api.pages("issues?state=all") if "pull_request" not in i]
    existing = {}
    markers = {slice_marker(plan, item): item["slice_id"] for item in plan["slices"]}
    pattern = re.compile(r"<!-- aipipe:" + re.escape(plan["batch"]) + r":[^>]+ -->")
    for issue in issues:
        found = pattern.findall(issue.get("body") or "")
        if any(marker not in markers for marker in found) or len(found) > 1:
            raise PublishError("remote batch has unexpected or repeated slice markers; reconcile the plan")
        if found:
            sid = markers[found[0]]
            if sid in existing:
                raise PublishError(f"duplicate slice marker: {sid}")
            existing[sid] = issue
    numbers = {sid: issue["number"] for sid, issue in existing.items()}
    # All immutable content is compared before the first write, including closed/active Issues.
    for item in plan["slices"]:
        if item["slice_id"] not in existing:
            continue
        issue = existing[item["slice_id"]]
        body = issue_body(plan, item, numbers, repo, design_ref, template)
        if (not milestone or issue.get("title") != issue_title(item) or issue.get("body") != body
                or (issue.get("milestone") or {}).get("number") != milestone["number"]):
            raise PublishError(f"{item['slice_id']}: existing Issue differs; no Issue will be rewritten")
    missing = len(plan["slices"]) - len(existing)
    started = any(i.get("state") != "open" or any(
        label.get("name") in ("aipipe:active", "aipipe:blocked", "aipipe:review", "aipipe:changes-requested", "aipipe:done", "aipipe:cancelled") for label in i.get("labels", []))
        for i in existing.values())
    if missing and (released or started or (milestone and milestone.get("state") != "open")):
        raise PublishError("cannot add slices to a released, started or closed batch")
    if not missing:
        output(f"No changes: reused {len(existing)} Issues; release state unchanged.")
        return numbers

    # These are the only writes: missing label, milestone, then Issues in dependency order.
    if READY not in {label["name"] for label in api.pages("labels")}:
        create(api, "labels", {"name": READY, "color": "0E8A16",
                               "description": "Eligible only after its milestone batch is released"}, pause)
    if not milestone:
        milestone = create(api, "milestones", {"title": plan["milestone"]["title"],
                                              "description": milestone_body(plan)}, pause)
    for item in plan["slices"]:
        sid = item["slice_id"]
        if sid in existing:
            output(f"Reused {sid}: #{numbers[sid]}")
            continue
        payload = {"title": issue_title(item),
                   "body": issue_body(plan, item, numbers, repo, design_ref, template),
                   "milestone": milestone["number"], "labels": [READY]}
        issue = create(api, "issues", payload, pause)
        if (issue.get("milestone") or {}).get("number") != milestone["number"]:
            raise UncertainWrite(f"Issue #{issue['number']}: milestone differs; reconcile before proceeding")
        if READY not in {label["name"] for label in issue.get("labels", [])}:
            raise UncertainWrite(f"Issue #{issue['number']}: ready label missing; reconcile before proceeding")
        numbers[sid] = issue["number"]
        output(f"Created {sid}: #{issue['number']}")
    output(f"Created {missing}; total {len(numbers)}. Batch remains unreleased; no Agent was started.")
    return numbers


def verify_complete(plan, repo, design_ref, template, api, milestone_number):
    """Reuse publishing's exact contract checks, with a transport that cannot write."""
    class ReadOnly:
        def request(self, path, method='GET', payload=None):
            if method != 'GET':
                raise PublishError('batch is incomplete; finish/reconcile publish before release')
            return api.request(path, method, payload)

        def pages(self, path):
            return api.pages(path)

    milestone = api.request('milestones/'+str(milestone_number))
    if batch_marker(plan) not in (milestone.get('description') or ''):
        raise PublishError('selected milestone does not belong to this plan')
    numbers = publish(plan, repo, design_ref, template, ReadOnly(), output=lambda _: None)
    issues = [i for i in api.pages('issues?state=all') if 'pull_request' not in i
              and (i.get('milestone') or {}).get('number') == milestone_number]
    if {i['number'] for i in issues} != set(numbers.values()):
        raise PublishError('milestone contains missing or unexpected Issues; reconcile before release')
    return numbers


def main(argv=None, env=None, template_path=None, actor=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/repository")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--design-ref", required=True, help="full commit SHA containing the product design file")
    parser.add_argument("--apply", action="store_true", help="create missing GitHub items using external gh credentials")
    args = parser.parse_args(argv)
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        template = Template((template_path or asset("templates/issue.md")).read_text(encoding="utf-8"))
        validate(plan, args.repo, args.design_ref)
        # Validate all template substitutions before any remote operation.
        previews = [(issue_title(item), issue_body(plan, item, {}, args.repo, args.design_ref, template, True))
                    for item in plan["slices"]]
        if args.apply:
            if not (os.environ if env is None else env).get("GH_TOKEN"):
                raise PublishError("--apply requires an externally supplied Delivery GH_TOKEN; "
                                   "global gh login is not used as a fallback")
            publish(plan, args.repo, args.design_ref, template, GitHub(args.repo, env=env, actor=actor))
        else:
            print("DRY RUN — offline preview; no authentication, API requests, writes or release.")
            print(f"Repository: {args.repo}\nMilestone: {plan['milestone']['title']}\n{milestone_body(plan)}")
            for title, body in previews:
                print(f"\n# {title}\n\n{body}")
        return 0
    except (PublishError, OSError, ValueError, KeyError) as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
