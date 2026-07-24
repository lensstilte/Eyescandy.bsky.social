# 5post_booster.py

import os
import re
import time
from atproto import Client

BOOST_POSTS = [
    "https://bsky.app/profile/erosensual.bsky.social/post/3mr4vfs6rfk2h",
    "https://bsky.app/profile/lekkerekontjes69.bsky.social/post/3mrdgavecg72r",
    "https://bsky.app/profile/big-dominio.bsky.social/post/3mh6sgyagq222",
    "https://bsky.app/profile/carmenle91.bsky.social/post/3m5dvmkcjzs2x",
    "",




]


def parse_bsky_url(url):
    match = re.search(r"bsky\.app/profile/([^/]+)/post/([^/?#]+)", url)
    if not match:
        raise ValueError(f"Ongeldige Bluesky URL: {url}")

    return match.group(1), match.group(2)


def main():
    username = os.getenv("BSKY_USERNAME")
    password = os.getenv("BSKY_PASSWORD")

    if not username or not password:
        raise RuntimeError("BSKY_USERNAME of BSKY_PASSWORD ontbreekt.")

    client = Client()
    client.login(username, password)

    print(f"Ingelogd als: {username}")

    active_posts = [url.strip() for url in BOOST_POSTS if url.strip()]

    if not active_posts:
        print("Geen boost posts ingevuld. Script stopt.")
        return

    for url in active_posts:
        try:
            handle, post_id = parse_bsky_url(url)

            profile = client.get_profile(handle)
            did = profile.did

            post_uri = f"at://{did}/app.bsky.feed.post/{post_id}"

            thread = client.get_post_thread(post_uri)
            post = thread.thread.post

            post_uri = post.uri
            post_cid = post.cid

            print(f"Boost post: {url}")

            try:
                client.delete_repost(post_uri)
                print("Oude repost verwijderd.")
                time.sleep(1)
            except Exception:
                print("Geen oude repost gevonden.")

            client.repost(post_uri, post_cid)
            print("Opnieuw gerepost.")

            time.sleep(2)

        except Exception as e:
            print(f"Fout bij {url}: {e}")

    print("5post booster klaar.")


if __name__ == "__main__":
    main()