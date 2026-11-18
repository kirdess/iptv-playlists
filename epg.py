"""Build one small XMLTV guide for the channels of the playlists.

Public guides are downloaded, their channels are matched to the playlist channels
(same id, same Pluto TV id in the stream URL, or same name), and the programmes of the
next two days are rewritten under the playlist's tvg-id into out/epg/guide.xml.gz.
"""

import gzip
import re
import sys
import tempfile
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

GUIDE_URL = "https://raw.githubusercontent.com/kirdess/iptv-playlists/epg/guide.xml.gz"
HOURS_BEFORE, HOURS_AFTER = 3, 48
DESC_MAX = 400

# (url, languages whose channels may be matched by name; None = any language).
# Earlier sources win. Name matching is limited by language so that a French channel
# never gets the schedule of a foreign channel with the same name.
SOURCES = [
    ("https://xmltvfr.fr/xmltv/xmltv.xml.gz", None),
    ("https://i.mjh.nz/PlutoTV/fr.xml.gz", {"fra"}),
    ("https://i.mjh.nz/PlutoTV/all.xml.gz", {"eng"}),
    ("https://epgshare01.online/epgshare01/epg_ripper_FR1.xml.gz", {"fra"}),
    ("https://epgshare01.online/epgshare01/epg_ripper_CH1.xml.gz", {"fra"}),
    ("https://i.mjh.nz/SamsungTVPlus/all.xml.gz", {"eng"}),
    ("https://i.mjh.nz/Plex/all.xml.gz", {"eng"}),
]
# tvg-id -> name of the same channel in the guides, when the names differ too much
ALIASES = {
    "EuronewsFrench.fr": "Euronews", "ScienceVieTV.fr": "Science et Vie TV",
    "BFMTechCo.fr": "TECH & CO", "LeFigaroTVIledeFrance.fr": "Le Figaro TV",
    "TebeoTV.fr": "TEBEO", "MuseumTVFrench.fr": "MUSEUM TV", "TiVi5Monde.fr": "Tivi5",
    "TV5MondeStyle.fr": "TV5 Style", "TraceVanillaIslands.fr": "TRACE VANILLA",
    "TVR.fr": "TV RENNES 35", "InvestigationDiscovery.fr": "Discovery Investigation",
    "TV5MondeLatinAmerica.fr": "TV5MondeAmeriqueLatine.fr",
}
PLUTO_ID = re.compile(r"jmp2\.uk/plu-([0-9a-f]+)")


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(f?hd|uhd|sd|4k)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def _open(path):
    with open(path, "rb") as f:
        gz = f.read(2) == b"\x1f\x8b"
    return gzip.open(path, "rb") if gz else open(path, "rb")


def _elements(path, tag):
    """Yield every <tag> element of an XMLTV file without loading the file."""
    with _open(path) as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag == tag:
                yield el
            if el.tag in ("channel", "programme"):
                el.clear()


def _match(path, langs, entries, done):
    """Map this guide's channel ids to the tvg-ids that still have no guide.

    Returns (guide id -> tvg-ids, tvg-id -> channel name).
    """
    by_lower, by_name = {}, {}
    for el in _elements(path, "channel"):
        cid = el.get("id") or ""
        by_lower.setdefault(cid.lower(), cid)
        for d in el.findall("display-name"):
            n = norm(d.text or "")
            if len(n) > 2:
                by_name.setdefault(n, cid)
    mapping, matched = {}, {}
    for e in entries:
        if e["id"] in done or e["id"] in matched:
            continue
        cid = by_lower.get(e["id"].lower())
        if not cid:
            m = PLUTO_ID.search(e["url"])
            cid = by_lower.get(m.group(1)) if m else None
        if not cid and (langs is None or langs & set(e["languages"])):
            cid = next((by_name[n] for n in map(norm, [e["plain"], *e["alt"], ALIASES.get(e["id"], "")])
                        if n in by_name), None)
        if cid:
            mapping.setdefault(cid, []).append(e["id"])
            matched[e["id"]] = e["plain"]
    return mapping, matched


def _time(value):
    try:
        t = datetime.strptime(value.strip(), "%Y%m%d%H%M%S %z" if " " in value.strip() else "%Y%m%d%H%M%S")
    except (ValueError, AttributeError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _programmes(path, mapping, start, end):
    for el in _elements(path, "programme"):
        ids = mapping.get(el.get("channel"))
        if not ids:
            continue
        t0, t1 = _time(el.get("start")), _time(el.get("stop"))
        if not t0 or not t1 or t1 <= start or t0 >= end:
            continue
        body = ""
        for tag, limit in (("title", 200), ("sub-title", 200), ("desc", DESC_MAX), ("category", 60)):
            child = el.find(tag)
            text = (child.text or "").strip() if child is not None else ""
            if text:
                if len(text) > limit:
                    text = text[:limit - 1].rstrip() + "…"
                lang = child.get("lang")
                body += f"<{tag}{' lang=' + quoteattr(lang) if lang else ''}>{escape(text)}</{tag}>"
        if "<title" not in body:
            continue
        for tvg in ids:
            yield tvg, t0, (f'<programme start={quoteattr(el.get("start"))} stop={quoteattr(el.get("stop"))} '
                            f'channel={quoteattr(tvg)}>{body}</programme>')


def build(entries, out_dir):
    """Write out_dir/guide.xml.gz and return the set of tvg-ids that have programmes."""
    now = datetime.now(timezone.utc)
    start, end = now - timedelta(hours=HOURS_BEFORE), now + timedelta(hours=HOURS_AFTER)
    done, lines = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        for i, (url, langs) in enumerate(SOURCES):
            path = Path(tmp) / f"{i}.xml"
            try:
                _download(url, path)
                mapping, matched = _match(path, langs, entries, done)
                found = {}
                for tvg, t0, line in _programmes(path, mapping, start, end):
                    found.setdefault(tvg, []).append((t0, line))
                # a channel listed without programmes stays open for the next sources
                done.update({k: v for k, v in matched.items() if k in found})
                lines.update(found)
                print(f"{len(found):5d}  guide channels from {url}", file=sys.stderr)
            except Exception as exc:  # one dead source must not stop the build
                print(f"::warning title=Guide source failed::{url}: {exc}")
            finally:
                path.unlink(missing_ok=True)
    if not lines:
        return set()
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "guide.xml.gz", "wb") as raw, \
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="guide.xml") as gz:
        gz.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<tv generator-info-name="iptv-playlists">\n')
        for tvg in sorted(lines):
            gz.write(f"<channel id={quoteattr(tvg)}><display-name>{escape(done[tvg])}</display-name></channel>\n".encode())
        for tvg in sorted(lines):
            for _, line in sorted(lines[tvg], key=lambda p: p[0]):
                gz.write(line.encode() + b"\n")
        gz.write(b"</tv>\n")
    return set(lines)
