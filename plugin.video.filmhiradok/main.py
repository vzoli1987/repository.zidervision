# -*- coding: utf-8 -*-
import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmc
import requests
import json
import re
import time

# --- KONFIGURÁCIÓ ---
ADDON = xbmcaddon.Addon()
BASE_URL = "https://filmhiradokonline.hu"
ITEMS_PER_PAGE = 20

session = requests.Session()

def get_html(url):
    """Lekéri az oldalt fix várakozással és süti-kezeléssel."""
    # A kérésednek megfelelően beállított 0.5 mp várakozás
    time.sleep(0.5) 
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0',
        'Referer': BASE_URL
    }
    try:
        r = session.get(url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        xbmc.log("Lekérési hiba: " + str(e), xbmc.LOGERROR)
        return None

def list_films_json(url, page=0):
    """Főoldali JSON típusú lista feldolgozása."""
    html = get_html(url)
    if not html: return
    match = re.search(r'var films\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not match: return
    
    all_films = json.loads(match.group(1))
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    
    for film in all_films[start:end]:
        add_video_item(
            title="({}) {}".format(film.get('year', ''), film.get('title', '')),
            db_id=film.get('id'),
            thumb="{}/getimage.php?src={}&size=medium".format(BASE_URL, film.get('mvh_id', '')),
            plot=film.get('content', '')
        )
    
    if len(all_films) > end:
        add_dir(">>> KÖVETKEZŐ OLDAL >>>", url, page + 1, mode='list_json')
    
    finalize_directory('movies')

def list_films_html(url):
    """Keresési és 'Új' találatok (HTML) feldolgozása."""
    html = get_html(url)
    if not html: return

    items = re.findall(r'class="search_item".*?src="(.*?)".*?href="watch\.php\?id=(\d+)">(.*?)</a>', html, re.DOTALL)
    
    for thumb_part, db_id, title in items:
        thumb = "{}/{}".format(BASE_URL, thumb_part.replace('size=small', 'size=medium').lstrip('/'))
        add_video_item(title.strip(), db_id, thumb, "")

    if 'class="right"' in html:
        current_page = 0
        p_match = re.search(r'page=(\d+)', url)
        if p_match: current_page = int(p_match.group(1))
        
        next_url = url
        if "page=" in next_url:
            next_url = re.sub(r'page=\d+', 'page={}'.format(current_page + 1), next_url)
        else:
            next_url += "&page=1"
        
        add_dir(">>> KÖVETKEZŐ OLDAL >>>", next_url, mode='list_html')

    finalize_directory('movies')

def add_video_item(title, db_id, thumb, plot):
    """Közös függvény videó elem hozzáadásához."""
    li = xbmcgui.ListItem(title)
    li.setArt({'thumb': thumb, 'poster': thumb, 'icon': thumb})
    li.getVideoInfoTag().setPlot(plot)
    li.getVideoInfoTag().setTitle(title)
    li.setProperty('IsPlayable', 'true')
    u = "{}?mode=play&id={}".format(sys.argv[0], db_id)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=u, listitem=li, isFolder=False)

def add_dir(title, url, page=0, mode='list_json'):
    """Mappa vagy gomb hozzáadása."""
    u = "{}?mode={}&url={}&page={}".format(sys.argv[0], mode, urllib.parse.quote_plus(url), page)
    li = xbmcgui.ListItem(title)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=u, listitem=li, isFolder=True)

def finalize_directory(content_type):
    xbmcplugin.setContent(int(sys.argv[1]), content_type)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def search():
    """Kodi billentyűzet a kereséshez. Csak redirect-el a listázáshoz."""
    kb = xbmcgui.Dialog().input('Keresés a Filmhíradókban', type=xbmcgui.INPUT_ALPHANUM)
    if kb:
        url = "{}/search.php?q={}".format(BASE_URL, urllib.parse.quote_plus(kb))
        # Nem hívjuk meg közvetlenül a listázást, hanem egy új Kodi útvonalra ugrunk
        search_path = "{}?mode=list_html&url={}".format(sys.argv[0], urllib.parse.quote_plus(url))
        xbmc.executebuiltin("Container.Update({})".format(search_path))

def play_film(video_id):
    """Lejátszás feloldása."""
    player_url = "{}/player.php?id={}".format(BASE_URL, video_id)
    html = get_html(player_url)
    video_match = re.search(r'["\']([^"\']+\.mp4)["\']', html)
    
    if video_match:
        video_url = video_match.group(1).replace('\\/', '/')
        if not video_url.startswith('http'):
            video_url = "{}/{}".format(BASE_URL, video_url.lstrip('/'))
            
        cookies = session.cookies.get_dict()
        cookies['fo[cookieaccept]'] = 'extra'
        cookie_str = "; ".join(["{}={}".format(k, v) for k, v in cookies.items()])
        
        headers = urllib.parse.urlencode({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0',
            'Referer': player_url,
            'Cookie': cookie_str
        })
        final_url = "{}|{}".format(video_url, headers)
        
        # Ez a fontos rész: a setResolvedUrl mondja meg a Kodinak, hogy ez egy lejátszható file
        listitem = xbmcgui.ListItem(path=final_url)
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, listitem=listitem)

def router(paramstring):
    params = dict(urllib.parse.parse_qsl(paramstring.lstrip('?')))
    mode = params.get('mode')
    
    if not mode:
        add_dir("Legfrissebbek (Új)", "{}/search.php?new".format(BASE_URL), mode='list_html')
        add_dir("Összes híradó (JSON lista)", "{}/index.php".format(BASE_URL), mode='list_json')
        # A keresés gomb is folder legyen, de a search() függvény Container.Update-et hív
        u = "{}?mode=search".format(sys.argv[0])
        li = xbmcgui.ListItem("[ KERESÉS ]")
        xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=u, listitem=li, isFolder=False)
        finalize_directory('addons')
    elif mode == 'list_json':
        list_films_json(params.get('url'), int(params.get('page', 0)))
    elif mode == 'list_html':
        list_films_html(params.get('url'))
    elif mode == 'search':
        search()
    elif mode == 'play':
        play_film(params.get('id'))

if __name__ == '__main__':
    router(sys.argv[2])