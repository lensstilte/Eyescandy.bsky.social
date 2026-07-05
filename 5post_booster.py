# 5post_booster.py

import os
import re
import time
from atproto import Client

BOOST_POSTS = [
    "https://bsky.app/profile/big-dominio.bsky.social/post/3mpuy2hlylc2a",
    "",
    "",
    "",
    "",
]


def parse_bsky_url(url):
    match = re.search(r"bsky\.app/profile/([^/]+)/post/([^/?#]+)", url)

    if not match:
        raise ValueError(f"Ongeldige Bluesky URL: {url}")

    handle = match.group(1)
    post_id = match.group(2)

    return handle, post_id


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

            print(f"Boost post: {url}")

            try:
                client.delete_repost(post_uri)
                print("Oude repost verwijderd.")
                time.sleep(1)
            except Exception:
                print("Geen oude repost gevonden.")

            client.repost(post_uri)
            print("Opnieuw gerepost.")

            time.sleep(2)

        except Exception as e:
            print(f"Fout bij {url}: {e}")

    print("5post booster klaar.")


if __name__ == "__main__":
    main()