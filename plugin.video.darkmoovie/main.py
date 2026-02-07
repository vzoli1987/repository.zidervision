import sys
import urllib.parse
import re
import time
import html
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

# --- ALAPADATOK ---
ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE_URL = "https://moovie.do.am"

try:
    import resolveurl
except ImportError:
    resolveurl = None

def build_url(query):
    return sys.argv[0] + '?' + urllib.parse.urlencode(query)

def get_html(url):
    # Fix várakozás a gyanú elkerülésére (0.5 mp)
    time.sleep(0.5) 
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0',
            'Referer': BASE_URL
        }
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        xbmc.log(f"MoovieDOAM - Hiba a letöltésnél: {str(e)}", xbmc.LOGERROR)
        return ""

def main_menu():
    add_dir("[COLOR cyan][ Keresés... ][/COLOR]", "", 'search', "DefaultAddonsSearch.png")
    
    menu_items = [
        ("Filmek (Összes)", "/load"),
        ("2025", "/index/2025/0-28"),
        ("Sikoly Filmek", "/index/sikoly_filmek/0-34"),
        ("Gyerekjáték Filmek", "/index/gyerekjatek_filmek/0-33"),
        ("Halloween Filmek", "/index/halloween_filmek/0-32"),
        ("Karácsonyi filmek", "/index/christmas_movies/0-29"),
        ("Péntek 13", "/index/pentek_13/0-31"),
        ("Rémálom az Elm utcában", "/index/a_nightmare_on_elm_street/0-30"),
        ("Coming soon", "/index/coming_soon/0-19")
    ]
    
    for name, path in menu_items:
        add_dir(name, f"{BASE_URL}{path}", 'list_movies', "DefaultVideo.png")
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_movies(url):
    html_content = get_html(url)
    matches = []

    if "/search/" in url:
        pattern_search = r'<div class="eTitle".*?href="([^"]+)">(.*?)</a>'
        search_matches = re.findall(pattern_search, html_content, re.DOTALL)
        for m_url, m_title in search_matches:
            matches.append((m_url, m_title, ""))
    else:
        pattern_wall = r'<a href="([^"]+)" target="_blank" title="([^"]+)"><img.*?src="([^"]+)"'
        matches = re.findall(pattern_wall, html_content)
        
        if not matches:
            pattern_classic = r'<div class="eTitle".*?href="([^"]+)">(.*?)</a>.*?src="([^"]+)"'
            matches = re.findall(pattern_classic, html_content, re.DOTALL)

    xbmcplugin.setContent(HANDLE, 'movies')

    seen_urls = set()
    for m_url, m_title, m_img in matches:
        if m_url in seen_urls: continue
        seen_urls.add(m_url)

        m_title = html.unescape(re.sub(r'<.*?>', '', m_title).strip())
        
        if ' / ' in m_title:
            parts = m_title.split(' / ')
            display_title = f"{parts[1].strip()} ({parts[0].strip()})"
        else:
            display_title = m_title

        full_m_img = (BASE_URL + m_img if m_img.startswith('/') else m_img) if m_img else "DefaultVideo.png"
        full_m_url = BASE_URL + m_url if m_url.startswith('/') else m_url

        li = xbmcgui.ListItem(label=display_title)
        li.setArt({'icon': full_m_img, 'thumb': full_m_img, 'poster': full_m_img, 'fanart': full_m_img})
        li.setInfo('video', {'title': display_title})
        
        params = {'mode': 'list_sources', 'url': full_m_url, 'title': display_title, 'img': full_m_img}
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=build_url(params), listitem=li, isFolder=True)

    next_page = re.findall(r'<a class="swchItem".*?href="([^"]+)"[^>]*><span>&raquo;</span></a>', html_content)
    if next_page:
        next_url = BASE_URL + next_page[0] if next_page[0].startswith('/') else next_page[0]
        add_dir("[COLOR yellow]>>> KÖVETKEZŐ OLDAL >>>[/COLOR]", next_url, 'list_movies', "DefaultVideo.png")

    xbmcplugin.endOfDirectory(HANDLE)

def list_sources(url, title, img):
    html_raw = get_html(url)
    
    # Kép és Plot kinyerése
    plot = "Nincs leírás."
    try:
        main_content = re.search(r'class="(?:eText|eMessage)".*?>(.*?)<table', html_raw, re.DOTALL)
        if main_content:
            paragraphs = re.findall(r'<p>(.*?)</p>', main_content.group(1), re.DOTALL)
            for p in paragraphs:
                clean_p = html.unescape(re.sub(r'<.*?>', '', p).strip())
                if clean_p and len(clean_p) > 30:
                    plot = clean_p
                    break
    except: pass

    # Linkek keresése
    pattern = r'<td.*?>\s*(?:<font.*?>)?(.*?)(?:</font>)?\s*</td>.*?href="([^"]+)"'
    matches = re.findall(pattern, html_raw, re.DOTALL)

    seen_links = set()
    trash_hosts = ['ucoz', 'yadro', 'counter', 'hit.ua', 'clarity.ms', 'moovie.do.am']

    for s_name, s_url in matches:
        s_url = s_url.strip().replace('\n', '').replace('\r', '')
        
        # 1. Redirector kezelése
        if "redirect?url=" in s_url:
            try:
                s_url = urllib.parse.unquote(s_url.split("url=")[1])
            except: pass

        # 2. ÜRES / CSAK FŐOLDAL LINK SZŰRÉSE (A kérésed alapján)
        parsed_url = urllib.parse.urlparse(s_url)
        path = parsed_url.path.strip('/')
        
        if not path or len(path) < 3:
            continue # Ha nincs azonosító a perjel után, átugorjuk

        # 3. Domain szűrés
        domain = parsed_url.netloc.lower()
        if any(trash in domain for trash in trash_hosts) or len(domain) < 4:
            continue

        if s_url in seen_links: continue
        seen_links.add(s_url)

        # 4. Megjelenítés
        s_name_clean = html.unescape(re.sub(r'<.*?>', '', s_name).strip())
        if not s_name_clean or len(s_name_clean) < 2:
            s_name_clean = domain.replace('www.', '').split('.')[0].capitalize() 
        
        display_name = f"{s_name_clean} - {title}"
        li = xbmcgui.ListItem(label=display_name)
        li.setArt({'icon': img, 'thumb': img, 'poster': img, 'fanart': img})
        li.setInfo('video', {'title': display_name, 'plot': plot, 'mediatype': 'movie'})
        
        li.setProperty('IsPlayable', 'true')
        params = {'mode': 'play', 'url': s_url}
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=build_url(params), listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(HANDLE)

def play_video(url):
    if not url: return
    xbmc.log(f"MoovieDOAM - Play indítása: {url}", xbmc.LOGINFO)
    
    if not resolveurl:
        xbmcgui.Dialog().notification("Hiba", "ResolveURL nincs!", xbmcgui.NOTIFICATION_ERROR, 5000)
        return

    try:
        # Tisztított hívás a logban látott hiba elkerülésére
        resolved_url = resolveurl.resolve(url)
        if resolved_url:
            li = xbmcgui.ListItem(path=resolved_url)
            xbmcplugin.setResolvedUrl(HANDLE, True, listitem=li)
        else:
            xbmc.log(f"MoovieDOAM - Sikertelen feloldás: {url}", xbmc.LOGWARNING)
            xbmcgui.Dialog().notification("ResolveURL", "Nem feloldható link.", xbmcgui.NOTIFICATION_INFO, 5000)
            xbmcplugin.setResolvedUrl(HANDLE, False, listitem=xbmcgui.ListItem())
    except Exception as e:
        xbmc.log(f"MoovieDOAM - ResolveURL hiba: {str(e)}", xbmc.LOGERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, listitem=xbmcgui.ListItem())

def add_dir(name, url, mode, icon):
    params = {'mode': mode, 'url': url}
    li = xbmcgui.ListItem(label=name)
    li.setArt({'icon': icon, 'thumb': icon})
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=build_url(params), listitem=li, isFolder=True)

def search():
    keyboard = xbmc.Keyboard('', 'Film keresése...')
    keyboard.doModal()
    if keyboard.isConfirmed():
        query = keyboard.getText()
        if query:
            search_url = f"{BASE_URL}/search/?q={urllib.parse.quote_plus(query)}&t=0"
            list_movies(search_url)

# --- ROUTER ---
params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
mode = params.get('mode')

if mode is None: main_menu()
elif mode == 'list_movies': list_movies(params.get('url'))
elif mode == 'list_sources': list_sources(params.get('url'), params.get('title', ''), params.get('img', ''))
elif mode == 'play': play_video(params.get('url'))
elif mode == 'search': search()