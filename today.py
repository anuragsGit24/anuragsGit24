import datetime
from dateutil import relativedelta
import requests
import os
from lxml import etree
import time
import hashlib

HEADERS = {'authorization': 'token '+ os.environ['ACCESS_TOKEN']}
USER_NAME = os.environ['USER_NAME'] 
QUERY_COUNT = {'user_getter': 0, 'follower_getter': 0, 'graph_repos_stars': 0, 'recursive_loc': 0, 'graph_commits': 0, 'loc_query': 0}

def daily_readme(start_date):
    diff = relativedelta.relativedelta(datetime.datetime.today(), start_date)
    return '{} {}, {} {}, {} {}'.format(
        diff.years, 'year' + format_plural(diff.years),
        diff.months, 'month' + format_plural(diff.months),
        diff.days, 'day' + format_plural(diff.days))

def format_plural(unit): return 's' if unit != 1 else ''

def graphql_request(query, variables, retries=6):
    last_error = 'unknown error'
    for attempt in range(1, retries + 1):
        request = None
        try:
            request = requests.post('https://api.github.com/graphql',
                                    json={'query': query, 'variables': variables},
                                    headers=HEADERS, timeout=120)
        except requests.exceptions.RequestException as e:
            last_error = 'connection error: ' + str(e)
        ok = False
        if request is not None:
            status = request.status_code
            if status == 200:
                try: body = request.json()
                except ValueError: body = None
                if body is None or 'errors' in body:
                    last_error = 'GraphQL errors in response body'
                    if body is not None and 'errors' in body:
                        if any(str(e.get('type', '')).upper() == 'RATE_LIMITED' for e in body['errors']):
                            reset = request.headers.get('X-RateLimit-Reset')
                            if reset:
                                try:
                                    wait = max(5, int(reset) - int(time.time()) + 2)
                                    time.sleep(wait)
                                    continue
                                except ValueError: pass
                else: ok = True
            else:
                last_error = 'HTTP ' + str(status)
                if status == 403 and request.headers.get('X-RateLimit-Remaining') == '0':
                    reset = request.headers.get('X-RateLimit-Reset')
                    if reset:
                        try:
                            wait = max(5, int(reset) - int(time.time()) + 2)
                            time.sleep(wait)
                            continue
                        except ValueError: pass
        if ok:
            _pace_requests(request)
            return request
        wait = 5 * (2 ** (attempt - 1))
        if request is not None and 'Retry-After' in request.headers:
            try: wait = max(wait, int(request.headers['Retry-After']) + 2)
            except ValueError: pass
        time.sleep(wait)
    raise Exception('GraphQL request failed after ' + str(retries) + ' attempts (' + last_error + ')')

def _pace_requests(request):
    remaining = request.headers.get('X-RateLimit-Remaining')
    reset = request.headers.get('X-RateLimit-Reset')
    if remaining is None or reset is None: return
    try:
        remaining = int(remaining)
        reset = int(reset)
    except ValueError: return
    if remaining < 10:
        sleep_for = max(0, reset - int(time.time())) + 2
        time.sleep(sleep_for)

def simple_request(func_name, query, variables): return graphql_request(query, variables)

def graph_commits(start_date, end_date):
    query_count('graph_commits')
    query = '''
    query($start_date: DateTime!, $end_date: DateTime!, $login: String!) {
        user(login: $login) { contributionsCollection(from: $start_date, to: $end_date) { contributionCalendar { totalContributions } } }
    }'''
    variables = {'start_date': start_date,'end_date': end_date, 'login': USER_NAME}
    request = simple_request(graph_commits.__name__, query, variables)
    return int(request.json()['data']['user']['contributionsCollection']['contributionCalendar']['totalContributions'])

def graph_repos_stars(count_type, owner_affiliation, cursor=None, add_loc=0, del_loc=0):
    query_count('graph_repos_stars')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) { repositories(first: 100, after: $cursor, ownerAffiliations: $owner_affiliation) {
                totalCount
                edges { node { ... on Repository { nameWithOwner stargazers { totalCount } } } }
                pageInfo { endCursor hasNextPage } } }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(graph_repos_stars.__name__, query, variables)
    if request.status_code == 200:
        if count_type == 'repos': return request.json()['data']['user']['repositories']['totalCount']
        elif count_type == 'stars': return stars_counter(request.json()['data']['user']['repositories']['edges'])

def recursive_loc(owner, repo_name, data, cache_comment, addition_total=0, deletion_total=0, my_commits=0, cursor=None):
    query_count('recursive_loc')
    query = '''
    query ($repo_name: String!, $owner: String!, $cursor: String) {
        repository(name: $repo_name, owner: $owner) { defaultBranchRef { target { ... on Commit { history(first: 100, after: $cursor) {
                            totalCount
                            edges { node { ... on Commit { committedDate } author { user { id } } deletions additions } }
                            pageInfo { endCursor hasNextPage } } } } } }
    }'''
    variables = {'repo_name': repo_name, 'owner': owner, 'cursor': cursor}
    try: request = graphql_request(query, variables)
    except Exception:
        force_close_file(data, cache_comment)
        raise
    if request.json()['data']['repository']['defaultBranchRef'] != None:
        return loc_counter_one_repo(owner, repo_name, data, cache_comment, request.json()['data']['repository']['defaultBranchRef']['target']['history'], addition_total, deletion_total, my_commits)
    return 0

def loc_counter_one_repo(owner, repo_name, data, cache_comment, history, addition_total, deletion_total, my_commits):
    for node in history['edges']:
        try: author_user = node['node']['author']['user']
        except (TypeError, KeyError): author_user = None
        if author_user == OWNER_ID:
            my_commits += 1
            addition_total += node['node']['additions']
            deletion_total += node['node']['deletions']

    if history['edges'] == [] or not history['pageInfo']['hasNextPage']: return addition_total, deletion_total, my_commits
    else: return recursive_loc(owner, repo_name, data, cache_comment, addition_total, deletion_total, my_commits, history['pageInfo']['endCursor'])

def loc_query(owner_affiliation, comment_size=0, force_cache=False, cursor=None, edges=[]):
    query_count('loc_query')
    query = '''
    query ($owner_affiliation: [RepositoryAffiliation], $login: String!, $cursor: String) {
        user(login: $login) { repositories(first: 60, after: $cursor, ownerAffiliations: $owner_affiliation) {
            edges { node { ... on Repository { nameWithOwner defaultBranchRef { target { ... on Commit { history { totalCount } } } } } } }
            pageInfo { endCursor hasNextPage } } }
    }'''
    variables = {'owner_affiliation': owner_affiliation, 'login': USER_NAME, 'cursor': cursor}
    request = simple_request(loc_query.__name__, query, variables)
    if request.json()['data']['user']['repositories']['pageInfo']['hasNextPage']:
        edges += request.json()['data']['user']['repositories']['edges']
        return loc_query(owner_affiliation, comment_size, force_cache, request.json()['data']['user']['repositories']['pageInfo']['endCursor'], edges)
    else:
        return cache_builder(edges + request.json()['data']['user']['repositories']['edges'], comment_size, force_cache)

def cache_builder(edges, comment_size, force_cache, loc_add=0, loc_del=0):
    cached = True
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt'
    try:
        with open(filename, 'r') as f: data = f.readlines()
    except FileNotFoundError:
        data = []
        if comment_size > 0:
            for _ in range(comment_size): data.append('This line is a comment block. Write whatever you want here.\n')
        with open(filename, 'w') as f: f.writelines(data)

    if len(data)-comment_size != len(edges) or force_cache:
        cached = False
        flush_cache(edges, filename, comment_size)
        with open(filename, 'r') as f: data = f.readlines()

    cache_comment = data[:comment_size]
    data = data[comment_size:]
    for index in range(len(edges)):
        try:
            parts = data[index].split()
            repo_hash = parts[0]
        except (IndexError, ValueError): repo_hash = ''
        expected = hashlib.sha256(edges[index]['node']['nameWithOwner'].encode('utf-8')).hexdigest()
        if repo_hash != expected:
            repo_hash = expected
            data[index] = repo_hash + ' 0 0 0 0\n'
            commit_count = 0
        else:
            try: commit_count = int(parts[1])
            except (IndexError, ValueError):
                commit_count = 0
                data[index] = repo_hash + ' 0 0 0 0\n'
        try:
            try: total = edges[index]['node']['defaultBranchRef']['target']['history']['totalCount']
            except TypeError: total = 0
            if commit_count != total:
                owner, repo_name = edges[index]['node']['nameWithOwner'].split('/')
                loc = recursive_loc(owner, repo_name, data, cache_comment)
                data[index] = repo_hash + ' ' + str(total) + ' ' + str(loc[2]) + ' ' + str(loc[0]) + ' ' + str(loc[1]) + '\n'
        except Exception as e: print('Skipping', edges[index]['node']['nameWithOwner'], 'for this run:', e)
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)
    for line in data:
        try:
            loc = line.split()
            if len(loc) >= 5:
                loc_add += int(loc[3])
                loc_del += int(loc[4])
        except ValueError: continue
    return [loc_add, loc_del, loc_add - loc_del, cached]

def flush_cache(edges, filename, comment_size):
    with open(filename, 'r') as f:
        data = []
        if comment_size > 0: data = f.readlines()[:comment_size]
    with open(filename, 'w') as f:
        f.writelines(data)
        for node in edges:
            f.write(hashlib.sha256(node['node']['nameWithOwner'].encode('utf-8')).hexdigest() + ' 0 0 0 0\n')

def force_close_file(data, cache_comment):
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt'
    with open(filename, 'w') as f:
        f.writelines(cache_comment)
        f.writelines(data)

def stars_counter(data):
    total_stars = 0
    for node in data: total_stars += node['node']['stargazers']['totalCount']
    return total_stars

def svg_overwrite(filename, age_data, commit_data, star_data, repo_data, contrib_data, follower_data, loc_data):
    tree = etree.parse(filename)
    root = tree.getroot()
    if age_data is not None: justify_format(root, 'age_data', age_data, 37)
    if commit_data is not None: justify_format(root, 'commit_data', commit_data, 12)
    if star_data is not None: justify_format(root, 'star_data', star_data, 8)
    if repo_data is not None: justify_format(root, 'repo_data', repo_data, 4)
    if contrib_data is not None: justify_format(root, 'contrib_data', contrib_data)
    if follower_data is not None: justify_format(root, 'follower_data', follower_data, 8)
    if loc_data is not None:
        if loc_data[2] != '-': justify_format(root, 'loc_data', loc_data[2], 9)
        if loc_data[0] != '-': justify_format(root, 'loc_add', loc_data[0])
        if loc_data[1] != '-': justify_format(root, 'loc_del', loc_data[1], 7)
    tree.write(filename, encoding='utf-8', xml_declaration=True)

def justify_format(root, element_id, new_text, length=0):
    if isinstance(new_text, int): new_text = f"{'{:,}'.format(new_text)}"
    new_text = str(new_text)
    find_and_replace(root, element_id, new_text)
    just_len = max(0, length - len(new_text))
    if just_len <= 2:
        dot_map = {0: '', 1: ' ', 2: '. '}
        dot_string = dot_map[just_len]
    else:
        dot_string = ' ' + ('.' * just_len) + ' '
    find_and_replace(root, f"{element_id}_dots", dot_string)

def find_and_replace(root, element_id, new_text):
    element = root.find(f".//*[@id='{element_id}']")
    if element is not None: element.text = new_text

def commit_counter(comment_size):
    total_commits = 0
    filename = 'cache/'+hashlib.sha256(USER_NAME.encode('utf-8')).hexdigest()+'.txt'
    with open(filename, 'r') as f: data = f.readlines()
    data = data[comment_size:]
    for line in data:
        try: total_commits += int(line.split()[2])
        except (IndexError, ValueError): continue
    return total_commits

def user_getter(username):
    query_count('user_getter')
    query = '''
    query($login: String!){ user(login: $login) { id createdAt } }'''
    variables = {'login': username}
    request = simple_request(user_getter.__name__, query, variables)
    return {'id': request.json()['data']['user']['id']}, request.json()['data']['user']['createdAt']

def follower_getter(username):
    query_count('follower_getter')
    query = '''
    query($login: String!){ user(login: $login) { followers { totalCount } } }'''
    request = simple_request(follower_getter.__name__, query, {'login': username})
    return int(request.json()['data']['user']['followers']['totalCount'])

def query_count(funct_id):
    global QUERY_COUNT
    QUERY_COUNT[funct_id] += 1

def perf_counter(funct, *args):
    start = time.perf_counter()
    funct_return = funct(*args)
    return funct_return, time.perf_counter() - start

if __name__ == '__main__':
    OWNER_ID = None
    try:
        user_data, _ = perf_counter(user_getter, USER_NAME)
        OWNER_ID, acc_date = user_data
    except Exception as e: print('Could not fetch account data:', e)

    age_data = None
    try:
        # Utilizing your engineering start date (Aug 2023)
        age_data, _ = perf_counter(daily_readme, datetime.datetime(2023, 8, 1))
    except Exception as e: print('Could not calculate age:', e)

    total_loc = ['-', '-', '-']
    try:
        total_loc_raw, _ = perf_counter(loc_query, ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'], 7)
        if total_loc_raw is None: raise Exception('loc_query returned no data')
        total_loc = [str(v) for v in total_loc_raw[:3]]
    except Exception as e: print('LOC calculation failed:', e)

    commit_data = None
    try: commit_data, _ = perf_counter(commit_counter, 7)
    except Exception as e: print('Could not count commits:', e)

    star_data, repo_data, contrib_data, follower_data = None, None, None, None
    try: star_data, _ = perf_counter(graph_repos_stars, 'stars', ['OWNER'])
    except Exception as e: pass
    try: repo_data, _ = perf_counter(graph_repos_stars, 'repos', ['OWNER'])
    except Exception as e: pass
    try: contrib_data, _ = perf_counter(graph_repos_stars, 'repos', ['OWNER', 'COLLABORATOR', 'ORGANIZATION_MEMBER'])
    except Exception as e: pass
    try: follower_data, _ = perf_counter(follower_getter, USER_NAME)
    except Exception as e: pass

    if total_loc != ['-', '-', '-']:
        for index in range(3): total_loc[index] = '{:,}'.format(int(total_loc[index]))

    try:
        svg_overwrite('dark_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc)
        svg_overwrite('light_mode.svg', age_data, commit_data, star_data, repo_data, contrib_data, follower_data, total_loc)
    except Exception as e:
        print('Could not write SVG files:', e)
        raise