# -*- coding: utf-8 -*-
import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmc
import xbmcvfs
import requests
import json
import re
import os

# --- KONFIGURÁCIÓ ---
ADDON = xbmcaddon.Addon()
BASE_URL = "https://filmhiradokonline.hu"
THUMB_URL_BASE = "https://filmhiradokonline.hu/keyframe/fo/"
ITEMS_PER_PAGE = 20
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0'

PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
HISTORY_FILE = os.path.join(PROFILE_PATH, 'search_history.json')
if not xbmcvfs.exists(PROFILE_PATH): xbmcvfs.mkdirs(PROFILE_PATH)

session = requests.Session()

# --- SEGÉDFÜGGVÉNYEK ---

def get_html(url):
    xbmc.sleep(500) # 0.5s várakozás (felhasználói kérés)
    headers = {
        'User-Agent': USER_AGENT, 
        'Referer': BASE_URL + '/index.php',
        'Accept': 'application/json, text/plain, */*'
    }
    try:
        r = session.get(url, headers=headers, timeout=10)
        r.encoding = 'utf-8'
        return r.text
    except: return None

def get_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except: pass
    return []

def save_history(keyword):
    h = get_history()
    if keyword in h: h.remove(keyword)
    h.insert(0, keyword)
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f: json.dump(h[:10], f)

def get_large_thumb(mvh_id):
    if not mvh_id: return ""
    return "{}{}.jpg".format(THUMB_URL_BASE, mvh_id)

# --- LISTÁZÁS ---

def list_films_json(url, page=0):
    """Archívum és Évszámok (JSON alapú)."""
    data_text = get_html(url)
    if not data_text: return
    
    # Ha HTML-be ágyazott JSON (Archívum főoldal)
    if "var films =" in data_text:
        match = re.search(r'var films\s*=\s*(\[.*?\]);', data_text, re.DOTALL)
        if not match: return
        all_films = json.loads(match.group(1))
    else:
        # Ha tiszta JSON (timemachine2.php)
        try:
            all_films = json.loads(data_text)
        except: return

    start, end = page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE
    for film in all_films[start:end]:
        f_id = film.get('id')
        display_title = "({}) {}".format(film.get('year', ''), film.get('title', ''))
        large_thumb = get_large_thumb(film.get('mvh_id'))
        plot = "[B][COLOR green]ÖSSZEFOGLALÓ:[/COLOR][/B]\n" + film.get('content', '')
        if film.get('annotation'):
            plot += "\n\n[B][COLOR white]RÉSZLETEK:[/COLOR][/B]\n" + film.get('annotation', '')
        add_video_item(display_title, f_id, large_thumb, plot)
        
    if len(all_films) > end:
        add_dir("[B][COLOR green]>>> KÖVETKEZŐ OLDAL >>>[/COLOR][/B]", url, page + 1, mode='list_json')
    finalize_directory('movies')

def list_films_html(url):
    """Kulcsszavas keresés és Legfrissebbek (HTML alapú)."""
    html = get_html(url)
    if not html: return
    
    items = re.findall(r'class="search_item".*?src="(.*?)".*?href="watch\.php\?id=(\d+)">(.*?)</a>', html, re.DOTALL)
    for thumb_part, db_id, title in items:
        mvh_id_match = re.search(r'src=([^&]+)', thumb_part)
        mvh_id = mvh_id_match.group(1) if mvh_id_match else ""
        large_thumb = get_large_thumb(mvh_id)
        add_video_item(title.strip(), db_id, large_thumb, "")
    
    if 'class="right"' in html or ">next<" in html.lower():
        current_page = int(re.search(r'page=(\d+)', url).group(1)) if 'page=' in url else 0
        next_url = re.sub(r'page=\d+', 'page={}'.format(current_page + 1), url) if 'page=' in url else url + "&page=1"
        add_dir("[B][COLOR green]>>> KÖVETKEZŐ OLDAL >>>[/COLOR][/B]", next_url, mode='list_html')
    finalize_directory('movies')

def add_video_item(title, db_id, thumb, plot):
    li = xbmcgui.ListItem(title)
    li.setArt({'thumb': thumb, 'poster': thumb, 'icon': thumb, 'fanart': thumb})
    li.setInfo('video', {'plot': plot, 'title': title})
    li.getVideoInfoTag().setPlot(plot)
    li.getVideoInfoTag().setTitle(title)
    li.setProperty('IsPlayable', 'true')
    u = "{}?mode=play&id={}".format(sys.argv[0], db_id)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=u, listitem=li, isFolder=False)

def add_dir(title, url, page=0, mode='list_json'):
    u = "{}?mode={}&url={}&page={}".format(sys.argv[0], mode, urllib.parse.quote_plus(url), page)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=u, listitem=xbmcgui.ListItem(title), isFolder=True)

def finalize_directory(ctype):
    xbmcplugin.setContent(int(sys.argv[1]), ctype)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

# --- LEJÁTSZÁS ---

class FilmhiradoMonitor(xbmc.Player):
    def __init__(self, start_t, end_t):
        self.start_t, self.end_t = float(start_t or 0), float(end_t or 0)
        self.seek_done = False
        xbmc.Player.__init__(self)

    def onAVStarted(self):
        if self.start_t > 0 and not self.seek_done:
            xbmc.sleep(1500)
            self.seekTime(self.start_t)
            self.seek_done = True

    def check_end(self):
        if self.isPlaying() and self.end_t > 0:
            if self.getTime() >= self.end_t:
                self.stop()
                return True
        return False

def play_film(video_id):
    player_url = "{}/player.php?id={}".format(BASE_URL, video_id)
    html = get_html(player_url)
    if not html: return
    video_match = re.search(r'<source\s+src=["\']([^"\']+\.mp4)["\']', html, re.I)
    if not video_match: return
    video_url = video_match.group(1).replace('\\/', '/')
    if not video_url.startswith('http'): video_url = "{}/{}".format(BASE_URL, video_url.lstrip('/'))

    start_t = re.search(r'var\s+start\s*=\s*(\d+);', html).group(1) if "var start" in html else 0
    end_t = re.search(r'var\s+end\s*=\s*(\d+);', html).group(1) if "var end" in html else 0

    cookies = session.cookies.get_dict()
    cookie_str = "fo[cookieaccept]=extra"
    if cookies: cookie_str += "; " + "; ".join(["{}={}".format(k, v) for k, v in cookies.items()])
    
    headers = {'User-Agent': USER_AGENT, 'Referer': player_url, 'Cookie': cookie_str}
    final_url = video_url + "|" + urllib.parse.urlencode(headers)
    
    li = xbmcgui.ListItem(path=final_url)
    xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, listitem=li)

    monitor = FilmhiradoMonitor(start_t, end_t)
    for _ in range(40):
        if monitor.isPlaying(): break
        xbmc.sleep(500)
    while monitor.isPlaying():
        if monitor.check_end(): break
        xbmc.sleep(1000)

# --- MENÜK ---

def main():
    params = dict(urllib.parse.parse_qsl(sys.argv[2].lstrip('?')))
    mode = params.get('mode')
    
    if not mode:
        add_dir("[B][COLOR red]:: LEGFRISSEBBEK ::[/COLOR][/B]", "{}/search.php?new".format(BASE_URL), mode='list_html')
        add_dir("[B][COLOR green]:: ARCHÍVUM (Összes) ::[/COLOR][/B]", "{}/index.php".format(BASE_URL), mode='list_json')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), sys.argv[0]+"?mode=year_menu", xbmcgui.ListItem("[B][ TALLÓZÁS ÉV SZERINT ][/B]"), True)
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), sys.argv[0]+"?mode=search_menu", xbmcgui.ListItem("[B][ KERESÉS SZÖVEGGEL ][/B]"), True)
        finalize_directory('addons')
        
    elif mode == 'year_menu':
        for year in range(1991, 1913, -1):
            url = "{}/timemachine2.php?year={}".format(BASE_URL, year)
            u = "{}?mode=list_json&url={}".format(sys.argv[0], urllib.parse.quote_plus(url))
            xbmcplugin.addDirectoryItem(int(sys.argv[1]), u, xbmcgui.ListItem("[COLOR yellow]Évszám:[/COLOR] {}".format(year)), True)
        finalize_directory('addons')
        
    elif mode == 'search_menu':
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), sys.argv[0]+"?mode=do_search", xbmcgui.ListItem("[COLOR red]ÚJ KERESÉS INDÍTÁSA[/COLOR]"), False)
        for item in get_history():
            url = "{}/search.php?q={}".format(BASE_URL, urllib.parse.quote_plus(item))
            u = "{}?mode=list_html&url={}".format(sys.argv[0], urllib.parse.quote_plus(url))
            xbmcplugin.addDirectoryItem(int(sys.argv[1]), u, xbmcgui.ListItem("[COLOR green]Előzmény:[/COLOR] " + item), True)
        finalize_directory('addons')
        
    elif mode == 'do_search':
        kb = xbmcgui.Dialog().input('Keresés', type=xbmcgui.INPUT_ALPHANUM)
        if kb:
            save_history(kb)
            url = "{}/search.php?q={}".format(BASE_URL, urllib.parse.quote_plus(kb))
            xbmc.executebuiltin("Container.Update({}?mode=list_html&url={})".format(sys.argv[0], urllib.parse.quote_plus(url)))
            
    elif mode == 'list_json': list_films_json(params.get('url'), int(params.get('page', 0)))
    elif mode == 'list_html': list_films_html(params.get('url'))
    elif mode == 'play': play_film(params.get('id'))

if __name__ == '__main__':
    main()