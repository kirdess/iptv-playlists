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
    if not entries:
        return
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(m3u(entries, group_of), encoding="utf-8")
    index.append((rel, len(entries)))


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

    (OUT / "index.md").write_text(
        "# Playlists\n\n| Playlist | Chaînes |\n|---|---|\n"
        + "".join(f"| `{p}` | {n} |\n" for p, n in index), encoding="utf-8")
    for p, n in index:
        print(f"{n:5d}  {p}")


if __name__ == "__main__":
    main()
