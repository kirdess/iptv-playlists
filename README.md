# IPTV playlists (iptv-org, filtrées)

Playlists M3U générées chaque jour depuis [iptv-org](https://github.com/iptv-org/iptv) par `build.py` (GitHub Actions).

- `out/fra/all.m3u` : toutes les chaînes en français, groupées par catégorie
- `out/fra/<catégorie>.m3u` : films (`movies`), séries, sports, infos (`news`), jeunesse (`kids`), musique…
- `out/sports/fra.m3u`, `out/sports/eng.m3u` : sports en français / anglais
- `out/sports/combat.m3u` : boxe, MMA, UFC, catch, kickboxing (toutes langues)
- `out/custom/<nom>.m3u` : listes perso, éditer `custom/<nom>.txt`

Liste complète avec le nombre de chaînes : [`out/index.md`](out/index.md).
Lien à donner à NexoTV : `https://raw.githubusercontent.com/<compte>/iptv-playlists/main/out/<fichier>.m3u`
