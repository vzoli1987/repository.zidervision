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

# --- SEGÉDFÜGGVÉNYEK ---

def get_html(url):
    """Lekéri az oldalt fix várakozással (User instruction: 0.5s)."""
    xbmc.sleep(500) # Kodi-barát várakozás
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0',
        'Referer': BASE_URL
    }
    try:
        r = session.get(url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        xbmc.log("Filmhirado - Hiba: " + str(e), xbmc.LOGERROR)
        return None

# --- EGYEDI LEJÁTSZÓ (A JS OFFSET LOGIKA SZIMULÁLÁSA) ---

class FilmhiradoMonitor(xbmc.Player):
    def __init__(self, start_time, end_time):
        self.start_offset = float(start_time)
        self.end_limit = float(end_time)
        self.seek_done = False
        xbmc.Player.__init__(self)

    def onAVStarted(self):
        """Amint elindul a média, elvégezzük a kezdő ugrást."""
        if self.start_offset > 0 and not self.seek_done:
            xbmc.log("Filmhirado: JS Offset szimuláció - Ugrás: {}s".format(self.start_offset), xbmc.LOGINFO)
            # Többszöri próbálkozás, mert a Kodi 21 néha eldobja az első seeket
            for i in range(5):
                xbmc.sleep(600) 
                self.seekTime(self.start_offset)
                # Ellenőrizzük, sikerült-e (kb.)
                if abs(self.getTime() - self.start_offset) < 2:
                    self.seek_done = True
                    break

    def check_end(self):
        """Ezt hívjuk a főciklusból a 'timeupdate' helyett."""
        if self.isPlaying() and self.end_limit > 0:
            curr = self.getTime()
            if curr >= self.end_limit:
                xbmc.log("Filmhirado: Elérve a JS szerinti végpont ({}) - Stop.".format(self.end_limit), xbmc.LOGINFO)
                self.stop()
                return True
        return False

# --- LISTÁZÁS ÉS KERESÉS ---

def list_films_json(url, page=0):
    html = get_html(url)
    if not html: return
    match = re.search(r'var films\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not match: return
    all_films = json.loads(match.group(1))
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    for film in all_films[start:end]:
        add_video_item("({}) {}".format(film.get('year', ''), film.get('title', '')), 
                       film.get('id'), 
                       "{}/getimage.php?src={}&size=medium".format(BASE_URL, film.get('mvh_id', '')), 
                       film.get('content', ''))
    if len(all_films) > end:
        add_dir(">>> KÖVETKEZŐ OLDAL >>>", url, page + 1, mode='list_json')
    finalize_directory('movies')

def list_films_html(url):
    html = get_html(url)
    if not html: return
    items = re.findall(r'class="search_item".*?src="(.*?)".*?href="watch\.php\?id=(\d+)">(.*?)</a>', html, re.DOTALL)
    for thumb_part, db_id, title in items:
        thumb = "{}/{}".format(BASE_URL, thumb_part.replace('size=small', 'size=medium').lstrip('/'))
        add_video_item(title.strip(), db_id, thumb, "")
    if 'class="right"' in html:
        current_page = int(re.search(r'page=(\d+)', url).group(1)) if 'page=' in url else 0
        next_url = re.sub(r'page=\d+', 'page={}'.format(current_page + 1), url) if 'page=' in url else url + "&page=1"
        add_dir(">>> KÖVETKEZŐ OLDAL >>>", next_url, mode='list_html')
    finalize_directory('movies')

def add_video_item(title, db_id, thumb, plot):
    li = xbmcgui.ListItem(title)
    li.setArt({'thumb': thumb, 'poster': thumb, 'icon': thumb})
    li.getVideoInfoTag().setPlot(plot)
    li.getVideoInfoTag().setTitle(title)
    li.setProperty('IsPlayable', 'true')
    u = "{}?mode=play&id={}".format(sys.argv[0], db_id)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=u, listitem=li, isFolder=False)

def add_dir(title, url, page=0, mode='list_json'):
    u = "{}?mode={}&url={}&page={}".format(sys.argv[0], mode, urllib.parse.quote_plus(url), page)
    li = xbmcgui.ListItem(title)
    xbmcplugin.addDirectoryItem(handle=int(sys.argv[1]), url=u, listitem=li, isFolder=True)

def finalize_directory(content_type):
    xbmcplugin.setContent(int(sys.argv[1]), content_type)
    xbmcplugin.endOfDirectory(int(sys.argv[1]))

def search():
    kb = xbmcgui.Dialog().input('Keresés', type=xbmcgui.INPUT_ALPHANUM)
    if kb:
        url = "{}/search.php?q={}".format(BASE_URL, urllib.parse.quote_plus(kb))
        xbmc.executebuiltin("Container.Update({}?mode=list_html&url={})".format(sys.argv[0], urllib.parse.quote_plus(url)))

# --- LEJÁTSZÁS VEZÉRLÉS ---

def play_film(video_id):
    player_url = "{}/player.php?id={}".format(BASE_URL, video_id)
    html = get_html(player_url)
    if not html: return

    video_match = re.search(r'<source\s+src=["\']([^"\']+\.mp4)["\']', html, re.IGNORECASE)
    if not video_match: return

    video_url = video_match.group(1).replace('\\/', '/')
    if not video_url.startswith('http'):
        video_url = "{}/{}".format(BASE_URL, video_url.lstrip('/'))

    # JS változók kimentése
    start_t = int(re.search(r'var\s+start\s*=\s*(\d+);', html).group(1)) if re.search(r'var\s+start\s*=\s*(\d+);', html) else 0
    end_t = int(re.search(r'var\s+end\s*=\s*(\d+);', html).group(1)) if re.search(r'var\s+end\s*=\s*(\d+);', html) else 0

    # Fejlécek
    cookies = session.cookies.get_dict()
    cookies['fo[cookieaccept]'] = 'extra'
    cookie_str = "; ".join(["{}={}".format(k, v) for k, v in cookies.items()])
    headers = {'User-Agent': 'Mozilla/5.0...', 'Referer': player_url, 'Cookie': cookie_str}
    
    final_url = video_url + "|" + urllib.parse.urlencode(headers)
    li = xbmcgui.ListItem(path=final_url)
    xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, listitem=li)

    # Indítjuk a monitort
    monitor = FilmhiradoMonitor(start_t, end_t)
    
    # Életben tartjuk a szkriptet, amíg megy a videó
    for _ in range(60): # Max 30 mp várakozás az indulásra
        if monitor.isPlaying(): break
        xbmc.sleep(500)
    
    while monitor.isPlaying():
        if monitor.check_end(): break
        xbmc.sleep(1000)

# --- ROUTER ---

def main():
    params = dict(urllib.parse.parse_qsl(sys.argv[2].lstrip('?')))
    mode = params.get('mode')
    if not mode:
        add_dir("Legfrissebbek", "{}/search.php?new".format(BASE_URL), mode='list_html')
        add_dir("Archívum", "{}/index.php".format(BASE_URL), mode='list_json')
        xbmcplugin.addDirectoryItem(int(sys.argv[1]), sys.argv[0]+"?mode=search", xbmcgui.ListItem("[ KERESÉS ]"), False)
        finalize_directory('addons')
    elif mode == 'list_json': list_films_json(params.get('url'), int(params.get('page', 0)))
    elif mode == 'list_html': list_films_html(params.get('url'))
    elif mode == 'search': search()
    elif mode == 'play': play_film(params.get('id'))

if __name__ == '__main__':
    main()