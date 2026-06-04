import os, json, time
from collections import defaultdict
from atproto import Client

USERNAME = os.getenv("BSKY_USERNAME")
PASSWORD = os.getenv("BSKY_PASSWORD")
STATE_FILE = os.getenv("STATE_FILE", "state_eyescandy.json")

MAX_PER_RUN = int(os.getenv("MAX_PER_RUN", "100"))
MAX_PER_USER = int(os.getenv("MAX_PER_USER", "3"))
SLEEP_SECONDS = float(os.getenv("SLEEP_SECONDS", "1.5"))

# Vul hier je 3 feeds in
FEEDS = [
    {"name": "feed1", "https://bsky.app/profile/did:plc:jaka644beit3x4vmmg6yysw7/feed/aaae6jfc5w2oi": "", "allow_replies": True},
    {"name": "feed2", "url": "", "allow_replies": True},
    {"name": "feed3", "url": "", "allow_replies": True},
]

# Vul hier je 3 lijsten in
LISTS = [
    {"name": "list1", "url": ""},
    {"name": "list2", "url": ""},
    {"name": "list3", "url": ""},
]

# Hashtags + exclude lijsten. Leeg = skip
HASHTAGS = [
    {"tag": "#eyescandy", "exclude_list": ""},
    {"tag": "#bskypromo", "exclude_list": "https://bsky.app/profile/did:plc:cxrt7ggxkamgzxa47cggtees/lists/3mkl4yhuimg2b"},
    {"tag": "", "exclude_list": ""},
]


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"reposted": []}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    state["reposted"] = list(dict.fromkeys(state["reposted"]))[-10000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_rkey(url):
    return url.rstrip("/").split("/")[-1]


def get_handle(url):
    parts = url.rstrip("/").split("/")
    if "profile" in parts:
        return parts[parts.index("profile") + 1]
    return ""


def is_reply(post):
    return bool(getattr(post.record, "reply", None))


def has_media(post):
    embed = getattr(post.record, "embed", None)
    if not embed:
        return False
    return "images" in str(embed).lower() or "video" in str(embed).lower()


def repost_and_like(client, post, state, per_user):
    uri = post.uri
    cid = post.cid
    author = post.author.did

    if uri in state["reposted"]:
        return False
    if per_user[author] >= MAX_PER_USER:
        return False
    if not has_media(post):
        return False

    try:
        client.like(uri, cid)
        time.sleep(SLEEP_SECONDS)
    except Exception as e:
        print(f"Like skipped/error: {e}")

    try:
        client.repost(uri, cid)
        state["reposted"].append(uri)
        per_user[author] += 1
        print(f"Reposted: {uri}")
        time.sleep(SLEEP_SECONDS)
        return True
    except Exception as e:
        print(f"Repost error: {e}")
        return False


def get_feed_posts(client, feed_url):
    handle = get_handle(feed_url)
    rkey = get_rkey(feed_url)
    did = client.com.atproto.identity.resolve_handle({"handle": handle}).did
    feed_uri = f"at://{did}/app.bsky.feed.generator/{rkey}"
    data = client.app.bsky.feed.get_feed({"feed": feed_uri, "limit": 100})
    return [item.post for item in data.feed]


def get_list_members(client, list_url):
    handle = get_handle(list_url)
    rkey = get_rkey(list_url)
    did = client.com.atproto.identity.resolve_handle({"handle": handle}).did
    list_uri = f"at://{did}/app.bsky.graph.list/{rkey}"

    members = []
    cursor = None

    while True:
        params = {"list": list_uri, "limit": 100}
        if cursor:
            params["cursor"] = cursor

        data = client.app.bsky.graph.get_list(params)
        members.extend([item.subject.did for item in data.items])

        cursor = getattr(data, "cursor", None)
        if not cursor:
            break

    return members


def get_list_posts(client, list_url):
    posts = []
    members = get_list_members(client, list_url)

    for did in members:
        try:
            data = client.app.bsky.feed.get_author_feed({
                "actor": did,
                "limit": 20,
                "filter": "posts_no_replies"
            })
            posts.extend([item.post for item in data.feed])
        except Exception as e:
            print(f"Author scan error: {e}")

    return posts


def get_excluded_dids(client, list_url):
    if not list_url.strip():
        return set()
    try:
        return set(get_list_members(client, list_url))
    except Exception as e:
        print(f"Exclude list error: {e}")
        return set()


def get_hashtag_posts(client, tag):
    if not tag.strip():
        return []
    q = tag if tag.startswith("#") else f"#{tag}"
    data = client.app.bsky.feed.search_posts({"q": q, "limit": 100})
    return data.posts


def main():
    print("=== EYESCANDY REPOSTER STARTED ===")

    client = Client()
    client.login(USERNAME, PASSWORD)

    state = load_state()
    per_user = defaultdict(int)
    total = 0

    # Feeds
    for feed in FEEDS:
        if total >= MAX_PER_RUN:
            break
        if not feed["url"].strip():
            continue

        print(f"Scanning feed: {feed['name']}")

        for post in get_feed_posts(client, feed["url"]):
            if total >= MAX_PER_RUN:
                break
            if is_reply(post) and not feed.get("allow_replies", True):
                continue
            if repost_and_like(client, post, state, per_user):
                total += 1
                save_state(state)

    # Lists
    for lst in LISTS:
        if total >= MAX_PER_RUN:
            break
        if not lst["url"].strip():
            continue

        print(f"Scanning list: {lst['name']}")

        for post in get_list_posts(client, lst["url"]):
            if total >= MAX_PER_RUN:
                break
            if repost_and_like(client, post, state, per_user):
                total += 1
                save_state(state)

    # Hashtags
    for item in HASHTAGS:
        if total >= MAX_PER_RUN:
            break
        tag = item["tag"].strip()
        if not tag:
            continue

        excluded = get_excluded_dids(client, item.get("exclude_list", ""))
        print(f"Scanning hashtag: {tag}")

        for post in get_hashtag_posts(client, tag):
            if total >= MAX_PER_RUN:
                break
            if post.author.did in excluded:
                continue
            if repost_and_like(client, post, state, per_user):
                total += 1
                save_state(state)

    print(f"Done. Total reposted: {total}")


if __name__ == "__main__":
    main()
