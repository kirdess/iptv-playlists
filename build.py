#!/usr/bin/env python3
"""Build curated M3U playlists from the iptv-org API.

Outputs (in ./out):
  <lang>/all.m3u               every channel in that language, grouped by category
  <lang>/<category>.m3u        one file per category
  sports/<lang>.m3u            sports channels for each sports language
  sports/combat.m3u            boxing / MMA / UFC / wrestling / kickboxing, any language
  custom/<name>.m3u            hand-picked lists from custom/*.txt (one channel name or id per line)
  index.md                     list of every playlist with its channel count
"""

import json
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

API = "https://iptv-org.github.io/api"
OUT = Path(__file__).parent / "out"
CUSTOM = Path(__file__).parent / "custom"

LANGUAGES = {"fra": "Français"}                         # full category split
SPORTS_LANGUAGES = {"fra": "Français", "eng": "English"}  # extra sports lists
# strong names match anywhere; weak words (fight, combat) only count for sports channels
COMBAT_STRONG = re.compile(
    r"\b(boxe|boxing|ufc|mma|wrestl\w*|kick ?boxing|bellator|pfl|glory kickboxing|"
    r"one championship|bkfc|bare knuckle|wwe|aew|tna)\b", re.I)
COMBAT_WEAK = re.compile(r"\b(fight\w*|combat|catch)\b", re.I)
CATEGORY_FR = {
    "animation": "Animation", "auto": "Auto", "business": "Économie", "classic": "Classiques",
    "comedy": "Comédie", "cooking": "Cuisine", "culture": "Culture", "documentary": "Documentaires",
    "education": "Éducation", "entertainment": "Divertissement", "family": "Famille",
    "general": "Généraliste", "interactive": "Interactif", "kids": "Jeunesse",
    "legislative": "Parlementaire", "lifestyle": "Lifestyle", "movies": "Films", "music": "Musique",
    "news": "Infos", "outdoor": "Nature & Plein air", "public": "Service public", "relax": "Détente",
    "religious": "Religion", "science": "Sciences", "series": "Séries", "shop": "Téléachat",
    "sports": "Sports", "travel": "Voyage", "weather": "Météo", "undefined": "Autres",
}
QUALITY_RANK = {"2160p": 6, "1080p": 5, "1080i": 5, "720p": 4, "576p": 3, "576i": 3, "480p": 2, "360p": 1}


def fetch(name):
    req = urllib.request.Request(f"{API}/{name}.json", headers={"User-Agent": "iptv-playlists-builder"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def load():
    print("Downloading iptv-org data…", file=sys.stderr)
    channels = {c["id"]: c for c in fetch("channels")}
    feeds = {(f["channel"], f["id"]): f for f in fetch("feeds")}
    main_feed = {f["channel"]: f for f in feeds.values() if f.get("is_main")}
    logos = {}
    for lg in fetch("logos"):
        key = (lg["channel"], lg.get("feed"))
        if key not in logos or (lg.get("width") or 0) > (logos[key].get("width") or 0):
            logos[key] = lg
    return channels, feeds, main_feed, logos, fetch("streams")


def build_entries():
    channels, feeds, main_feed, logos, streams = load()
    best = {}  # (channel, feed) -> entry, keep highest quality stream
    for s in streams:
        ch = channels.get(s.get("channel"))
        if not ch or ch.get("is_nsfw") or ch.get("closed") or ch.get("replaced_by"):
            continue
        feed = feeds.get((ch["id"], s.get("feed"))) if s.get("feed") else main_feed.get(ch["id"])
        langs = (feed or {}).get("languages") or []
        logo = logos.get((ch["id"], (feed or {}).get("id"))) or logos.get((ch["id"], None))
        name = ch["name"]
        if feed and not feed.get("is_main") and feed.get("name"):
            name += f" ({feed['name']})"
        if s.get("quality"):
            name += f" [{s['quality']}]"
        labels = s.get("labels") or []
        if labels:
            name += " {" + ", ".join(labels) + "}"
        entry = {
            "key": f"{ch['id']}@{(feed or {}).get('id', '')}",
            "id": ch["id"], "name": name, "plain": ch["name"],
            "alt": ch.get("alt_names") or [], "country": ch.get("country", ""),
            "categories": ch.get("categories") or ["undefined"], "languages": langs,
            "logo": (logo or {}).get("url", ""), "url": s["url"],
            "referrer": s.get("referrer"), "user_agent": s.get("user_agent"),
            "rank": QUALITY_RANK.get(s.get("quality") or "", 0) - (5 if labels else 0),
        }
        k = entry["key"]
        if k not in best or entry["rank"] > best[k]["rank"]:
            best[k] = entry
    return sorted(best.values(), key=lambda e: e["name"].lower())


POSTERS = OUT / "posters"
POSTER_BASE = "https://raw.githubusercontent.com/kirdess/iptv-playlists/main/out/posters"
POSTER_SIZE = (300, 450)          # Stremio poster ratio 2:3
POSTER_BG = (236, 239, 243)       # light card for dark or colourful logos
POSTER_BG_DARK = (34, 36, 40)    # dark card for white or very light logos
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def _font(size):
    from PIL import ImageFont
    for p in FONT_PATHS:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _poster_from_logo(data):
    import io
    from PIL import Image
    logo = Image.open(io.BytesIO(data))
    logo.load()
    logo = logo.convert("RGBA")
    bbox = logo.getchannel("A").getbbox()  # trim transparent margins
    if bbox:
        logo = logo.crop(bbox)
    W, H = POSTER_SIZE
    logo.thumbnail((int(W * 0.84), int(H * 0.5)), Image.LANCZOS)
    # pick the card colour that contrasts with the logo's visible pixels
    px = [p for p in logo.resize((48, 48)).getdata() if p[3] > 128]
    lum = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b, _ in px) / len(px) if px else 0
    card = Image.new("RGB", POSTER_SIZE, POSTER_BG_DARK if lum > 170 else POSTER_BG)
    card.paste(logo, ((W - logo.width) // 2, (H - logo.height) // 2), logo)
    return card


def _poster_from_name(name):
    from PIL import Image, ImageDraw
    import textwrap
    W, H = POSTER_SIZE
    card = Image.new("RGB", POSTER_SIZE, (43, 43, 43))
    draw = ImageDraw.Draw(card)
    font = _font(30)
    text = "\n".join(textwrap.wrap(name, 14)[:4])
    box = draw.multiline_textbbox((0, 0), text, font=font, align="center")
    draw.multiline_text(((W - box[2]) // 2, (H - box[3]) // 2), text, font=font,
                        fill=(240, 240, 240), align="center")
    return card


def make_posters(entries):
    """Replace each entry's logo by a self-hosted 2:3 poster (cached across runs by URL hash)."""
    import hashlib
    from concurrent.futures import ThreadPoolExecutor
    POSTERS.mkdir(parents=True, exist_ok=True)

    def name_for(e):
        src = e["logo"] or f"name:{e['plain']}"
        return hashlib.sha1(src.encode()).hexdigest()[:16] + ".png"

    def render(e):
        path = POSTERS / name_for(e)
        if path.exists():
            return path.name
        img = None
        if e["logo"]:
            try:
                req = urllib.request.Request(e["logo"], headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    img = _poster_from_logo(r.read())
            except Exception:
                img = None
        if img is None:  # dead link, SVG, or no logo: readable name card instead
            path = POSTERS / (hashlib.sha1(f"name:{e['plain']}".encode()).hexdigest()[:16] + ".png")
            if path.exists():
                return path.name
            img = _poster_from_name(e["plain"])
        img.save(path, optimize=True)
        return path.name

    with ThreadPoolExecutor(16) as pool:
        names = list(pool.map(render, entries))
    for e, n in zip(entries, names):
        e["logo"] = f"{POSTER_BASE}/{n}"
    return set(names)


def m3u(entries, group_of):
    lines = ['#EXTM3U x-tvg-url="https://iptv-org.github.io/epg/guides/fr.xml"']
    for e in entries:
        lines.append(
            f'#EXTINF:-1 tvg-id="{e["id"]}" tvg-logo="{e["logo"]}" tvg-country="{e["country"]}" '
            f'group-title="{group_of(e)}",{e["name"]}'
        )
        if e["referrer"]:
            lines.append(f"#EXTVLCOPT:http-referrer={e['referrer']}")
        if e["user_agent"]:
            lines.append(f"#EXTVLCOPT:http-user-agent={e['user_agent']}")
        lines.append(e["url"])
    return "\n".join(lines) + "\n"


def write(rel, entries, group_of, index):
    """Queue a playlist; files are written in main() once posters exist."""
    if entries:
        index.append((rel, entries, group_of))


def main():
    entries = build_entries()
    index = []
    cat = lambda e: CATEGORY_FR.get(e["categories"][0], e["categories"][0])

    for lang in LANGUAGES:
        in_lang = [e for e in entries if lang in e["languages"]]
        write(f"{lang}/all.m3u", in_lang, cat, index)
        by_cat = defaultdict(list)
        for e in in_lang:
            for c in e["categories"]:
                by_cat[c].append(e)
        for c, items in sorted(by_cat.items()):
            write(f"{lang}/{c}.m3u", items, lambda e, c=c: CATEGORY_FR.get(c, c), index)

    sports = [e for e in entries if "sports" in e["categories"]]
    for lang, label in SPORTS_LANGUAGES.items():
        write(f"sports/{lang}.m3u", [e for e in sports if lang in e["languages"]], lambda e: f"Sports {label}", index)
    names = lambda e: " ".join([e["plain"], *e["alt"]])
    combat = [e for e in entries if COMBAT_STRONG.search(names(e))
              or ("sports" in e["categories"] and COMBAT_WEAK.search(names(e)))]
    write("sports/combat.m3u", combat, lambda e: "Sports de combat", index)

    if CUSTOM.is_dir():
        for txt in sorted(CUSTOM.glob("*.txt")):
            wanted = []  # (name or id, optional language) from lines like "France 24 | fra"
            for line in txt.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#"):
                    name, _, lang = line.partition("|")
                    wanted.append((name.strip().lower(), lang.strip().lower() or None))
            picked = [e for e in entries if any(
                n in (e["id"].lower(), e["plain"].lower()) and (not l or l in e["languages"])
                for n, l in wanted)]
            write(f"custom/{txt.stem}.m3u", picked, lambda e, n=txt.stem: n, index)

    published = {e["key"]: e for _, items, _ in index for e in items}
    print(f"Rendering posters for {len(published)} channels…", file=sys.stderr)
    used = make_posters(list(published.values()))
    for old in POSTERS.glob("*.png"):  # drop posters of channels that left every playlist
        if old.name not in used:
            old.unlink()

    for rel, items, group_of in index:
        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(m3u(items, group_of), encoding="utf-8")
    (OUT / "index.md").write_text(
        "# Playlists\n\n| Playlist | Chaînes |\n|---|---|\n"
        + "".join(f"| `{p}` | {len(i)} |\n" for p, i, _ in index), encoding="utf-8")
    for p, i, _ in index:
        print(f"{len(i):5d}  {p}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import os
        import traceback
        tb = traceback.format_exc()
        if os.environ.get("GITHUB_ACTIONS"):  # surface the error as a public run annotation
            print("::error title=build.py failed::" + tb.replace("%", "%25").replace("\n", "%0A"))
        raise
