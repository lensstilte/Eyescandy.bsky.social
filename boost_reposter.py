import os
import random
import time
from datetime import datetime, timezone, timedelta
from atproto import Client

# Target creator
TARGET_ACCOUNT = "big-dominio.bsky.social"

# Your own account, always boosted last
OWN_ACCOUNT = "eyescandy.bsky.social"

RANDOM_POSTS = 10
NEWEST_POSTS = 10
OWN_POSTS = 3
LOOKBACK_DAYS = 60
SLEEP_SECONDS = 2

USERNAME = os.getenv("BSKY_USERNAME")
PASSWORD = os.getenv("BSKY_PASSWORD")

client = Client()


def get_created_at(item):
    return datetime.fromisoformat(
        item.post.record.created_at.replace("Z", "+00:00")
    )


def has_media(item):
    embed = getattr(item.post.record, "embed", None)
    return embed is not None


def is_quote(item):
    embed = getattr(item.post.record, "embed", None)
    return embed and "record" in str(type(embed)).lower()


def is_repost_from_feed(item):
    # Blocks reposts shown in the author's feed
    return getattr(item, "reason", None) is not None


def get_media_posts(account, limit=100, days_back=None):
    feed = client.app.bsky.feed.get_author_feed({
        "actor": account,
        "limit": limit
    })

    posts = []
    cutoff = None

    if days_back:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    for item in feed.feed:
        # Only real content from this account, no reposts
        if is_repost_from_feed(item):
            continue

        # Media required
        if not has_media(item):
            continue

        # No quote posts
        if is_quote(item):
            continue

        created = get_created_at(item)

        if cutoff and created < cutoff:
            continue

        posts.append(item)

    # Newest first
    posts.sort(key=get_created_at, reverse=True)
    return posts


def refresh_repost(item):
    viewer = item.post.viewer
    repost_uri = getattr(viewer, "repost", None)

    if repost_uri:
        print("Unrepost:", item.post.uri)
        client.delete_repost(repost_uri)
        time.sleep(SLEEP_SECONDS)

    print("Repost:", item.post.uri)
    client.repost(item.post.uri, item.post.cid)
    time.sleep(SLEEP_SECONDS)


def main():
    if not USERNAME or not PASSWORD:
        raise Exception("Missing BSKY_USERNAME or BSKY_PASSWORD")

    client.login(USERNAME, PASSWORD)

    target_posts = get_media_posts(
        TARGET_ACCOUNT,
        limit=100,
        days_back=LOOKBACK_DAYS
    )

    newest_posts = target_posts[:NEWEST_POSTS]

    random_pool = target_posts[NEWEST_POSTS:]
    random_posts = random.sample(
        random_pool,
        min(RANDOM_POSTS, len(random_pool))
    )

    own_posts = get_media_posts(
        OWN_ACCOUNT,
        limit=30,
        days_back=None
    )[:OWN_POSTS]

    print(f"Random old target posts: {len(random_posts)}")
    print(f"Newest target posts: {len(newest_posts)}")
    print(f"Own Eyescandy posts: {len(own_posts)}")

    # Belangrijk:
    # Laatste repost komt bovenaan.
    # Daarom Eyescandy als laatste groep.
    # En binnen Eyescandy: oudste eerst, nieuwste als allerlaatste.
    final_posts = (
        random_posts
        + list(reversed(newest_posts))
        + list(reversed(own_posts))
    )

    print(f"Total repost actions: {len(final_posts)}")

    for item in final_posts:
        refresh_repost(item)


if __name__ == "__main__":
    main()