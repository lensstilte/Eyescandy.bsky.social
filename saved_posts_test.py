# saved_posts_test.py
#
# Centrale Saved Posts booster voor Bluesky
# - Bron: Eyescandy Saved Posts (instelbaar)
# - Doel: het account waarmee de workflow inlogt
# - Maximaal 10 opgeslagen posts per uitvoering (media of tekst)
# - Unrepost -> repost
# - Like alleen als de post nog niet geliket is
# - Geen handmatige postlinks nodig

import os
import time
from atproto import Client


SOURCE_ACCOUNT = os.getenv("SAVED_POSTS_USERNAME", "eyescandy.bsky.social").strip()
SOURCE_PASSWORD = os.getenv("SAVED_POSTS_PASSWORD")
TARGET_ACCOUNT = os.getenv("BSKY_USERNAME")
TARGET_PASSWORD = os.getenv("BSKY_PASSWORD")

try:
    requested_limit = int(os.getenv("MAX_SAVED_POSTS", "10"))
except (TypeError, ValueError):
    requested_limit = 10

MAX_SAVED_POSTS = max(1, min(requested_limit, 10))
SLEEP_SECONDS = 2


def get_attr(obj, *names):
    """Read a field from either a dict or an SDK model."""
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return None


def to_dict(obj):
    if isinstance(obj, dict):
        return obj
    if obj is None:
        return {}
    for method_name in ("model_dump", "dict"):
        method = getattr(obj, method_name, None)
        if callable(method):
            for kwargs in ({"by_alias": True, "mode": "json"}, {"by_alias": True}, {}):
                try:
                    result = method(**kwargs)
                    if isinstance(result, dict):
                        return result
                except Exception:
                    continue
    return {}


def type_markers(obj):
    """Return type markers from both JSON data and SDK class names."""
    data = to_dict(obj)
    markers = [
        str(data.get("$type", "")),
        str(data.get("py_type", "")),
        type(obj).__name__ if obj is not None else "",
    ]
    for attr in ("py_type", "type", "lexicon_type"):
        value = getattr(obj, attr, None) if obj is not None else None
        if value is not None:
            markers.append(str(value))
    return " ".join(markers).lower()


def get_saved_posts(client):
    """Read saved posts regardless of whether they contain media or text."""
    selected = []
    seen = set()
    cursor = None
    total_bookmarks = 0

    while len(selected) < MAX_SAVED_POSTS:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor

        response = client.app.bsky.bookmark.get_bookmarks(params=params)
        bookmarks = get_attr(response, "bookmarks") or []
        total_bookmarks += len(bookmarks)
        print(f"Saved Posts-pagina: {len(bookmarks)} bookmark(s)")

        if not bookmarks:
            response_data = to_dict(response)
            print(
                "Diagnose lege pagina: "
                f"responsvelden={list(response_data.keys()) or 'niet beschikbaar'}"
            )

        for bookmark in bookmarks:
            item = get_attr(bookmark, "item")
            if item is None:
                print("Bookmark overgeslagen: geen item in bookmark-respons.")
                continue

            item_type = type_markers(item)
            if "notfoundpost" in item_type or "blockedpost" in item_type:
                print("Bookmark overgeslagen: post niet beschikbaar of geblokkeerd.")
                continue

            post = item
            for nested_name in ("post", "post_view", "postView"):
                nested = get_attr(item, nested_name)
                if nested is not None:
                    post = nested
                    break

            uri = get_attr(post, "uri")
            cid = get_attr(post, "cid")
            if not uri or not cid or uri in seen:
                continue

            author = get_attr(post, "author")
            handle = get_attr(author, "handle") or "onbekend"

            selected.append({"uri": uri, "cid": cid, "author": handle})
            seen.add(uri)
            print(f"Saved Post gevonden: @{handle} | {uri}")

            if len(selected) >= MAX_SAVED_POSTS:
                break

        cursor = get_attr(response, "cursor")
        if not cursor or not bookmarks:
            break

    print(f"Totaal bookmarks gelezen: {total_bookmarks}")
    print(f"Opgeslagen posts geselecteerd: {len(selected)}")
    return selected


def get_records(client, collection):
    records = []
    cursor = None
    while True:
        params = {"repo": client.me.did, "collection": collection, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = client.com.atproto.repo.list_records(params=params)
        page = get_attr(response, "records") or []
        records.extend(page)
        cursor = get_attr(response, "cursor")
        if not cursor or not page:
            break
    return records


def get_subject_uri(record):
    value = get_attr(record, "value")
    subject = get_attr(value, "subject")
    return get_attr(subject, "uri")


def post_url(post):
    rkey = post["uri"].rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{post['author']}/post/{rkey}"


def boost_post(client, post, reposts_by_subject, liked_uris):
    uri, cid = post["uri"], post["cid"]
    success = True

    print(f"\n@{post['author']}")
    print(post_url(post))

    existing_reposts = reposts_by_subject.get(uri, [])
    for record in existing_reposts:
        try:
            client.delete_repost(record.uri)
            print("Oude repost verwijderd.")
            time.sleep(1)
        except Exception as exc:
            success = False
            print(f"Repost verwijderen mislukt: {exc}")

    try:
        client.repost(uri, cid)
        print("Opnieuw gerepost.")
        time.sleep(SLEEP_SECONDS)
    except Exception as exc:
        success = False
        print(f"Repost mislukt: {exc}")

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
        raise RuntimeError("SAVED_POSTS_USERNAME of SAVED_POSTS_PASSWORD ontbreekt.")
    if not TARGET_ACCOUNT or not TARGET_PASSWORD:
        raise RuntimeError("BSKY_USERNAME of BSKY_PASSWORD ontbreekt.")

    print("=" * 55)
    print("SAVED POSTS BOOSTER")
    print(f"Bron: {SOURCE_ACCOUNT}")
    print(f"Doel: {TARGET_ACCOUNT}")
    print(f"Maximum: {MAX_SAVED_POSTS}")
    print("=" * 55)

    source = Client()
    source.login(SOURCE_ACCOUNT, SOURCE_PASSWORD)
    print("Bronaccount ingelogd.")

    target = Client()
    target.login(TARGET_ACCOUNT, TARGET_PASSWORD)
    print("Doelaccount ingelogd.")

    print("\nAlle Saved Posts ophalen (mediafilter uit)...")
    posts = get_saved_posts(source)
    print(f"Opgeslagen posts geselecteerd: {len(posts)}")

    if not posts:
        print("Geen Saved Posts ontvangen van de API. Controleer of het bronaccount Saved Posts heeft en bekijk de diagnose hierboven.")
        return

    print("\nBestaande reposts en likes controleren...")
    repost_records = get_records(target, "app.bsky.feed.repost")
    like_records = get_records(target, "app.bsky.feed.like")

    reposts_by_subject = {}
    for record in repost_records:
        uri = get_subject_uri(record)
        if uri:
            reposts_by_subject.setdefault(uri, []).append(record)

    liked_uris = {
        uri for uri in (get_subject_uri(record) for record in like_records) if uri
    }

    successful = failed = 0
    for index, post in enumerate(posts, start=1):
        print(f"\n[{index}/{len(posts)}]")
        if boost_post(target, post, reposts_by_subject, liked_uris):
            successful += 1
        else:
            failed += 1

    print("\n" + "=" * 55)
    print("BOOSTER KLAAR")
    print(f"Bronaccount: {SOURCE_ACCOUNT}")
    print(f"Doelaccount: {TARGET_ACCOUNT}")
    print(f"Opgeslagen posts geselecteerd: {len(posts)}")
    print(f"Volledig gelukt: {successful}")
    print(f"Met fouten: {failed}")
    print("=" * 55)


if __name__ == "__main__":
    main()
