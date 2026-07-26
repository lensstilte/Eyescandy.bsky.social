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
OTHER_REPOST_LIMIT = max(0, MAX_PER_RUN - OWN_REPOST_SLOTS)


# Bij allow_replies=True worden ook media-replies uit die feed gerepost.
# Quote-posts en reposts blijven altijd uitgesloten.
FEEDS = [
    {
        "name": "lijst",
        "url": https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/feed/aaaia4sxjd6ts",
        "allow_replies": True,
    },
    {
        "name": "redfox",
        "url": "https://bsky.app/profile/did:plc:jaka644beit3x4vmmg6yysw7/feed/aaae6jfc5w2oi",
        "allow_replies": true,
    },
    {
        "name": "feed",
        "url": "",
        "allow_replies": False,
    },
]


LISTS = [
    {
        "name": "eigen",
        "url": "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mnib6r6cwk2q",
    },
    {
        "name": "repost always",
        "url": "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mncvshsuhi2d",
    },
    {
        "name": "",
        "url": "",
    },
]


HASHTAGS = [
    {
        "tag": "#eyescandy",
        "exclude_list": "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mnianivya72q",
    },
    {
        "tag": "",
        "exclude_list": "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mniamoz32f2n",
    },
    {
        "tag": "",
        "exclude_list": "",
    },
]


GLOBAL_EXCLUDE_LISTS = [
    "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mnianivya72q",
    "https://bsky.app/profile/did:plc:sp54ouue6fp2dlvn2cux54ka/lists/3mniamoz32f2n",
]


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"reposted": []}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        if not isinstance(state, dict):
            return {"reposted": []}

        if "reposted" not in state:
            state["reposted"] = []

        if not isinstance(state["reposted"], list):
            state["reposted"] = []

        return state

    except Exception as error:
        print(f"State load error: {error}")
        return {"reposted": []}


def save_state(state):
    state["reposted"] = list(
        dict.fromkeys(state.get("reposted", []))
    )[-10000:]

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=2)

    except Exception as error:
        print(f"State save error: {error}")


def get_rkey(url):
    return url.rstrip("/").split("/")[-1]


def get_actor_from_url(url):
    parts = url.rstrip("/").split("/")

    if "profile" not in parts:
        raise ValueError(f"Invalid Bluesky URL: {url}")

    profile_index = parts.index("profile")

    if profile_index + 1 >= len(parts):
        raise ValueError(f"Actor missing in URL: {url}")

    return parts[profile_index + 1]


def resolve_actor(client, actor):
    if actor.startswith("did:"):
        return actor

    result = client.com.atproto.identity.resolve_handle({
        "handle": actor
    })

    return result.did


def get_created_at(post):
    try:
        created_at = post.record.created_at

        return datetime.fromisoformat(
            created_at.replace("Z", "+00:00")
        )

    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def sort_old_to_new(posts):
    return sorted(posts, key=get_created_at)


def has_media(post):
    embed = getattr(post.record, "embed", None)

    if not embed:
        return False

    embed_text = str(embed).lower()

    return (
        "app.bsky.embed.images" in embed_text
        or "app.bsky.embed.video" in embed_text
        or "images" in embed_text
        or "video" in embed_text
    )


def is_reply(post):
    return bool(getattr(post.record, "reply", None))


def is_quote(post):
    embed = getattr(post.record, "embed", None)

    if not embed:
        return False

    embed_text = str(embed).lower()

    return (
        "app.bsky.embed.record" in embed_text
        or "recordwithmedia" in embed_text
    )


def is_repost_item(item):
    return getattr(item, "reason", None) is not None


def is_valid_media_post(post, allow_replies=False):
    if not has_media(post):
        return False

    if is_quote(post):
        return False

    if is_reply(post) and not allow_replies:
        return False

    return True


def is_recent(post):
    try:
        created_at = get_created_at(post)
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=HOURS_BACK
        )

        return created_at >= cutoff

    except Exception:
        return False


def repost_and_like(
    client,
    post,
    state,
    per_user,
    allow_replies=False,
):
    uri = post.uri
    cid = post.cid
    author_did = post.author.did

    if uri in state["reposted"]:
        return False

    if per_user[author_did] >= MAX_PER_USER:
        return False

    if not is_valid_media_post(
        post,
        allow_replies=allow_replies,
    ):
        return False

    try:
        client.like(uri, cid)
        print(f"Liked: {post.author.handle} - {uri}")
        time.sleep(SLEEP_SECONDS)

    except Exception as error:
        print(f"Like skipped/error: {error}")

    try:
        client.repost(uri, cid)

        state["reposted"].append(uri)
        per_user[author_did] += 1

        post_type = (
            "media reply"
            if is_reply(post)
            else "media post"
        )

        print(
            f"Reposted {post_type}: "
            f"{post.author.handle} - {uri}"
        )

        time.sleep(SLEEP_SECONDS)
        return True

    except Exception as error:
        print(f"Repost error: {error}")
        return False


def get_feed_posts(
    client,
    feed_url,
    allow_replies=False,
):
    actor = get_actor_from_url(feed_url)
    rkey = get_rkey(feed_url)
    did = resolve_actor(client, actor)

    feed_uri = (
        f"at://{did}/app.bsky.feed.generator/{rkey}"
    )

    posts = []
    cursor = None
    scanned_items = 0
    max_feed_items = 500

    while scanned_items < max_feed_items:
        params = {
            "feed": feed_uri,
            "limit": 100,
        }

        if cursor:
            params["cursor"] = cursor

        try:
            data = client.app.bsky.feed.get_feed(params)

        except Exception as error:
            print(f"Feed scan error: {error}")
            break

        if not data.feed:
            break

        for item in data.feed:
            scanned_items += 1

            if is_repost_item(item):
                continue

            post = item.post

            if not is_valid_media_post(
                post,
                allow_replies=allow_replies,
            ):
                continue

            posts.append(post)

            if scanned_items >= max_feed_items:
                break

        cursor = getattr(data, "cursor", None)

        if not cursor:
            break

    unique_posts = {}

    for post in posts:
        unique_posts[post.uri] = post

    result = sort_old_to_new(
        list(unique_posts.values())
    )

    print(
        f"Feed items scanned: {scanned_items}, "
        f"valid media found: {len(result)}"
    )

    return result


def get_list_members(client, list_url):
    actor = get_actor_from_url(list_url)
    rkey = get_rkey(list_url)
    did = resolve_actor(client, actor)

    list_uri = (
        f"at://{did}/app.bsky.graph.list/{rkey}"
    )

    members = []
    cursor = None

    while True:
        params = {
            "list": list_uri,
            "limit": 100,
        }

        if cursor:
            params["cursor"] = cursor

        data = client.app.bsky.graph.get_list(params)

        for item in data.items:
            member_did = item.subject.did

            if member_did not in members:
                members.append(member_did)

        cursor = getattr(data, "cursor", None)

        if not cursor:
            break

    return members


def get_list_posts(client, list_url):
    posts = []
    members = get_list_members(client, list_url)

    print(f"List members found: {len(members)}")

    for did in members:
        try:
            data = client.app.bsky.feed.get_author_feed({
                "actor": did,
                "limit": 30,
                "filter": "posts_with_replies",
            })

            for item in data.feed:
                if is_repost_item(item):
                    continue

                post = item.post

                # Lijsten nemen geen replies mee.
                if not is_valid_media_post(
                    post,
                    allow_replies=False,
                ):
                    continue

                posts.append(post)

        except Exception as error:
            print(f"Author scan error for {did}: {error}")

    unique_posts = {}

    for post in posts:
        unique_posts[post.uri] = post

    return sort_old_to_new(
        list(unique_posts.values())
    )


def get_excluded_dids(client, list_url):
    if not list_url.strip():
        return set()

    try:
        return set(
            get_list_members(client, list_url)
        )

    except Exception as error:
        print(f"Exclude list error: {error}")
        return set()


def get_hashtag_posts(client, tag):
    tag = tag.strip()

    if not tag:
        return []

    clean_tag = (
        tag.replace("#", "")
        .strip()
        .lower()
    )

    query = f"#{clean_tag}"

    try:
        data = client.app.bsky.feed.search_posts({
            "q": query,
            "limit": 100,
            "sort": "latest",
        })

    except Exception as error:
        print(f"Hashtag search error: {error}")
        return []

    posts = []

    for post in data.posts:
        text = (
            getattr(post.record, "text", "")
            or ""
        )

        if f"#{clean_tag}" not in text.lower():
            continue

        # Hashtags nemen geen replies mee.
        if not is_valid_media_post(
            post,
            allow_replies=False,
        ):
            continue

        posts.append(post)

    unique_posts = {}

    for post in posts:
        unique_posts[post.uri] = post

    return sort_old_to_new(
        list(unique_posts.values())
    )


def repost_own_latest_media(client):
    print("Scanning own latest media posts")

    try:
        my_did = client.me.did

        data = client.app.bsky.feed.get_author_feed({
            "actor": my_did,
            "limit": 100,
            "filter": "posts_with_replies",
        })

        own_media = []

        for item in data.feed:
            if is_repost_item(item):
                continue

            post = item.post

            if post.author.did != my_did:
                continue

            # Eigen posts: geen replies en geen quotes.
            if not is_valid_media_post(
                post,
                allow_replies=False,
            ):
                continue

            own_media.append(post)

            if len(own_media) >= OWN_REPOST_SLOTS:
                break

        own_media = sort_old_to_new(own_media)

        print(
            f"Own media posts found: "
            f"{len(own_media)}"
        )

        # Oudste eerst en nieuwste als laatste.
        # Daardoor eindigt de nieuwste eigen post bovenaan.
        for post in own_media:
            try:
                viewer = getattr(post, "viewer", None)

                old_repost = (
                    getattr(viewer, "repost", None)
                    if viewer
                    else None
                )

                if old_repost:
                    try:
                        client.delete_repost(old_repost)

                        print(
                            "Deleted old own repost: "
                            f"{post.uri}"
                        )

                        time.sleep(SLEEP_SECONDS)

                    except Exception as error:
                        print(
                            "Delete own repost "
                            f"skipped/error: {error}"
                        )

                client.repost(post.uri, post.cid)

                print(
                    "Own post reposted on top: "
                    f"{post.uri}"
                )

                time.sleep(SLEEP_SECONDS)

            except Exception as error:
                print(f"Own repost error: {error}")

    except Exception as error:
        print(f"Own media scan error: {error}")


def process_posts(
    client,
    posts,
    state,
    per_user,
    my_did,
    excluded_global,
    total,
    allow_replies=False,
    excluded_source=None,
):
    if excluded_source is None:
        excluded_source = set()

    for post in posts:
        if total >= OTHER_REPOST_LIMIT:
            break

        author_did = post.author.did

        if author_did == my_did:
            continue

        if author_did in excluded_global:
            continue

        if author_did in excluded_source:
            continue

        if not is_recent(post):
            continue

        success = repost_and_like(
            client=client,
            post=post,
            state=state,
            per_user=per_user,
            allow_replies=allow_replies,
        )

        if not success:
            continue

        total += 1
        save_state(state)

    return total


def main():
    print("=== EYESCANDY REPOSTER STARTED ===")

    if not USERNAME:
        raise ValueError(
            "BSKY_USERNAME is missing"
        )

    if not PASSWORD:
        raise ValueError(
            "BSKY_PASSWORD is missing"
        )

    client = Client()
    client.login(USERNAME, PASSWORD)

    my_did = client.me.did

    state = load_state()
    per_user = defaultdict(int)
    total = 0

    excluded_global = set()

    for exclude_url in GLOBAL_EXCLUDE_LISTS:
        if not exclude_url.strip():
            continue

        excluded_global.update(
            get_excluded_dids(
                client,
                exclude_url,
            )
        )

    print(
        f"Global excluded accounts: "
        f"{len(excluded_global)}"
    )
    print(
        f"Normal repost limit: "
        f"{OTHER_REPOST_LIMIT}"
    )
    print(
        f"Own repost slots last: "
        f"{OWN_REPOST_SLOTS}"
    )
    print("Post order: old -> new")

    PROCESS_ORDER = [
        ("hashtag", HASHTAGS[0]),
        ("hashtag", HASHTAGS[1]),
        ("hashtag", HASHTAGS[2]),

        ("feed", FEEDS[2]),
        ("list", LISTS[2]),

        ("feed", FEEDS[1]),
        ("list", LISTS[1]),

        ("feed", FEEDS[0]),
        ("list", LISTS[0]),
    ]

    for source_type, source in PROCESS_ORDER:
        if total >= OTHER_REPOST_LIMIT:
            break

        if source_type == "hashtag":
            tag = source.get("tag", "").strip()

            if not tag:
                continue

            print(f"Scanning hashtag: {tag}")

            source_excluded = get_excluded_dids(
                client,
                source.get("exclude_list", ""),
            )

            posts = get_hashtag_posts(
                client,
                tag,
            )

            total = process_posts(
                client=client,
                posts=posts,
                state=state,
                per_user=per_user,
                my_did=my_did,
                excluded_global=excluded_global,
                excluded_source=source_excluded,
                total=total,
                allow_replies=False,
            )

        elif source_type == "feed":
            url = source.get("url", "").strip()

            if not url:
                continue

            allow_replies = source.get(
                "allow_replies",
                False,
            )

            print(
                f"Scanning feed: "
                f"{source.get('name', '')}"
            )
            print(
                "Media replies enabled: "
                f"{allow_replies}"
            )

            posts = get_feed_posts(
                client=client,
                feed_url=url,
                allow_replies=allow_replies,
            )

            total = process_posts(
                client=client,
                posts=posts,
                state=state,
                per_user=per_user,
                my_did=my_did,
                excluded_global=excluded_global,
                total=total,
                allow_replies=allow_replies,
            )

        elif source_type == "list":
            url = source.get("url", "").strip()

            if not url:
                continue

            print(
                f"Scanning list: "
                f"{source.get('name', '')}"
            )

            posts = get_list_posts(
                client,
                url,
            )

            total = process_posts(
                client=client,
                posts=posts,
                state=state,
                per_user=per_user,
                my_did=my_did,
                excluded_global=excluded_global,
                total=total,
                allow_replies=False,
            )

    # Altijd als laatste en ongeacht de ouderdom.
    # De laatste drie eigen mediaposts worden
    # opnieuw bovenaan gezet.
    repost_own_latest_media(client)

    save_state(state)

    print(
        f"Done. Other reposts: {total}, "
        f"own repost slots: {OWN_REPOST_SLOTS}"
    )


if __name__ == "__main__":
    main()