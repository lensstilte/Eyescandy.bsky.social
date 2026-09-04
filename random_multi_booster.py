import os
import random
import time
from datetime import datetime, timezone, timedelta

from atproto import Client


# ============================================================
# ACCOUNTS
# ============================================================

OWN_ACCOUNT = "eyescandy.bsky.social"

# Maximaal 5 targetaccounts.
# Laat een regel leeg om die positie over te slaan.
TARGET_ACCOUNTS = [
    "womenworld.bsky.social",
    "big-dominio.bsky.social",
    "melli848.bsky.social",
    "@mg4mg.bsky.social",
    "",
]


# ============================================================
# INSTELLINGEN PER TARGETACCOUNT
# ============================================================

# Voorbeeld:
# 1 nieuwste post + 2 willekeurige oude posts = 3 reposts per target
NEWEST_POSTS_PER_TARGET = 3
RANDOM_OLD_POSTS_PER_TARGET = 0

# Aantal eigen posts dat als laatste wordt vernieuwd
OWN_POSTS = 1

# Hoe ver terugkijken bij de targetaccounts
LOOKBACK_DAYS = 3650

# Hoeveel posts maximaal verzamelen per targetaccount
TARGET_SCAN_LIMIT = 500

# Maximaal aantal feedpagina's doorzoeken
TARGET_MAX_PAGES = 100
OWN_MAX_PAGES = 20

# Pauze tussen Bluesky-acties
SLEEP_SECONDS = 2


# ============================================================
# GITHUB SECRETS / OMGEVINGSVARIABELEN
# ============================================================

USERNAME = os.getenv("BSKY_USERNAME")
PASSWORD = os.getenv("BSKY_PASSWORD")

client = Client()


# ============================================================
# HULPFUNCTIES
# ============================================================

def get_created_at(item):
    """Geeft de aanmaakdatum van een Bluesky-post terug."""
    created_at = item.post.record.created_at

    return datetime.fromisoformat(
        created_at.replace("Z", "+00:00")
    )


def has_media(item):
    """Controleert of de post media bevat."""
    return getattr(item.post.record, "embed", None) is not None


def is_quote(item):
    """Controleert of de post een quote-post is."""
    embed = getattr(item.post.record, "embed", None)

    if not embed:
        return False

    embed_type = str(type(embed)).lower()

    return "record" in embed_type


def is_reply(item):
    """Controleert of de post een reply is."""
    return getattr(item.post.record, "reply", None) is not None


def is_repost_from_feed(item):
    """Controleert of het feeditem een repost van iemand anders is."""
    return getattr(item, "reason", None) is not None


def get_media_posts(
    account,
    wanted=100,
    days_back=None,
    max_pages=10
):
    """
    Haalt originele mediaposts van een account op.

    Worden overgeslagen:
    - reposts
    - replies
    - quote-posts
    - posts zonder media
    """

    posts = []
    cursor = None
    cutoff = None

    if days_back is not None:
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(days=days_back)
        )

    for page_number in range(1, max_pages + 1):
        params = {
            "actor": account,
            "limit": 100,
        }

        if cursor:
            params["cursor"] = cursor

        try:
            feed = client.app.bsky.feed.get_author_feed(params)
        except Exception as error:
            print(f"Feed ophalen mislukt voor {account}: {error}")
            break

        print(
            f"Scan {account}: pagina {page_number}, "
            f"gevonden mediaposts: {len(posts)}"
        )

        stop_scanning = False

        for item in feed.feed:
            if is_repost_from_feed(item):
                continue

            if is_reply(item):
                continue

            if not has_media(item):
                continue

            if is_quote(item):
                continue

            try:
                created_at = get_created_at(item)
            except Exception as error:
                print(
                    f"Datum kon niet worden gelezen "
                    f"voor {item.post.uri}: {error}"
                )
                continue

            # Feed staat normaal van nieuw naar oud.
            # Zodra de cutoff is bereikt, kunnen we stoppen.
            if cutoff and created_at < cutoff:
                stop_scanning = True
                break

            posts.append(item)

            if len(posts) >= wanted:
                stop_scanning = True
                break

        if stop_scanning:
            break

        cursor = getattr(feed, "cursor", None)

        if not cursor:
            break

    # Nieuwste eerst
    posts.sort(
        key=get_created_at,
        reverse=True
    )

    return posts


def unique_posts(items):
    """Verwijdert eventuele dubbele posts op basis van de URI."""
    result = []
    seen_uris = set()

    for item in items:
        uri = item.post.uri

        if uri in seen_uris:
            continue

        seen_uris.add(uri)
        result.append(item)

    return result


def select_target_posts(posts):
    """
    Selecteert nieuwste en willekeurige oudere posts.

    Voorbeeld:
    NEWEST_POSTS_PER_TARGET = 1
    RANDOM_OLD_POSTS_PER_TARGET = 2

    Resultaat:
    - 1 nieuwste post
    - 2 willekeurige posts uit de resterende oudere posts
    """

    if not posts:
        return [], []

    newest_posts = posts[:NEWEST_POSTS_PER_TARGET]

    # Nieuwste geselecteerde posts worden uit de random pool gehouden
    random_pool = posts[NEWEST_POSTS_PER_TARGET:]

    random_count = min(
        RANDOM_OLD_POSTS_PER_TARGET,
        len(random_pool)
    )

    if random_count > 0:
        random_old_posts = random.sample(
            random_pool,
            random_count
        )
    else:
        random_old_posts = []

    return newest_posts, random_old_posts


def refresh_repost(item):
    """
    Liket een post indien nodig en vernieuwt de repost.

    Als de post al gerepost is:
    - unrepost
    - opnieuw repost

    Als de post nog niet gerepost is:
    - direct repost
    """

    uri = item.post.uri
    cid = item.post.cid
    viewer = item.post.viewer

    like_uri = getattr(viewer, "like", None)

    if not like_uri:
        try:
            print(f"Like: {uri}")
            client.like(uri, cid)
            time.sleep(1)
        except Exception as error:
            print(f"Like mislukt voor {uri}: {error}")
    else:
        print(f"Al geliket: {uri}")

    repost_uri = getattr(viewer, "repost", None)

    if repost_uri:
        try:
            print(f"Unrepost: {uri}")
            client.delete_repost(repost_uri)
            time.sleep(SLEEP_SECONDS)
        except Exception as error:
            print(f"Unrepost mislukt voor {uri}: {error}")
            return

    try:
        print(f"Repost: {uri}")
        client.repost(uri, cid)
        time.sleep(SLEEP_SECONDS)
    except Exception as error:
        print(f"Repost mislukt voor {uri}: {error}")


# ============================================================
# MAIN
# ============================================================

def main():
    if not USERNAME or not PASSWORD:
        raise RuntimeError(
            "BSKY_USERNAME of BSKY_PASSWORD ontbreekt."
        )

    if NEWEST_POSTS_PER_TARGET < 0:
        raise ValueError(
            "NEWEST_POSTS_PER_TARGET mag niet negatief zijn."
        )

    if RANDOM_OLD_POSTS_PER_TARGET < 0:
        raise ValueError(
            "RANDOM_OLD_POSTS_PER_TARGET mag niet negatief zijn."
        )

    print("Inloggen bij Bluesky...")
    client.login(USERNAME, PASSWORD)
    print(f"Ingelogd als: {USERNAME}")

    active_targets = [
        account.strip()
        for account in TARGET_ACCOUNTS
        if account and account.strip()
    ]

    print(f"Actieve targetaccounts: {len(active_targets)}")

    final_target_posts = []

    for target_account in active_targets:
        print("")
        print("=" * 60)
        print(f"Targetaccount: {target_account}")
        print("=" * 60)

        target_posts = get_media_posts(
            account=target_account,
            wanted=TARGET_SCAN_LIMIT,
            days_back=LOOKBACK_DAYS,
            max_pages=TARGET_MAX_PAGES,
        )

        newest_posts, random_old_posts = select_target_posts(
            target_posts
        )

        print(
            f"{target_account} – totaal gevonden: "
            f"{len(target_posts)}"
        )
        print(
            f"{target_account} – nieuwste gekozen: "
            f"{len(newest_posts)}"
        )
        print(
            f"{target_account} – oude random gekozen: "
            f"{len(random_old_posts)}"
        )

        # Willekeurige oude posts eerst.
        # Binnen die selectie: oudste eerst.
        random_old_posts.sort(
            key=get_created_at
        )

        # Nieuwste selectie ook oud naar nieuw uitvoeren.
        newest_posts_old_to_new = sorted(
            newest_posts,
            key=get_created_at
        )

        selected_posts = (
            random_old_posts
            + newest_posts_old_to_new
        )

        final_target_posts.extend(selected_posts)

    print("")
    print("=" * 60)
    print(f"Eigen posts ophalen: {OWN_ACCOUNT}")
    print("=" * 60)

    own_posts = get_media_posts(
        account=OWN_ACCOUNT,
        wanted=OWN_POSTS,
        days_back=None,
        max_pages=OWN_MAX_PAGES,
    )[:OWN_POSTS]

    # Oudste eerst, zodat de nieuwste eigen post uiteindelijk bovenaan staat
    own_posts_old_to_new = sorted(
        own_posts,
        key=get_created_at
    )

    print(f"Eigen mediaposts gekozen: {len(own_posts_old_to_new)}")

    # Targetposts eerst, eigen account als laatste
    final_posts = (
        final_target_posts
        + own_posts_old_to_new
    )

    final_posts = unique_posts(final_posts)

    print("")
    print("=" * 60)
    print("SAMENVATTING")
    print("=" * 60)
    print(f"Actieve targets: {len(active_targets)}")
    print(f"Target-reposts: {len(final_target_posts)}")
    print(f"Eigen reposts: {len(own_posts_old_to_new)}")
    print(f"Totaal unieke repostacties: {len(final_posts)}")

    if not final_posts:
        print("Geen geschikte posts gevonden.")
        return

    print("")
    print("Repostproces starten...")

    for index, item in enumerate(final_posts, start=1):
        print("")
        print(
            f"Actie {index}/{len(final_posts)} – "
            f"{item.post.author.handle}"
        )

        refresh_repost(item)

    print("")
    print("Repostproces voltooid.")


if __name__ == "__main__":
    main()