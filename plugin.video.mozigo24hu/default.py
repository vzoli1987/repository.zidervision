# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcplugin, xbmcaddon
import requests, re, json, sys, time, html
from urllib.parse import urlencode, parse_qsl

try:
    import resolveurl
except ImportError:
    resolveurl = None

ADDON_HANDLE = int(sys.argv[1])
BASE_URL = "https://mozigo24.hu"
ADDON_ID = "plugin.video.mozigo24hu"

class MozigoClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0',
            'X-Requested-With': 'XMLHttpRequest',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Referer': f'{BASE_URL}/',
            'Accept-Language': 'hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7'
        })
        self._load_cookies()

    def _load_cookies(self):
        try:
            addon = xbmcaddon.Addon(ADDON_ID)
            for key in ['cf_clearance', 'mozigo_session', 'xsrf_token']:
                val = addon.getSetting(key)
                if val:
                    cookie_name = 'XSRF-TOKEN' if key == 'xsrf_token' else key
                    self.session.cookies.set(cookie_name, val, domain='.mozigo24.hu')
                    if key == 'xsrf_token':
                        self.session.headers.update({'X-XSRF-TOKEN': val})
        except: pass

    def ensure_session(self):
        try:
            r = self.session.get(BASE_URL, timeout=10)
            addon = xbmcaddon.Addon(ADDON_ID)
            for cookie in self.session.cookies:
                if cookie.name in ['cf_clearance', 'mozigo_session', 'XSRF-TOKEN']:
                    setting_name = 'xsrf_token' if cookie.name == 'XSRF-TOKEN' else cookie.name
                    addon.setSetting(setting_name, cookie.value)
        except: pass

    def get_api(self, url, params=None):
        self.ensure_session()
        time.sleep(0.3)
        r = self.session.get(url, params=params, timeout=15)
        return r.json()

client = MozigoClient()

def clean_text(text):
    if not text: return ""
    return html.unescape(re.sub(r'<[^>]+>', '', text)).strip()

def build_url(query):
    clean_query = {k: v for k, v in query.items() if v is not None and v != ''}
    return sys.argv[0] + '?' + urlencode(clean_query)

def main_menu():
    items = [
        ("[COLOR orange]🔍 KERESÉS...[/COLOR]", {'action': 'search'}),
        ("[COLOR cyan]📁 KATEGÓRIÁK[/COLOR]", {'action': 'genres'}),
        ("[COLOR yellow]🎬 ÖSSZES FILM[/COLOR]", {'action': 'list', 'page': '1'})
    ]
    for label, query in items:
        xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=build_url(query), listitem=xbmcgui.ListItem(label), isFolder=True)
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

_genre_cache = None
_genre_cache_time = 0

def list_genres():
    global _genre_cache, _genre_cache_time
    xbmcplugin.setContent(ADDON_HANDLE, 'genres')
    try:
        if _genre_cache and (time.time() - _genre_cache_time) < 86400:
            genres = _genre_cache
        else:
            data = client.get_api(f"{BASE_URL}/api/genre-list", params={'page': '1', 'is_ajax': '1', 'per_page': '30'})
            html_content = data.get('html', '')
            genres = re.findall(r'genre/(\d+)"[^>]*>.*?geners-title[^>]*>\s*([^<]+)', html_content, re.DOTALL)
            genres.sort(key=lambda x: clean_text(x[1]).lower())
            _genre_cache = genres
            _genre_cache_time = time.time()
        
        for g_id, g_name in genres:
            li = xbmcgui.ListItem(label=clean_text(g_name))
            u = build_url({'action': 'list', 'genre': g_id, 'page': '1'})
            xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=u, listitem=li, isFolder=True)
        xbmcplugin.addSortMethod(ADDON_HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    except Exception as e:
        xbmc.log(f"Mozigo24 Genres Error: {str(e)}", xbmc.LOGERROR)
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_movies(page=1, query=None, genre=None):
    xbmcplugin.setContent(ADDON_HANDLE, 'movies')
    try:
        page = str(int(page))
        params = {'page': page, 'is_ajax': '1', 'per_page': '24'}
        if query:
            url = f"{BASE_URL}/api/v3/get-search-data"
            params['search'] = query
        elif genre:
            url = f"{BASE_URL}/api/genre-content-list"
            params.update({'genre_id': str(genre), 'type': 'both'})
        else:
            url = f"{BASE_URL}/api/v3/movie-list"

        data = client.get_api(url, params=params)
        raw_html = data.get('html', '')
        if not raw_html:
            xbmcplugin.endOfDirectory(ADDON_HANDLE)
            return
        
        movies_data = re.findall(r'data-movie-data="({.*?})"', html.unescape(raw_html))
        for m_json in movies_data:
            try:
                d = json.loads(m_json)
                title = clean_text(d.get('name', 'Ismeretlen'))
                slug = d.get('slug')
                if not slug: continue
                li = xbmcgui.ListItem(label=title)
                img = d.get('poster_image', '')
                li.setArt({'thumb': img, 'poster': img, 'fanart': img})
                v = li.getVideoInfoTag()
                v.setTitle(title)
                v.setPlot(clean_text(d.get('description', '')))
                v.setMediaType('movie')
                li.setProperty('IsPlayable', 'true')
                u = build_url({'action': 'play', 'video_url': f"{BASE_URL}/watch/{slug}.html"})
                xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=u, listitem=li, isFolder=False)
            except: continue
            
        if len(movies_data) >= 20:
            nq = {'action': 'list', 'page': str(int(page) + 1)}
            if genre: nq['genre'] = str(genre)
            if query: nq['query'] = query
            xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=build_url(nq), listitem=xbmcgui.ListItem("[COLOR yellow]>>> KÖVETKEZŐ OLDAL[/COLOR]"), isFolder=True)
    except Exception as e:
        xbmc.log(f"Mozigo24 Movie List Error: {str(e)}", xbmc.LOGERROR)
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def play_video(movie_url):
    try:
        client.ensure_session()
        r = client.session.get(movie_url, timeout=10)
        token_match = re.search(r'data-video-url="([^"]+)"', r.text)
        
        if not token_match:
            xbmcgui.Dialog().ok("Hiba", "Nem található video token!")
            xbmcplugin.setResolvedUrl(ADDON_HANDLE, False, listitem=xbmcgui.ListItem())
            return
            
        token = token_match.group(1)
        stream_data = client.get_api(f"{BASE_URL}/video/stream/{token}")
        iframe_url = stream_data.get('url')
        if not iframe_url:
            xbmcgui.Dialog().ok("Hiba", "Nem sikerült lekérni a stream URL-t!")
            xbmcplugin.setResolvedUrl(ADDON_HANDLE, False, listitem=xbmcgui.ListItem())
            return

        if iframe_url.startswith('//'): iframe_url = 'https:' + iframe_url
        
        # Videa linkek speciális kezelése
        if 'videa.hu' in iframe_url:
            # Ha 'f=' paraméter van benne, meg kell keresnünk a valódi videó azonosítót (vcode)
            if 'f=' in iframe_url and 'v=' not in iframe_url:
                try:
                    player_page = requests.get(iframe_url, timeout=10).text
                    vcode_match = re.search(r'var vcode = "([^"]+)"', player_page)
                    if vcode_match:
                        iframe_url = f"https://videa.hu/player?v={vcode_match.group(1)}"
                except: pass

        if resolveurl:
            hmf = resolveurl.HostedMediaFile(iframe_url)
            resolved = hmf.resolve()
            if resolved:
                li = xbmcgui.ListItem(path=resolved)
                xbmcplugin.setResolvedUrl(ADDON_HANDLE, True, listitem=li)
                return

        xbmcgui.Dialog().ok("Hiba", "Szerver nem támogatott vagy feloldási hiba.\nURL: " + iframe_url)
        xbmcplugin.setResolvedUrl(ADDON_HANDLE, False, listitem=xbmcgui.ListItem())
    except Exception as e:
        xbmc.log(f"Mozigo24 Play Error: {str(e)}", xbmc.LOGERROR)
        xbmcplugin.setResolvedUrl(ADDON_HANDLE, False, listitem=xbmcgui.ListItem())

if __name__ == '__main__':
    p = dict(parse_qsl(sys.argv[2][1:]))
    a = p.get('action')
    if not a: main_menu()
    elif a == 'genres': list_genres()
    elif a == 'search':
        kb = xbmc.Keyboard('', 'Film keresése...')
        kb.doModal()
        if kb.isConfirmed() and kb.getText(): list_movies(query=kb.getText())
    elif a == 'list': list_movies(page=p.get('page', '1'), genre=p.get('genre'), query=p.get('query'))
    elif a == 'play': play_video(p.get('video_url'))