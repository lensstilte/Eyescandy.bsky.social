
# saved_posts_test.py
#
# Centrale Saved Posts booster voor Bluesky
# - Bron: Eyescandy Saved Posts (instelbaar)
# - Doel: het account waarmee de workflow inlogt
# - Maximaal 10 media-posts per uitvoering
# - Unrepost -> repost
# - Like alleen als de post nog niet geliket is
# - Geen handmatige postlinks nodig

import os
import time
from atproto import Client


SOURCE_ACCOUNT = os.getenv(
    "SAVED_POSTS_USERNAME",
    "eyescandy.bsky.social"
).strip()
SOURCE_PASSWORD = os.getenv("SAVED_POSTS_PASSWORD")

TARGET_ACCOUNT = os.getenv("BSKY_USERNAME")
TARGET_PASSWORD = os.getenv("BSKY_PASSWORD")

# Veiligheidslimiet: nooit meer dan 10 posts per uitvoering.
try:
    requested_limit = int(os.getenv("MAX_SAVED_POSTS", "10"))
except ValueError:
    requested_limit = 10

MAX_SAVED_POSTS = max(1, min(requested_limit, 10))
SLEEP_SECONDS = 2


def to_dict(obj):
    """Zet een SDK-object zo mogelijk om naar een dictionary."""
    if isinstance(obj, dict):
        return obj

    if obj is None:
        return {}

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(by_alias=True, mode="json")
        except Exception:
            try:
                return obj.model_dump(by_alias=True)
            except Exception:
                pass

    if hasattr(obj, "dict"):
        try:
            return obj.dict(by_alias=True)
        except Exception:
            pass

    return {}


def has_media(post):
    """
    Accepteer afbeeldingen, video's en galleries.
    Bij recordWithMedia wordt alleen de media gecontroleerd,
    niet de quote-post zelf.
    """

    post_data = to_dict(post)
    embed = post_data.get("embed")

    if not embed:
        embed = getattr(post, "embed", None)

    embed_data = to_dict(embed)
    embed_type = str(
        embed_data.get("$type", "")
        or getattr(embed, "py_type", "")
        or ""
    )

    # Directe media-embeds.
    if any(media_type in embed_type for media_type in (
        "app.bsky.embed.images#view",
        "app.bsky.embed.video#view",
        "app.bsky.embed.gallery#view",
    )):
        return True

    # Quote-post met media: controleer uitsluitend de media-embed.
    if "app.bsky.embed.recordWithMedia#view" in embed_type:
        media = embed_data.get("media")
        media_data = to_dict(media)
        media_type = str(media_data.get("$type", ""))

        return any(media_kind in media_type for media_kind in (
            "app.bsky.embed.images#view",
            "app.bsky.embed.video#view",
            "app.bsky.embed.gallery#view",
        ))

    # Fallback voor SDK-versies met een andere objectrepresentatie.
    if not embed_data and embed is not None:
        for attr in ("images", "video", "media"):
            if getattr(embed, attr, None):
                return True

    return False


def get_saved_media_posts(client):
    """Lees Saved Posts en selecteer maximaal 10 media-posts."""

    selected = []
    seen = set()
    cursor = None

    while len(selected) < MAX_SAVED_POSTS:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        response = client.app.bsky.bookmark.get_bookmarks(
            params=params
        )

        bookmarks = response.bookmarks or []

        for bookmark in bookmarks:
            # De bookmark bevat de werkelijke post onder .item.
            post = getattr(bookmark, "item", None)

            if post is None:
                continue

            uri = getattr(post, "uri", None)
            cid = getattr(post, "cid", None)

            if not uri or not cid or uri in seen:
                continue

            # Voorkom dat geblokkeerde of verwijderde posts worden gebruikt.
            if getattr(post, "not_found", False):
                continue

            if not has_media(post):
                print(f"Overgeslagen (geen media): {uri}")
                continue

            author = getattr(post, "author", None)
            handle = getattr(author, "handle", None) or "onbekend"

            selected.append({
                "uri": uri,
                "cid": cid,
                "author": handle,
            })
            seen.add(uri)

            if len(selected) >= MAX_SAVED_POSTS:
                break

        cursor = getattr(response, "cursor", None)

        if not cursor or not bookmarks:
            break

    return selected


def get_records(client, collection):
    """Lees interactierecords van het doelaccount met paginering."""

    records = []
    cursor = None

    while True:
        params = {
            "repo": client.me.did,
            "collection": collection,
            "limit": 100,
        }

        if cursor:
            params["cursor"] = cursor

        response = client.com.atproto.repo.list_records(
            params=params
        )

        page = response.records or []
        records.extend(page)

        cursor = getattr(response, "cursor", None)

        if not cursor or not page:
            break

    return records


def get_subject_uri(record):
    value = getattr(record, "value", None)
    subject = getattr(value, "subject", None)
    return getattr(subject, "uri", None)


def post_url(post):
    rkey = post["uri"].rsplit("/", 1)[-1]
    return (
        f"https://bsky.app/profile/"
        f"{post['author']}/post/{rkey}"
    )


def boost_post(client, post, reposts_by_subject, liked_uris):
    uri = post["uri"]
    cid = post["cid"]
    success = True

    print(f"\n@{post['author']}")
    print(post_url(post))

    # Verwijder eventuele bestaande repost-records.
    existing_reposts = reposts_by_subject.get(uri, [])

    for record in existing_reposts:
        try:
            client.delete_repost(record.uri)
            print("Oude repost verwijderd.")
            time.sleep(1)
        except Exception as exc:
            success = False
            print(f"Repost verwijderen mislukt: {exc}")

    # Repost opnieuw, ook als verwijderen niet lukte.
    try:
        client.repost(uri, cid)
        print("Opnieuw gerepost.")
        time.sleep(SLEEP_SECONDS)
    except Exception as exc:
        success = False
        print(f"Repost mislukt: {exc}")

    # Like alleen als dit account nog geen like-record heeft.
    if uri in liked_uris:
        print("Like bestond al; geen nieuwe like nodig.")
    else:
        try:
            client.like(uri, cid)
            liked_uris.add(uri)
            print("Post geliket.")
            time.sleep(SLEEP_SECONDS)
        except Exception as exc:
            success = False
            print(f"Like mislukt: {exc}")

    return success


def main():
    if not SOURCE_ACCOUNT or not SOURCE_PASSWORD:
        raise RuntimeError(
            "SAVED_POSTS_USERNAME of SAVED_POSTS_PASSWORD ontbreekt."
        )

    if not TARGET_ACCOUNT or not TARGET_PASSWORD:
        raise RuntimeError(
            "BSKY_USERNAME of BSKY_PASSWORD ontbreekt."
        )

    print("=" * 55)
    print("SAVED POSTS MEDIA BOOSTER")
    print(f"Bron: {SOURCE_ACCOUNT}")
    print(f"Doel: {TARGET_ACCOUNT}")
    print(f"Maximum: {MAX_SAVED_POSTS}")
    print("=" * 55)

    source = Client()
    source.login(SOURCE_ACCOUNT, SOURCE_PASSWORD)

    target = Client()
    target.login(TARGET_ACCOUNT, TARGET_PASSWORD)

    print("\nSaved Posts met media ophalen...")
    posts = get_saved_media_posts(source)

    print(f"Geschikte media-posts: {len(posts)}")

    if not posts:
        print("Geen geschikte Saved Posts gevonden.")
        return

    print("\nBestaande reposts en likes controleren...")
    repost_records = get_records(
        target, "app.bsky.feed.repost"
    )
    like_records = get_records(
        target, "app.bsky.feed.like"
    )

    reposts_by_subject = {}

    for record in repost_records:
        uri = get_subject_uri(record)
        if uri:
            reposts_by_subject.setdefault(uri, []).append(record)

    liked_uris = {
        get_subject_uri(record)
        for record in like_records
        if get_subject_uri(record)
    }

    successful = 0
    failed = 0

    for index, post in enumerate(posts, start=1):
        print(f"\n[{index}/{len(posts)}]")

        if boost_post(
            target, post, reposts_by_subject, liked_uris
        ):
            successful += 1
        else:
            failed += 1

    print("\n" + "=" * 55)
    print("BOOSTER KLAAR")
    print(f"Bronaccount: {SOURCE_ACCOUNT}")
    print(f"Doelaccount: {TARGET_ACCOUNT}")
    print(f"Media-posts geselecteerd: {len(posts)}")
    print(f"Volledig gelukt: {successful}")
    print(f"Met fouten: {failed}")
    print("=" * 55)


if __name__ == "__main__":
    main()
