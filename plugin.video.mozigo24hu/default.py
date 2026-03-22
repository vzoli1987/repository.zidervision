# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcplugin, xbmcaddon  # ← xbmcaddon hozzáadva!
import requests, re, json, sys, time, html
from urllib.parse import urlencode, parse_qsl

try:
    import resolveurl
except ImportError:
    resolveurl = None

ADDON_HANDLE = int(sys.argv[1])
BASE_URL = "https://mozigo24.hu"
ADDON_ID = "plugin.video.mozigo24hu"  # ← Egyezzen az addon.xml ID-val!

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
        """Cookie-k betöltése Kodi beállításokból."""
        cf_clearance = xbmcaddon.Addon(ADDON_ID).getSetting('cf_clearance')
        mozigo_session = xbmcaddon.Addon(ADDON_ID).getSetting('mozigo_session')
        xsrf_token = xbmcaddon.Addon(ADDON_ID).getSetting('xsrf_token')
        
        if cf_clearance:
            self.session.cookies.set('cf_clearance', cf_clearance, domain='.mozigo24.hu')
        if mozigo_session:
            self.session.cookies.set('mozigo_session', mozigo_session, domain='.mozigo24.hu')
        if xsrf_token:
            self.session.cookies.set('XSRF-TOKEN', xsrf_token, domain='.mozigo24.hu')
            self.session.headers.update({'X-XSRF-TOKEN': xsrf_token})

    def ensure_session(self):
        """Munkamenet frissítése ha szükséges."""
        try:
            r = self.session.get(BASE_URL, timeout=10)
            # Cookie-k frissítése a válaszból
            for cookie in self.session.cookies:
                if cookie.name in ['cf_clearance', 'mozigo_session', 'XSRF-TOKEN']:
                    xbmcaddon.Addon(ADDON_ID).setSetting(cookie.name, cookie.value)
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
    # None értékek kiszűrése
    clean_query = {k: v for k, v in query.items() if v is not None and v != ''}
    return sys.argv[0] + '?' + urlencode(clean_query)

def main_menu():
    items = [
        ("[COLOR orange]KERESÉS...[/COLOR]", {'action': 'search'}),
        ("[COLOR cyan] KATEGÓRIÁK[/COLOR]", {'action': 'genres'}),
        ("[COLOR yellow]  ÖSSZES FILM[/COLOR]", {'action': 'list', 'page': '1'})
    ]
    for label, query in items:
        xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=build_url(query), listitem=xbmcgui.ListItem(label), isFolder=True)
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

_genre_cache = None
_genre_cache_time = 0

def list_genres():
    global _genre_cache, _genre_cache_time
    import time
    
    xbmcplugin.setContent(ADDON_HANDLE, 'genres')
    
    try:
        # ✅ CACHE ELLENŐRZÉS (24 óra)
        if _genre_cache and (time.time() - _genre_cache_time) < 86400:
            genres = _genre_cache
            xbmc.log("Mozigo24: Genre cache HIT", xbmc.LOGDEBUG)
        else:
            data = client.get_api(f"{BASE_URL}/api/genre-list", params={'page': '1', 'is_ajax': '1', 'per_page': '30'})
            html_content = data.get('html', '')
            pattern = r'genre/(\d+)"[^>]*>.*?geners-title[^>]*>\s*([^<]+)'
            genres = re.findall(pattern, html_content, re.DOTALL)
            
            # ✅ ABC RENDEZÉS
            genres.sort(key=lambda x: clean_text(x[1]).lower())
            
            _genre_cache = genres
            _genre_cache_time = time.time()
            xbmc.log("Mozigo24: Genre cache MISS - frissítve", xbmc.LOGDEBUG)
        
        for g_id, g_name in genres:
            name = clean_text(g_name)
            li = xbmcgui.ListItem(label=name)
            u = build_url({'action': 'list', 'genre': g_id, 'page': '1'})
            xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=u, listitem=li, isFolder=True)
        
        # ✅ KODI RENDEZÉS BEKAPCSOLÁSA
        xbmcplugin.addSortMethod(ADDON_HANDLE, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
        
    except Exception as e:
        xbmc.log(f"Mozigo24 Genres Error: {str(e)}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Hiba", "Kategóriák betöltése sikertelen", xbmcgui.NOTIFICATION_ERROR, 2000)
        
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_movies(page=1, query=None, genre=None):
    # ⚠️ FONTOS: setContent AZ ELEJÉN!
    xbmcplugin.setContent(ADDON_HANDLE, 'movies')
    
    try:
        # Page explicit konverzió
        page = str(int(page)) if page else '1'
        
        params = {'page': page, 'is_ajax': '1', 'per_page': '24'}
        
        if query:
            url = f"{BASE_URL}/api/v3/get-search-data"
            params['search'] = query
        elif genre:
            url = f"{BASE_URL}/api/genre-content-list"
            params.update({'genre_id': str(genre), 'type': 'both'})
        else:
            url = f"{BASE_URL}/api/v3/movie-list"

        xbmc.log(f"Mozigo24 API Call: {url} | Page: {page} | Genre: {genre} | Query: {query}", xbmc.LOGINFO)
        
        data = client.get_api(url, params=params)
        raw_html = data.get('html', '')
        
        if not raw_html:
            xbmcgui.Dialog().notification("Mozigo24", "Nincs több tartalom", xbmcgui.NOTIFICATION_WARNING, 2000)
            xbmcplugin.endOfDirectory(ADDON_HANDLE)
            return
        
        clean_html = html.unescape(raw_html)
        movies_data = re.findall(r'data-movie-data="({.*?})"', clean_html)
        
        xbmc.log(f"Mozigo24: Oldal: {page}, Talált filmek: {len(movies_data)}", xbmc.LOGINFO)

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
                
                if d.get('release_date'):
                    try: v.setYear(int(d.get('release_date')[:4]))
                    except: pass
                if d.get('imdb_rating'):
                    try: v.setRating(float(d.get('imdb_rating')), 'imdb')
                    except: pass

                li.setProperty('IsPlayable', 'true')
                u = build_url({'action': 'play', 'video_url': f"{BASE_URL}/film/{slug}"})
                xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=u, listitem=li, isFolder=False)
                
            except Exception as e:
                xbmc.log(f"Mozigo24 JSON hiba: {str(e)}", xbmc.LOGDEBUG)
                continue
            
        # Lapozás - csak ha van elég találat
        if len(movies_data) >= 20:
            next_page = int(page) + 1
            nq = {'action': 'list', 'page': str(next_page)}
            if genre: nq['genre'] = str(genre)
            if query: nq['query'] = query
            
            xbmc.log(f"Mozigo24: Következő oldal hozzáadva: {next_page}", xbmc.LOGINFO)
            
            xbmcplugin.addDirectoryItem(
                handle=ADDON_HANDLE, 
                url=build_url(nq), 
                listitem=xbmcgui.ListItem(f"[COLOR yellow]>>> KÖVETKEZŐ OLDAL ({next_page})[/COLOR]"), 
                isFolder=True
            )
            
    except Exception as e:
        xbmc.log(f"Mozigo24 Kritikus hiba: {str(e)}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Hiba", str(e), xbmcgui.NOTIFICATION_ERROR, 3000)
        
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def play_video(movie_url):
    try:
        client.ensure_session()
        r = client.session.get(movie_url, timeout=10)
        token_match = re.search(r'data-video-url="([^"]+)"', r.text)
        
        if not token_match:
            xbmcgui.Dialog().ok("Hiba", "Nem található video token!")
            xbmcplugin.setResolvedUrl(ADDON_HANDLE, False)
            return
            
        token = token_match.group(1)
        stream_data = client.get_api(f"{BASE_URL}/video/stream/{token}")
        iframe_url = stream_data.get('url')
        
        if iframe_url.startswith('//'): iframe_url = 'https:' + iframe_url

        if resolveurl:
            hmf = resolveurl.HostedMediaFile(iframe_url)
            resolved = hmf.resolve()
            if resolved:
                host = hmf.get_host() or "Ismeretlen"
                xbmcgui.Dialog().notification("Mozigo24", f"Szerver: [COLOR green]{host.capitalize()}[/COLOR]", xbmcgui.NOTIFICATION_INFO, 2500)
                li = xbmcgui.ListItem(path=resolved)
                xbmcplugin.setResolvedUrl(ADDON_HANDLE, True, listitem=li)
                return

        xbmcgui.Dialog().ok("Hiba", "Szerver nem támogatott vagy a fájl törölve.")
        xbmcplugin.setResolvedUrl(ADDON_HANDLE, False)
    except Exception as e:
        xbmc.log(f"Play error: {str(e)}", xbmc.LOGERROR)
        xbmcplugin.setResolvedUrl(ADDON_HANDLE, False)

if __name__ == '__main__':
    p = dict(parse_qsl(sys.argv[2][1:]))
    a = p.get('action')
    if not a: main_menu()
    elif a == 'genres': list_genres()
    elif a == 'search':
        kb = xbmc.Keyboard('', 'Film keresése...')
        kb.doModal()
        if kb.isConfirmed() and kb.getText(): list_movies(query=kb.getText())
    elif a == 'list': 
        list_movies(
            page=p.get('page', '1'), 
            genre=p.get('genre'), 
            query=p.get('query')
        )
    elif a == 'play': play_video(p.get('video_url'))