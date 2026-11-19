#!/usr/bin/env python3
"""Build a static Stremio addon (plain JSON files, no server) from the playlists.

    python addon.py out/addon-data.json guide.xml.gz dist

dist/ is published as it is on the "addon" branch; Stremio installs
https://raw.githubusercontent.com/<account>/iptv-playlists/addon/manifest.json

  manifest.json                         one "tv" catalogue, one genre per playlist group
  catalog/tv/chaines.json               every channel once
  catalog/tv/chaines/genre=<group>.json the channels of one group
  meta/tv/<id>.json                     channel page with the schedule
  stream/tv/<id>.json                   the stream

Each channel's description is its schedule in Paris time, so Stremio shows it in the
side panel of the catalogue. It is a snapshot: the workflow rebuilds it every hour.
"""

import gzip
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")
PREFIX = "iptvfr_"
CATALOG = "chaines"
PANEL_LINES, PAGE_LINES = 5, 12   # programmes listed in the side panel / on the channel page
TITLE_MAX, LINE_MIN = 28, 32      # entry width, see schedule()
DAYS = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]


def genre_name(group):
    """'1 Films FR' -> 'Films FR': the manifest keeps the order, so the number can go."""
    return re.sub(r"^\d+ ", "", group).replace(" & ", " et ")


def load_guide(path, now):
    """tvg-id -> programmes still running or coming, sorted by start."""
    guide = {}
    with gzip.open(path, "rb") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag != "programme":
                continue
            try:
                start = datetime.strptime(el.get("start"), "%Y%m%d%H%M%S %z")
                stop = datetime.strptime(el.get("stop"), "%Y%m%d%H%M%S %z")
            except (TypeError, ValueError):
                start = stop = None
            if stop and stop > now:
                guide.setdefault(el.get("channel"), []).append(
                    (start, stop, el.findtext("title") or "", el.findtext("desc") or ""))
            el.clear()
    for progs in guide.values():
        progs.sort(key=lambda p: p[0])
    return guide


def schedule(progs, now, limit):
    lines = []
    for start, _, title, _ in progs[:limit]:
        local = start.astimezone(TZ)
        day = "" if local.date() == now.astimezone(TZ).date() else DAYS[local.weekday()] + " "
        title = title if len(title) <= TITLE_MAX else title[:TITLE_MAX - 1].rstrip() + "…"
        line = f"{'▶' if start <= now else '•'} {day}{local:%H:%M}  {title}"
        # Stremio's side panel ignores line breaks. Unbreakable spaces keep an entry in one
        # piece, and padding makes it too wide for two entries to share a line.
        lines.append(line.replace(" ", "\u00a0") + "\u2007" * max(0, LINE_MIN - len(line)))
    return "\n".join(lines)


def build(data_path, guide_path, dist):
    now = datetime.now(timezone.utc)
    rows = json.loads(Path(data_path).read_text(encoding="utf-8"))
    guide = load_guide(guide_path, now) if guide_path and Path(guide_path).exists() else {}

    channels, genres = {}, []          # channels keep the order of tout.m3u: pinned groups first
    for r in rows:
        g = genre_name(r["group"])
        if g not in genres:
            genres.append(g)
        ch = channels.setdefault(r["key"], {**r, "genres": []})
        ch["genres"].append(g)

    def write(rel, obj):
        path = dist / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    previews = []
    for ch in channels.values():
        cid = PREFIX + hashlib.md5(ch["key"].encode()).hexdigest()[:12]
        progs = guide.get(ch["id"], [])
        base = {"id": cid, "type": "tv", "name": ch["name"], "poster": ch["logo"], "posterShape": "poster",
                "genres": ch["genres"]}
        if ch["logo_src"].lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            base["logo"] = ch["logo_src"]   # shown small at the top of the side panel
        panel = schedule(progs, now, PANEL_LINES) or "Pas de programme TV pour cette chaîne."
        previews.append({**base, "description": panel})

        page = schedule(progs, now, PAGE_LINES)
        if progs and progs[0][0] <= now and progs[0][3]:
            page = f"{progs[0][2]} : {progs[0][3]}\n\n{page}"
        page = (page or "Pas de programme TV pour cette chaîne.") + f"\n\nMis à jour à {now.astimezone(TZ):%H:%M}"
        write(f"meta/tv/{cid}.json", {"meta": {**base, "background": ch["logo"], "description": page,
                                              "runtime": "Direct"}})

        headers = {k: v for k, v in (("Referer", ch["referrer"]), ("User-Agent", ch["user_agent"])) if v}
        hints = {"notWebReady": True}
        if headers:
            hints["proxyHeaders"] = {"request": headers}
        write(f"stream/tv/{cid}.json", {"streams": [{"url": ch["url"], "name": "Direct", "title": ch["name"],
                                                     "behaviorHints": hints}]})

    write(f"catalog/tv/{CATALOG}.json", {"metas": previews})
    for g in genres:
        write(f"catalog/tv/{CATALOG}/genre={g}.json", {"metas": [p for p in previews if g in p["genres"]]})
    write("manifest.json", {
        "id": "org.iptv-playlists.fr", "version": "1.0.0", "name": "TV FR",
        "description": "Chaînes en français, sports et sélection perso, avec le programme TV.",
        "resources": ["catalog", "meta", "stream"], "types": ["tv"], "idPrefixes": [PREFIX],
        "catalogs": [{"type": "tv", "id": CATALOG, "name": "TV FR",
                      "extra": [{"name": "genre", "options": genres, "isRequired": False}]}],
    })
    with_guide = sum(1 for ch in channels.values() if guide.get(ch["id"]))
    print(f"{len(channels)} channels, {with_guide} with a schedule, {len(genres)} genres")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
