import os
import json
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from atproto import Client

USERNAME = os.getenv("BSKY_USERNAME")
PASSWORD = os.getenv("BSKY_PASSWORD")
STATE_FILE = os.getenv("STATE_FILE", "state_eyescandy.json")

MAX_PER_RUN = int(os.getenv("MAX_PER_RUN", "100"))
MAX_PER_USER = int(os.getenv("MAX_PER_USER", "3"))
SLEEP_SECONDS = float(os.getenv("SLEEP_SECONDS", "1.5"))
HOURS_BACK = int(os.getenv("HOURS_BACK", "3"))

OWN_REPOST_SLOTS = 3
OTHER_REPOST_LIMIT = MAX_PER_RUN - OWN_REPOST_SLOTS  # 97

FEEDS = [
    {"name": "lijst", "url": ""},
    {"name": "redfox", "url": "https://bsky.app/profile/did:plc:jaka644beit3x4vmmg6yysw7/feed/aaae6jfc5w2oi"},
    {"name": "my accounts", "url": "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/feed/aaaji5emthgtg"},
]

LISTS = [
    {"name": "lijst", "url": ""},
    {"name": "repost always", "url": "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mncvshsuhi2d"},
    {"name": "", "url": ""},
]

HASHTAGS = [
    {"tag": "#eyescandy", "exclude_list": "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mnianivya72q"},
    {"tag": "#bskypromo", "exclude_list": "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mniamoz32f2n"},
    {"tag": "", "exclude_list": ""},
]

GLOBAL_EXCLUDE_LISTS = [
    "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mnianivya72q",
    "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mniamoz32f2n",
]


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"reposted": []}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

        if "reposted" not in state:
            state["reposted"] = []

        return state

    except Exception:
        return {"reposted": []}


def save_state(state):
    state["reposted"] = list(dict.fromkeys(state["reposted"]))[-10000:]

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def get_rkey(url):
    return url.rstrip("/").split("/")[-1]


def get_actor_from_url(url):
    parts = url.rstrip("/").split("/")
    return parts[parts.index("profile") + 1]


def resolve_actor(client, actor):
    if actor.startswith("did:"):
        return actor

    return client.com.atproto.identity.resolve_handle({
        "handle": actor
    }).did


def get_created_at(post):
    try:
        return datetime.fromisoformat(
            post.record.created_at.replace("Z", "+00:00")
        )
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def sort_old_to_new(posts):
    return sorted(posts, key=get_created_at)


def has_media(post):
    embed = getattr(post.record, "embed", None)
    if not embed:
        return False

    text = str(embed).lower()
    return "images" in text or "video" in text


def is_reply(post):
    return bool(getattr(post.record, "reply", None))


def is_quote(post):
    embed = getattr(post.record, "embed", None)
    if not embed:
        return False

    text = str(embed).lower()
    return "app.bsky.embed.record" in text or "recordwithmedia" in text


def is_repost_item(item):
    return getattr(item, "reason", None) is not None


def is_valid_media_post(post):
    if not has_media(post):
        return False
    if is_reply(post):
        return False
    if is_quote(post):
        return False

    return True


def is_recent(post):
    try:
        created = get_created_at(post)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS_BACK)
        return created >= cutoff

    except Exception:
        return False


def repost_and_like(client, post, state, per_user):
    uri = post.uri
    cid = post.cid
    author = post.author.did

    if uri in state["reposted"]:
        return False

    if per_user[author] >= MAX_PER_USER:
        return False

    if not is_valid_media_post(post):
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
        print(f"Reposted: {post.author.handle} - {uri}")
        time.sleep(SLEEP_SECONDS)
        return True

    except Exception as e:
        print(f"Repost error: {e}")
        return False


def get_feed_posts(client, feed_url):
    actor = get_actor_from_url(feed_url)
    rkey = get_rkey(feed_url)
    did = resolve_actor(client, actor)

    feed_uri = f"at://{did}/app.bsky.feed.generator/{rkey}"

    data = client.app.bsky.feed.get_feed({
        "feed": feed_uri,
        "limit": 100
    })

    posts = []

    for item in data.feed:
        if is_repost_item(item):
            continue

        post = item.post

        if not is_valid_media_post(post):
            continue

        posts.append(post)

    return sort_old_to_new(posts)


def get_list_members(client, list_url):
    actor = get_actor_from_url(list_url)
    rkey = get_rkey(list_url)
    did = resolve_actor(client, actor)

    list_uri = f"at://{did}/app.bsky.graph.list/{rkey}"

    members = []
    cursor = None

    while True:
        params = {
            "list": list_uri,
            "limit": 100
        }

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
                "limit": 30,
                "filter": "posts_with_replies"
            })

            for item in data.feed:
                if is_repost_item(item):
                    continue

                post = item.post

                if not is_valid_media_post(post):
                    continue

                posts.append(post)

        except Exception as e:
            print(f"Author scan error: {e}")

    return sort_old_to_new(posts)


def get_excluded_dids(client, list_url):
    if not list_url.strip():
        return set()

    try:
        return set(get_list_members(client, list_url))

    except Exception as e:
        print(f"Exclude list error: {e}")
        return set()


def get_hashtag_posts(client, tag):
    tag = tag.strip()
    if not tag:
        return []

    clean_tag = tag.replace("#", "").strip().lower()
    query = f"#{clean_tag}"

    data = client.app.bsky.feed.search_posts({
        "q": query,
        "limit": 100,
        "sort": "latest"
    })

    posts = []

    for post in data.posts:
        text = getattr(post.record, "text", "") or ""

        if f"#{clean_tag}" not in text.lower():
            continue

        if not is_valid_media_post(post):
            continue

        posts.append(post)

    return sort_old_to_new(posts)


def repost_own_latest_media(client):
    print("Scanning own latest media posts")

    try:
        my_did = client.me.did

        data = client.app.bsky.feed.get_author_feed({
            "actor": my_did,
            "limit": 100,
            "filter": "posts_with_replies"
        })

        own_media = []

        for item in data.feed:
            if is_repost_item(item):
                continue

            post = item.post

            if post.author.did != my_did:
                continue

            if not is_valid_media_post(post):
                continue

            own_media.append(post)

            if len(own_media) >= OWN_REPOST_SLOTS:
                break

        own_media = sort_old_to_new(own_media)

        print(f"Own media posts found: {len(own_media)}")

        # Oudste eerst, nieuwste als laatste.
        # Daardoor eindigt de nieuwste eigen post bovenaan.
        for post in own_media:
            try:
                viewer = getattr(post, "viewer", None)
                old_repost = getattr(viewer, "repost", None) if viewer else None

                if old_repost:
                    try:
                        client.delete_repost(old_repost)
                        print(f"Deleted old own repost: {post.uri}")
                        time.sleep(SLEEP_SECONDS)
                    except Exception as e:
                        print(f"Delete own repost skipped/error: {e}")

                time.sleep(SLEEP_SECONDS)

                client.repost(post.uri, post.cid)
                print(f"Own post reposted on top: {post.uri}")
                time.sleep(SLEEP_SECONDS)

            except Exception as e:
                print(f"Own repost error: {e}")

    except Exception as e:
        print(f"Own media scan error: {e}")


def main():
    print("=== EYESCANDY REPOSTER STARTED ===")

    client = Client()
    client.login(USERNAME, PASSWORD)

    my_did = client.me.did

    state = load_state()
    per_user = defaultdict(int)
    total = 0

    excluded_global = set()

    for exclude_url in GLOBAL_EXCLUDE_LISTS:
        if exclude_url.strip():
            excluded_global.update(get_excluded_dids(client, exclude_url))

    print(f"Global excluded accounts: {len(excluded_global)}")
    print(f"Normal repost limit: {OTHER_REPOST_LIMIT}")
    print(f"Own repost slots last: {OWN_REPOST_SLOTS}")
    print("Post order: old -> new")

    PROCESS_ORDER = [
        ("hashtag", HASHTAGS[0]),
        ("hashtag", HASHTAGS[1]),
        ("hashtag", HASHTAGS[2]),

        ("feed", FEEDS[0]),
        ("list", LISTS[2]),

        ("feed", FEEDS[1]),
        ("list", LISTS[1]),

        ("feed", FEEDS[0]),
        ("list", LISTS[2]),
    ]

    for source_type, source in PROCESS_ORDER:
        if total >= OTHER_REPOST_LIMIT:
            break

        if source_type == "hashtag":
            tag = source["tag"].strip()
            if not tag:
                continue

            excluded = get_excluded_dids(client, source.get("exclude_list", ""))

            print(f"Scanning hashtag: {tag}")

            posts = get_hashtag_posts(client, tag)

            for post in posts:
                if total >= OTHER_REPOST_LIMIT:
                    break

                if post.author.did == my_did:
                    continue

                if post.author.did in excluded_global:
                    continue

                if post.author.did in excluded:
                    continue

                if not is_recent(post):
                    continue

                if not repost_and_like(client, post, state, per_user):
                    continue

                total += 1
                save_state(state)

        elif source_type == "feed":
            url = source["url"].strip()
            if not url:
                continue

            print(f"Scanning feed: {source['name']}")

            posts = get_feed_posts(client, url)

            for post in posts:
                if total >= OTHER_REPOST_LIMIT:
                    break

                if post.author.did == my_did:
                    continue

                if post.author.did in excluded_global:
                    continue

                if not is_recent(post):
                    continue

                if not repost_and_like(client, post, state, per_user):
                    continue

                total += 1
                save_state(state)

        elif source_type == "list":
            url = source["url"].strip()
            if not url:
                continue

            print(f"Scanning list: {source['name']}")

            posts = get_list_posts(client, url)

            for post in posts:
                if total >= OTHER_REPOST_LIMIT:
                    break

                if post.author.did == my_did:
                    continue

                if post.author.did in excluded_global:
                    continue

                if not is_recent(post):
                    continue

                if not repost_and_like(client, post, state, per_user):
                    continue

                total += 1
                save_state(state)

    # Altijd als laatste, hoe oud ook.
    # Je eigen laatste 3 media posts komen opnieuw bovenaan.
    repost_own_latest_media(client)

    print(f"Done. Other reposts: {total}, own repost slots: {OWN_REPOST_SLOTS}")


if __name__ == "__main__":
    main()