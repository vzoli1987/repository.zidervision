import xbmc
import xbmcplugin
import xbmcgui
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import sys
import urllib.parse

# Kodi plugin handle
handle = int(sys.argv[1])

# Segédfüggvények importálása a resources mappából
from resources.porthu_scraper import get_port_film_description, search_port_movies
from resources.musor_utils import get_programs

# NAPLÓ FUNKCIÓ HIBAKERESÉSHEZ
def log(message, level=xbmc.LOGINFO):
    xbmc.log(f"[Műsor TV Debug] {message}", level)

# A műsorok listájának beolvasása és megjelenítése Kodi-ban
def list_programs():
    log("Lista megjelenítése")
    programs = get_programs()

    if not programs:
        log("Nem találhatóak programok.")
        xbmcgui.Dialog().notification("Hiba", "Nem találhatóak műsorok.", xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(handle)
        return

    for program in programs:
        # Ellenőrizzük, hogy a cím valóban létezik
        title = program.get('title', 'Ismeretlen cím')
        channel_name = program.get('channel', 'Ismeretlen csatorna')

        # Port.hu link keresése a cím alapján
        movie_url = search_port_movies(title)
        if movie_url:
            description = get_port_film_description(movie_url)
        else:
            description = "Nincs leírás elérhető."

        label = f"[COLOR blue]{title}[/COLOR] | [B]{channel_name}[/B]"

        # Kép és információk hozzáadása
        li = xbmcgui.ListItem(label=label)  # Csatorna és cím együtt
        li.setInfo('video', {
            'title': title, 
            'plot': f"Csatorna: {channel_name} - Időpont: {program.get('time', 'N/A')}\nLeírás: {description}"
        })

        # Csatorna logója a bal oldalon és bélyegkép a műsor.tv-ről
        li.setArt({
            'thumb': program.get('img_url', 'https://example.com/default_image.jpg'),  # Nagyobb bélyegkép
            'icon': program.get('logo_url', 'https://example.com/default_icon.jpg'),  # Csatorna logó
            'fanart': program.get('img_url', 'https://example.com/default_image.jpg')  # Fanart kép
        })

        # URL generálása és menüelem hozzáadása
        url = f"plugin://plugin.video.musortv/{program.get('channel', 'unknown')}/{program.get('time', 'unknown')}"
        xbmcplugin.addDirectoryItem(handle=handle, url=url, listitem=li, isFolder=False)
    
    xbmcplugin.endOfDirectory(handle)
    log("Lista megjelenítése befejezve")

# Program indítása
if __name__ == '__main__':
    log("Műsor TV bővítmény indítása")
    list_programs()
