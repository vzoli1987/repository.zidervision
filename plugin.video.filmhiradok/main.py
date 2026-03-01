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
# Felhasználói instrukció alapján a nagy bélyegkép alapja
THUMB_URL_BASE = "https://filmhiradokonline.hu/keyframe/fo/"
ITEMS_PER_PAGE = 20
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

PROFILE_PATH = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
HISTORY_FILE = os.path.join(PROFILE_PATH, 'search_history.json')
if not xbmcvfs.exists(PROFILE_PATH): xbmcvfs.mkdirs(PROFILE_PATH)

session = requests.Session()

# --- SEGÉDFÜGGVÉNYEK ---

def get_html(url):
    xbmc.sleep(500)
    headers = {'User-Agent': USER_AGENT, 'Referer': BASE_URL}
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
    """
    User instruction: mvh_id-ból (pl. MFH_1989_23-04) nagy felbontású bélyegkép URL generálása.
    URL formátum: https://filmhiradokonline.hu/keyframe/fo/MFH_1989_23-04.jpg
    """
    if not mvh_id: return ""
    return "{}{}.jpg".format(THUMB_URL_BASE, mvh_id)

# --- LISTÁZÁS ---

def list_films_json(url, page=0):
    html = get_html(url)
    if not html: return
    match = re.search(r'var films\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not match: return
    
    try:
        all_films = json.loads(match.group(1))
    except: return

    start, end = page * ITEMS_PER_PAGE, (page + 1) * ITEMS_PER_PAGE

    for film in all_films[start:end]:
        f_id = film.get('id')
        year = film.get('year', '')
        title = film.get('title', '')
        display_title = "({}) {}".format(year, title)
        
        # Nagy felbontású bélyegkép generálása az mvh_id alapján
        large_thumb = get_large_thumb(film.get('mvh_id'))
        
        plot = "[B][COLOR green]ÖSSZEFOGLALÓ:[/COLOR][/B]\n" + film.get('content', '')
        if film.get('annotation'):
            plot += "\n\n[B][COLOR white]RÉSZLETEK:[/COLOR][/B]\n" + film.get('annotation', '')

        add_video_item(display_title, f_id, large_thumb, plot)
        
    if len(all_films) > end:
        add_dir("[B][COLOR green]>>> KÖVETKEZŐ OLDAL >>>[/COLOR][/B]", url, page + 1, mode='list_json')
    finalize_directory('movies')

def list_films_html(url):
    html = get_html(url)
    if not html: return
    # HTML-ből kinyerjük awatch.php linkeket és a címet
    items = re.findall(r'class="search_item".*?src="(.*?)".*?href="watch\.php\?id=(\d+)">(.*?)</a>', html, re.DOTALL)
    
    for thumb_part, db_id, title in items:
        # A HTML-ben a kis kép URL-je van, de a getimage.php hívásból kinyerhetjük az mvh_id-t a nagy képhez
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
    li.setArt({'thumb': thumb, 'poster': thumb, 'icon': thumb, 'fanart': thumb}) # A bélyegképet használjuk fanartnak is a leírás mögé
    
    # Plot javítás Kodi 20/21-hez
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

# --- LEJÁTSZÁS (MONITORRAL ÉS SÜTI FIXEL) ---

class FilmhiradoMonitor(xbmc.Player):
    def __init__(self, start_t, end_t):
        self.start_t = float(start_t) if start_t else 0
        self.end_t = float(end_t) if end_t else 0
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
    if not video_url.startswith('http'): 
        video_url = "{}/{}".format(BASE_URL, video_url.lstrip('/'))

    # JS változók kimentése az időzítéshez
    start_t = re.search(r'var\s+start\s*=\s*(\d+);', html).group(1) if "var start" in html else 0
    end_t = re.search(r'var\s+end\s*=\s*(\d+);', html).group(1) if "var end" in html else 0

    # Sütik összeállítása a 403 hiba elkerülésére
    cookies = session.cookies.get_dict()
    cookie_str = "fo[cookieaccept]=extra"
    if cookies:
        cookie_str += "; " + "; ".join(["{}={}".format(k, v) for k, v in cookies.items()])

    # Fejlécek a Kodi lejátszónak
    headers = {
        'User-Agent': USER_AGENT,
        'Referer': player_url,
        'Cookie': cookie_str
    }
    
    final_url = video_url + "|" + urllib.parse.urlencode(headers)
    
    li = xbmcgui.ListItem(path=final_url)
    # Beállítjuk a bélyegképet a videóhoz is, ha elindul
    mvh_id_match = re.search(r'id=(\d+)', player_url) # Ezt nehéz kinyerni az mvh_id-ből, de a player URL-ben ott az ID
    large_thumb = "" # Nehéz kitalálni az mvh_id-t az ID-ból HTTP hívás nélkül
    
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
        add_dir("[B][COLOR green]:: ARCHÍVUM ::[/COLOR][/B]", "{}/index.php".format(BASE_URL), mode='list_json')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), sys.argv[0]+"?mode=search_menu", xbmcgui.ListItem("[B][ KERESÉS ][/B]"), True)
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