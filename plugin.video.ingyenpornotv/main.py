import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import requests
import re
import time

# --- Konfiguráció ---
base_url = sys.argv[0]
addon_handle = int(sys.argv[1])
args = urllib.parse.parse_qs(sys.argv[2][1:])

SITE_URL = 'https://ingyenporno.tv'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

session = requests.Session()
session.headers.update({'User-Agent': USER_AGENT, 'Referer': SITE_URL + '/'})

def build_url(query):
    return base_url + '?' + urllib.parse.urlencode(query)

def get_html(url):
    time.sleep(0.3) 
    try:
        r = session.get(url, timeout=15)
        if r.status_code == 429:
            time.sleep(5)
            r = session.get(url, timeout=15)
        return r.text
    except:
        return None

# --- Menürendszer ---

def list_main_menu():
    # 1. KERESÉS
    search_item = xbmcgui.ListItem("[COLOR cyan][B]KERESÉS[/B][/COLOR]")
    search_item.setArt({'thumb': 'DefaultAddonsSearch.png', 'icon': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'search'}), listitem=search_item, isFolder=True)
    
    # 2. NÉPSZERŰ (A beküldött forrás alapján)
    nepszeru = xbmcgui.ListItem("[COLOR orange]» NÉPSZERŰ (MA)[/COLOR]")
    nepszeru.setArt({'thumb': 'DefaultRecentlyAddedEpisodes.png'})
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list', 'url': SITE_URL + "/viewed/today/"}), listitem=nepszeru, isFolder=True)

    # 3. KATEGÓRIÁK
    kategoriak = xbmcgui.ListItem("[COLOR yellow]» PORNÓ KATEGÓRIÁK[/COLOR]")
    kategoriak.setArt({'thumb': 'DefaultSets.png'})
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list_categories'}), listitem=kategoriak, isFolder=True)

    # 4. LEGÚJABB
    ujak = xbmcgui.ListItem("[COLOR white]» LEGÚJABB VIDEÓK[/COLOR]")
    ujak.setArt({'thumb': 'DefaultVideo.png'})
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list', 'url': SITE_URL + "/recent/"}), listitem=ujak, isFolder=True)
    
    xbmcplugin.endOfDirectory(addon_handle)

def search():
    kb = xbmc.Keyboard('', 'Pornó keresés...')
    kb.doModal()
    if kb.isConfirmed() and kb.getText():
        s_url = f"{SITE_URL}/kereses/?s={urllib.parse.quote_plus(kb.getText())}"
        list_videos(s_url)

def list_categories():
    html = get_html(SITE_URL + "/categories/")
    if not html: return
    
    # Kategória minta a dv1/dv2 struktúrához
    cat_pattern = re.compile(r'href="(/[^"]+/)".*?class="dv1">([^<]+)<span class="dv2">\((\d+)\)</span>', re.DOTALL)
    for path, name, count in cat_pattern.findall(html):
        # Kiszűrjük a menüpontokat a kategória listából
        if any(x in path for x in ['recent', 'viewed', 'kereses', 'categories']): continue
        
        u = build_url({'mode': 'list', 'url': SITE_URL + path})
        li = xbmcgui.ListItem(f"• {name.strip()} [COLOR gray]({count})[/COLOR]")
        li.setArt({'thumb': 'DefaultSets.png'})
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=u, listitem=li, isFolder=True)
        
    xbmcplugin.endOfDirectory(addon_handle)

def list_videos(page_url):
    html = get_html(page_url)
    if not html: return
    xbmcplugin.setContent(addon_handle, 'videos')
    
    # Videó lista Regex - a beküldött forráskód alapján optimalizálva
    pattern = re.compile(r'id="video-(\d+)".*?href="([^"]+)".*?title="([^"]+)".*?src="([^"]+)".*?<span>(\d+:\d+)</span>', re.DOTALL)
    
    for v_id, v_url, title, thumb, dur in pattern.findall(html):
        full_v_url = v_url if v_url.startswith('http') else SITE_URL + v_url
        full_thumb = thumb if thumb.startswith('http') else SITE_URL + thumb
        title = title.replace('&amp;', '&').replace('&#8211;', '-').strip()
        
        li = xbmcgui.ListItem(f"[COLOR yellow][{dur}][/COLOR] {title}")
        li.setArt({'thumb': full_thumb, 'poster': full_thumb, 'fanart': full_thumb})
        li.getVideoInfoTag().setTitle(title)
        li.setProperty('IsPlayable', 'true')
        
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'play', 'url': full_v_url}), listitem=li, isFolder=False)

    # LAPOZÓ - Kifejezetten a beküldött class="next" alapján
    next_match = re.search(r'<li><a\s+href="([^"]+)"\s+class="next">', html)
    if next_match:
        next_url = next_match.group(1)
        if next_url.startswith('/'):
            next_url = SITE_URL + next_url
            
        li_next = xbmcgui.ListItem("[COLOR cyan][B]>>> KÖVETKEZŐ OLDAL >>>[/B][/COLOR]")
        li_next.setArt({'thumb': 'DefaultVideoFolder.png'})
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list', 'url': next_url}), listitem=li_next, isFolder=True)

    xbmcplugin.endOfDirectory(addon_handle)

def play_video(url):
    xbmc.log(f"[IngyenPorno] Adatlap betöltése: {url}", xbmc.LOGINFO)
    html = get_html(url)
    if not html: return
    
    # 1. Embed URL keresése
    embed_match = re.search(r'iframe.*?src=["\']([^"\']+/embed/\d+)', html)
    if not embed_match: return
    
    embed_url = embed_match.group(1)
    if embed_url.startswith('//'): embed_url = 'https:' + embed_url
    
    # 2. Embed oldal betöltése
    embed_html = get_html(embed_url)
    if not embed_html: return
    
    # Sütik kinyerése
    cookie_str = "; ".join([f"{c.name}={c.value}" for c in session.cookies])

    # 3. Videó URL keresése - Szuper-rugalmas verzió
    # Keressük a video_url utáni első idézőjelek közötti részt, ami http-vel kezdődik és mp4-re végződik
    video_url = None
    
    # Próbálkozás 1: JavaScript változó keresése (flashvars stílus)
    js_match = re.search(r"video_url['\"]\s*:\s*['\"](?:function/\d+/)?(https?://[^'\"]+\.mp4[^'\"]*)['\"]", embed_html)
    if js_match:
        video_url = js_match.group(1)
    
    # Próbálkozás 2: Ha az 1. nem ment, keressünk bármilyen MP4 linket a forrásban
    if not video_url:
        any_mp4 = re.search(r"['\"](https?://[^'\"]+\.mp4[^'\"]*)['\"]", embed_html)
        if any_mp4:
            video_url = any_mp4.group(1)

    if video_url:
        # Tisztítás (ha maradtak volna benne escape karakterek)
        video_url = video_url.replace('\\/', '/')
        
        headers = {
            'User-Agent': USER_AGENT,
            'Referer': embed_url,
            'Cookie': cookie_str,
            'Accept': '*/*'
        }
        
        play_path = video_url + '|' + urllib.parse.urlencode(headers)
        xbmc.log(f"[IngyenPorno] Sikeres URL kinyerés: {video_url}", xbmc.LOGINFO)
        
        li = xbmcgui.ListItem(path=play_path)
        xbmcplugin.setResolvedUrl(addon_handle, True, listitem=li)
    else:
        xbmc.log(f"[IngyenPorno] URL hiba! Embed forrás eleje: {embed_html[:500]}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Hiba", "Nem található a videó forrása", xbmcgui.NOTIFICATION_ERROR)

def main():
    mode = args.get('mode', [None])[0]
    if not mode: list_main_menu()
    elif mode == 'list_categories': list_categories()
    elif mode == 'search': search()
    elif mode == 'list': list_videos(args['url'][0])
    elif mode == 'play': play_video(args['url'][0])

if __name__ == '__main__':
    main()