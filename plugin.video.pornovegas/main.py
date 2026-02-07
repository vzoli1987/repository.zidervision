import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import requests
import re
import xbmc

# --- Konfiguráció ---
base_url = sys.argv[0]
addon_handle = int(sys.argv[1])

SITE_URL = 'https://porno.vegas'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

session = requests.Session()
session.headers.update({'User-Agent': USER_AGENT})

def build_url(query):
    return base_url + '?' + urllib.parse.urlencode(query)

def get_html(url, referer=None):
    headers = {'Referer': referer} if referer else {}
    try:
        r = session.get(url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        return r.text
    except:
        return None

# --- Menürendszer ---

def list_main_menu():
    # 1. KERESÉS
    li = xbmcgui.ListItem("[COLOR cyan][B]KERESÉS[/B][/COLOR]")
    li.setArt({'thumb': 'DefaultAddonsSearch.png', 'icon': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'search'}), listitem=li, isFolder=True)
    
    # 2. LEGÚJABB
    li = xbmcgui.ListItem("[COLOR white]» LEGÚJABB VIDEÓK[/COLOR]")
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list', 'url': SITE_URL + "/recent/"}), listitem=li, isFolder=True)

    # 3. NÉPSZERŰ
    li = xbmcgui.ListItem("[COLOR orange]» NÉPSZERŰ (MA)[/COLOR]")
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list', 'url': SITE_URL + "/viewed/today/"}), listitem=li, isFolder=True)

    # 4. KATEGÓRIÁK
    li = xbmcgui.ListItem("[COLOR yellow]» PORNÓ KATEGÓRIÁK[/COLOR]")
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list_categories'}), listitem=li, isFolder=True)
    
    xbmcplugin.endOfDirectory(addon_handle)

def list_categories():
    html = get_html(SITE_URL + "/categories/", referer=SITE_URL)
    if not html:
        return

    # A beküldött HTML struktúrához igazított pontos Regex:
    # <a class="categLink" href="([^"]+)" title="([^"]+)"><div class="categMenu">.*?<span>\((\d+)\)</span>
    cat_pattern = re.compile(r'class="categLink"\s+href="([^"]+)"\s+title="([^"]+)".*?class="categMenu">([^<]+)<span>\((\d+)\)</span>', re.DOTALL)
    
    results = cat_pattern.findall(html)
    
    for path, title_attr, title_text, count in results:
        full_cat_url = SITE_URL + path if not path.startswith('http') else path
        
        # Tisztítsuk meg a nevet a felesleges szóközöktől
        display_name = title_text.strip()
        
        # Megjelenítés: Név (darabszám)
        li = xbmcgui.ListItem(f"[COLOR yellow]{display_name}[/COLOR] [COLOR gray]({count})[/COLOR]")
        
        # Mivel ebben a nézetben nincsenek egyedi képek, az alap kategória ikont használjuk
        li.setArt({'icon': 'DefaultVideos.png', 'thumb': 'DefaultVideos.png'})
        
        u = build_url({'mode': 'list', 'url': full_cat_url})
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=u, listitem=li, isFolder=True)
        
    xbmcplugin.endOfDirectory(addon_handle)

def list_videos(page_url):
    html = get_html(page_url, referer=SITE_URL)
    if not html: return
    xbmcplugin.setContent(addon_handle, 'videos')
    
    pattern = re.compile(r'<li id="video-(\d+)".*?href="([^"]+)".*?title="([^"]+)".*?src="([^"]+)"', re.DOTALL)
    
    for v_id, v_url, title, thumb in pattern.findall(html):
        full_v_url = v_url if v_url.startswith('http') else SITE_URL + v_url
        full_thumb = thumb if thumb.startswith('http') else SITE_URL + thumb
        if full_thumb.startswith('//'): full_thumb = 'https:' + full_thumb
        
        li = xbmcgui.ListItem(title)
        li.setArt({'thumb': full_thumb, 'icon': full_thumb})
        li.setInfo('video', {'title': title})
        li.setProperty('IsPlayable', 'true')
        
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'play', 'url': full_v_url}), listitem=li, isFolder=False)

    next_match = re.search(r'href="([^"]+)"\s+class="next"', html)
    if next_match:
        next_url = next_match.group(1)
        if not next_url.startswith('http'): 
            next_url = SITE_URL + next_url
        li_next = xbmcgui.ListItem("[COLOR cyan][B]>>> KÖVETKEZŐ OLDAL >>>[/B][/COLOR]")
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list', 'url': next_url}), listitem=li_next, isFolder=True)

    xbmcplugin.endOfDirectory(addon_handle)

def search():
    kb = xbmc.Keyboard('', 'Keresés a Vegas-on...')
    kb.doModal()
    if kb.isConfirmed() and kb.getText():
        search_term = kb.getText()
        search_url = f"{SITE_URL}/kereses/?s={urllib.parse.quote_plus(search_term)}"
        list_videos(search_url)
    else:
        xbmcplugin.endOfDirectory(addon_handle, cacheToDisc=False)

def play_video(url):
    html = get_html(url, referer=SITE_URL)
    if not html: return
    
    embed_match = re.search(r'iframe.*?src=["\']([^"\']+/embed/\d+)', html)
    if not embed_match: return
    
    embed_url = embed_match.group(1)
    if embed_url.startswith('//'): embed_url = 'https:' + embed_url
    
    embed_html = get_html(embed_url, referer=url)
    if not embed_html: return
    
    video_url = None
    js_match = re.search(r"video_url\s*:\s*'([^']+)'", embed_html)
    if js_match:
        video_url = js_match.group(1).replace('\\/', '/')
    
    if not video_url:
        src_match = re.search(r'<source.*?src=["\']([^"\']+\.mp4[^"\']*)["\']', embed_html)
        if src_match: video_url = src_match.group(1)

    if video_url:
        if video_url.startswith('//'): video_url = 'https:' + video_url
        domain = urllib.parse.urlparse(embed_url).netloc
        cookie_dict = session.cookies.get_dict(domain=domain)
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        headers = {'User-Agent': USER_AGENT, 'Referer': embed_url, 'Cookie': cookie_str}
        
        play_path = video_url + '|' + urllib.parse.urlencode(headers)
        li = xbmcgui.ListItem(path=play_path)
        xbmcplugin.setResolvedUrl(addon_handle, True, listitem=li)

def main():
    paramstring = sys.argv[2]
    params = dict(urllib.parse.parse_qsl(paramstring.lstrip('?')))
    
    mode = params.get('mode')
    url = params.get('url')

    if not mode:
        list_main_menu()
    elif mode == 'search':
        search()
    elif mode == 'list':
        list_videos(url)
    elif mode == 'list_categories':
        list_categories()
    elif mode == 'play':
        play_video(url)

if __name__ == '__main__':
    main()