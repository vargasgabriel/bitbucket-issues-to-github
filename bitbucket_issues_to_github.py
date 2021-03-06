#!/usr/bin/python
import json
import sys
import os
from dateutil import parser
import requests
from requests import Request
from requests_toolbelt.utils import dump
import requests_toolbelt
import config


def repo_url():
    return 'https://api.github.com/repos/' + config.TARGET_REPO


def issue_url():
    return repo_url() + '/issues'


def comment_url(issue_id):
    return issue_url() + '/' + issue_id + '/comments'


def project_url():
    return 'https://api.github.com/projects'


def project_columns_url(project_id):
    return project_url() + '/' + project_id + '/columns'


def project_cards_url(column_id):
    return project_url() + '/columns/' + column_id + '/cards'


def do_request(req):
    prep_req = req.prepare()
    s = requests.session()
    res = s.send(prep_req)
    data = dump.dump_all(res)
    print(data.decode('utf-8'))
    if not res.ok:
        res.raise_for_status()
    return res


def read_json_file(f):
    json_object = json.load(f)
    return json_object


def get_github_access_token():
    if 'GITHUB_ACCESS_TOKEN' in os.environ:
        return os.environ['GITHUB_ACCESS_TOKEN']
    else:
        return None


def do_github_request(req):
    headers = {
        'User-Agent': requests_toolbelt.user_agent('bitbucket_issues_to_github', '1.0.0'),
        'Accept': 'application/vnd.github.inertia-preview+json'
    }
    if get_github_access_token() is not None:
        headers['Authorization'] = 'token ' + get_github_access_token()
    req.headers.update(headers)
    return do_request(req)


def query_all_repo_gissues():
    # The issues endpoint is a paginated API.
    # We need to iterate over all issues to make this script idempotent.
    query_url = issue_url()
    issues = []
    while True:
        res = do_github_request(Request('GET', url=query_url, params={'per_page': 100, 'state': 'all'}))
        issues.extend(res.json())
        if 'next' in res.links:
            query_url = res.links['next']['url']
        else:
            break
    return issues


def query_all_project_columns():
    project_id = config.GITHUB_PROJECT_ID
    if project_id is None:
        return []
    query_url = project_columns_url(str())
    columns = []
    while True:
        res = do_github_request(Request('GET', url=query_url, params={'per_page': 100, 'state': 'all'}))
        columns.extend(res.json())
        if 'next' in res.links:
            query_url = res.links['next']['url']
        else:
            break
    return columns


def post_bissue_to_github(bissue):
    # We patch the remaining elements right after posting the issue.
    incomplete_gissue = {
        "title": bissue['title'],
        "body": bissue['content'],
    }
    res = do_github_request(Request('POST', url=issue_url(), json=incomplete_gissue))
    full_gissue = res.json()
    return full_gissue


def post_project_card(gissue, bissue, gmap_project_columns):
    bstatus = bissue['status']
    if bstatus not in config.STATE_MAPPING_PROJECT_COLUMNS:
        return
    gcolumn_name = config.STATE_MAPPING_PROJECT_COLUMNS[bstatus]
    column_id = gmap_project_columns[gcolumn_name]
    gcard = {
        "content_id": gissue['id'],
        "content_type": "Issue"
    }
    do_github_request(Request('POST', url=project_cards_url(column_id=str(column_id)), json=gcard))


def is_gissue_patch_different(gissue, gissue_patch):
    if gissue['state'] != gissue_patch['state']:
        return True
    if gissue['body'] != gissue_patch['body']:
        return True

    patch_assignees = set(gissue_patch['assignees'])
    current_assignees = set(map(lambda assignee: assignee['login'], gissue['assignees']))
    if current_assignees != patch_assignees:
        return True

    patch_labels = set(gissue_patch['labels'])
    current_labels = set(map(lambda label: label['name'], gissue['labels']))
    if current_labels != patch_labels:
        return True
    return False


def map_bstatus_to_gstate(bissue):
    bstatus = bissue['status']
    if bstatus in config.OPEN_ISSUE_STATES:
        return 'open'
    else:
        return 'closed'


def map_bassignee_to_gassignees(bissue):
    bassignee = bissue['assignee']
    if bassignee is None:
        return []
    elif bassignee in config.USER_MAPPING:
        return [config.USER_MAPPING[bassignee]]
    else:
        return []


def map_bstatus_to_glabels(bissue, glabels):
    bstatus = bissue['status']
    if bstatus in config.STATE_MAPPING:
        glabels.add(config.STATE_MAPPING[bstatus])


def map_bkind_to_glabels(bissue, glabels):
    bkind = bissue['kind']
    if bkind in config.KIND_MAPPING:
        label = config.KIND_MAPPING[bkind]
    else:
        label = bkind
    glabels.add(label)


def map_project_columns(gproject_columns):
    gmap_project_columns = {}
    for gproject_column in gproject_columns:
        gmap_project_columns[gproject_column['name']] = gproject_column['id']
    return gmap_project_columns


def time_string_to_datetime_string(timestring):
    return parser.parse(timestring).strftime("%Y-%m-%d %H:%M:%S")


def append_time_label(sb, timestring, label):
    sb.append('\n[' + label + ': ' + timestring + ']')


def construct_gcomment_content(gissue, bcomment):
    content = bcomment['content']
    if content is None:
        return None
    comment_label = 'Comment created by ' + bcomment['user']
    comment_created_on = time_string_to_datetime_string(timestring=bcomment['created_on'])
    sb = []
    append_time_label(sb=sb, timestring=comment_created_on, label=comment_label)
    sb.append('\n')
    sb.append(content)
    return ''.join(sb)


def post_gcomment(gissue, bcomment):
    # TODO get all comments on the github issue and compare the comment hash with bitbucket comment hash
    gcomment = construct_gcomment_content(gissue=gissue, bcomment=bcomment)
    if gcomment is None:
        return
    do_github_request(Request('POST', url=comment_url(str(gissue['number'])), json={ "body": gcomment }))


def append_bcomment(sb, bcomment):
    content = bcomment['content']
    if content is None:
        return  # There are bitbucket comments without any content. We ignore them.
    sb.append('\n')
    comment_label = 'Comment created by ' + bcomment['user']
    comment_created_on = time_string_to_datetime_string(timestring=bcomment['created_on'])
    append_time_label(sb=sb, timestring=comment_created_on, label=comment_label)
    sb.append('\n')
    sb.append(content)


def construct_gissue_content(bissue, bexport):
    sb = [bissue['content'], '\n']
    created_on = time_string_to_datetime_string(timestring=bissue['created_on'])
    updated_on = time_string_to_datetime_string(timestring=bissue['updated_on'])
    append_time_label(sb=sb, timestring=created_on, label='Issue created by ' + bissue['reporter'])
    if created_on != updated_on:
        append_time_label(sb=sb, timestring=updated_on, label='Last updated on bitbucket')

    # TODO option to append comment on issue content
    # bcomments = bexport.comment_map[bissue['id']]
    # for bcomment in bcomments:
    #     append_bcomment(sb=sb, bcomment=bcomment)
    return ''.join(sb)


def patch_gissue(gissue, bissue, bexport):
    if gissue['title'] != bissue['title']:
        raise ValueError('Inconsistent issues')

    glabels = set()
    map_bkind_to_glabels(bissue=bissue, glabels=glabels)
    map_bstatus_to_glabels(bissue=bissue, glabels=glabels)

    gissue_patch = {
        "body": construct_gissue_content(bissue=bissue, bexport=bexport),
        "assignees": map_bassignee_to_gassignees(bissue=bissue),
        "labels": list(glabels),
        "state": map_bstatus_to_gstate(bissue=bissue),
    }
    if is_gissue_patch_different(gissue=gissue, gissue_patch=gissue_patch):
        do_github_request(Request('PATCH', url=issue_url() + '/' + str(gissue['number']), json=gissue_patch))
    else:
        print('Skip issue "' + gissue['title'] + '" since there are no changes compared to ' + repo_url())

    bcomments = bexport.comment_map[bissue['id']]
    for bcomment in bcomments:
        post_gcomment(gissue=gissue, bcomment=bcomment)


def find_gissue_with_bissue_title(gissues, bissue):
    for gissue in gissues:
        if gissue['title'] == bissue['title']:
            return gissue
    return None


def bitbucket_to_github(bexport):
    bissues = bexport.bissues
    old_gissues = query_all_repo_gissues()
    gproject_columns = query_all_project_columns()

    gmap_project_columns = map_project_columns(gproject_columns=gproject_columns)

    print('Number of github issues in ' + repo_url() + ' before POSTing:', len(old_gissues))
    print('Number of bitbucket issues in ' + bexport.f_name + ':', len(bissues))

    for bissue in bissues:
        gissue = find_gissue_with_bissue_title(gissues=old_gissues, bissue=bissue)
        if gissue is None:
            gissue = post_bissue_to_github(bissue=bissue)
        patch_gissue(gissue=gissue, bissue=bissue, bexport=bexport)

        if gmap_project_columns:
            post_project_card(gissue=gissue, bissue=bissue, gmap_project_columns=gmap_project_columns)


class BitbucketExport:
    def __init__(self, bissues, comment_map, f_name):
        self.bissues = bissues
        self.comment_map = comment_map
        self.f_name = f_name


def parse_bitbucket_export(f, f_name):
    print('Parsing ' + f_name + '...')
    bexport_json = read_json_file(f)
    bissues = bexport_json['issues']
    if len(bissues) == 0:
        raise ValueError('Could not find any issue in ' + f_name)
    bissues = sorted(bissues, key=lambda x: x['id'])
    comments = bexport_json['comments']
    comment_map = {}
    for bissue in bissues:
        comment_map[bissue['id']] = []
    for comment in comments:
        bissue_idx = comment['issue']
        comment_map[bissue_idx].append(comment)
    for comments in comment_map.values():
        comments.reverse()
    return BitbucketExport(bissues=bissues, comment_map=comment_map, f_name=f_name)


def main():
    if len(sys.argv) < 2:
        print('Usage: ' + sys.argv[0] + ' <bitbucket export json file>')
        exit(-1)
    f_name = sys.argv[1]

    if config.TARGET_REPO is None:
        sys.exit('Error: Configure TARGET_REPO in config.py')


    if get_github_access_token() is None:
        print('Warning: Environment variable GITHUB_ACCESS_TOKEN is not set. This script will fail for private repositories.')

    with open(f_name, 'r', encoding='utf8') as f:
        bexport = parse_bitbucket_export(f=f, f_name=f_name)
        bitbucket_to_github(bexport=bexport)


main()
