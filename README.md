# IPTV playlists (iptv-org, filtrées)

Playlists M3U générées chaque jour depuis [iptv-org](https://github.com/iptv-org/iptv) par `build.py` (GitHub Actions).

- `out/fra/all.m3u` : toutes les chaînes en français, groupées par catégorie
- `out/fra/<catégorie>.m3u` : films (`movies`), séries, sports, infos (`news`), jeunesse (`kids`), musique…
- `out/sports/fra.m3u`, `out/sports/eng.m3u` : sports en français / anglais
- `out/sports/combat.m3u` : boxe, MMA, UFC, catch, kickboxing (toutes langues)
- `out/tout.m3u` : toutes les listes ci-dessous dans un seul fichier, un groupe par liste (Films FR, Séries FR, Sports FR, Sports EN, Sports de combat, puis les autres catégories) ; c'est le lien à donner à NexoTV
- `out/custom/<nom>.m3u` : listes perso, éditer `custom/<nom>.txt`

Liste complète avec le nombre de chaînes : [`out/index.md`](out/index.md).
## Programme TV (EPG)

`epg.py` assemble chaque jour un guide XMLTV limité aux chaînes des playlists (48 h de programmes),
à partir de xmltvfr.fr, i.mjh.nz (Pluto TV, Samsung TV Plus, Plex) et epgshare01. Il est publié sur la
branche `epg` : `https://raw.githubusercontent.com/<compte>/iptv-playlists/epg/guide.xml.gz`.

Chaque playlist annonce ce guide dans son en-tête (`url-tvg`), donc NexoTV le charge tout seul si
« Program guide » est coché ; rien à saisir dans « custom guide URL ». La colonne « Avec programme TV »
de [`out/index.md`](out/index.md) donne la couverture. Les chaînes locales sans guide public restent sans programme ;
pour une chaîne mal reconnue, ajouter son nom dans `ALIASES` (`epg.py`).

Lien à donner à NexoTV (instance publique, aucun serveur à la maison) : `https://raw.githubusercontent.com/<compte>/iptv-playlists/main/out/<fichier>.m3u`
