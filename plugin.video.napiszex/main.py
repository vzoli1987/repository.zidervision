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

# Biztonságos paraméter beolvasás
try:
    # A [1:] levágja a '?' jelet az elejéről
    args = urllib.parse.parse_qs(sys.argv[2][1:])
except:
    args = {}

SITE_URL = 'https://napiszex.com'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0'

# Session beállítása a Referer és User-Agent fixálására
session = requests.Session()
session.headers.update({'User-Agent': USER_AGENT, 'Referer': SITE_URL + '/'})

def build_url(query):
    return base_url + '?' + urllib.parse.urlencode(query)

def get_html(url):
    """Szigorított letöltés 429-es védelemmel és fix várakozással."""
    # Fix várakozás a korábbi instrukciód alapján a feltűnésmentes működésért
    time.sleep(0.5) 
    
    for i in range(3): # 3 próbálkozás hiba esetén
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                return r.text
            elif r.status_code == 429:
                wait_time = (i + 1) * 2
                xbmc.log(f"Napiszex: 429 hiba, várakozás {wait_time}mp...", xbmc.LOGINFO)
                time.sleep(wait_time)
                continue
            else:
                return None
        except:
            return None
    return None

# --- Menürendszer ---

def list_main_menu():
    # 1. KERESÉS
    search_item = xbmcgui.ListItem("[COLOR cyan][B]KERESÉS[/B][/COLOR]")
    search_item.setArt({'thumb': 'DefaultAddonsSearch.png', 'icon': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'search'}), 
                                listitem=search_item, isFolder=True)
    
    # Kategóriák, Válogatás, stb. (a többi marad az eredeti)
    add_menu_item("[COLOR yellow]» KATEGÓRIÁK[/COLOR]", 'list_categories', 'DefaultSets.png')
    add_menu_item("[COLOR fuchsia]» NAPISZEX VÁLOGATÁS[/COLOR]", 'list', 'DefaultAddonService.png', SITE_URL + "/napiszex")
    add_menu_item("[COLOR orange]» NÉPSZERŰ VIDEÓK[/COLOR]", 'list', 'DefaultRecentlyAddedEpisodes.png', SITE_URL + "/nepszeru")
    add_menu_item("[COLOR white]» ÚJ SZEXVIDEÓK[/COLOR]", 'list', 'DefaultVideo.png', SITE_URL + "/szexfilmek")
    
    xbmcplugin.endOfDirectory(addon_handle)

def add_menu_item(label, mode, icon, url=None):
    params = {'mode': mode}
    if url: params['url'] = url
    li = xbmcgui.ListItem(label)
    li.setArt({'thumb': icon, 'icon': icon})
    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url(params), listitem=li, isFolder=True)

def search():
    """Keresés javított paraméterezéssel a Router számára."""
    kb = xbmcgui.Dialog().input('Keresés...', type=xbmcgui.INPUT_ALPHANUM)
    if kb:
        query = urllib.parse.quote_plus(kb)
        # Itt a trükk: a keresési URL-t úgy adjuk át, mintha egy kategória lenne
        s_url = f"{SITE_URL}/search/videos?search_query={query}"
        
        # Frissítjük a referert
        session.headers.update({'Referer': f"{SITE_URL}/search/videos"})
        
        # Meghívjuk a listázást
        list_videos(s_url)

def list_categories():
    html = get_html(SITE_URL + "/categories")
    if not html: return
    cat_pattern = re.compile(r'href="(/szexfilmek/[^"]+)">.*?title-truncate">\s*(.*?)\s*</div>.*?badge">(\d+)</span>', re.DOTALL)
    for path, name, count in cat_pattern.findall(html):
        u = build_url({'mode': 'list', 'url': SITE_URL + path})
        li = xbmcgui.ListItem(f"• {name.strip()} [COLOR gray]({count})[/COLOR]")
        li.setArt({'thumb': 'DefaultSets.png', 'icon': 'DefaultSets.png'})
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=u, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(addon_handle)

def list_videos(page_url):
    html = get_html(page_url)
    if not html: 
        xbmcplugin.endOfDirectory(addon_handle)
        return

    # Ellenőrzés: Van-e találat?
    if "Nincs találat" in html or "No results found" in html:
        xbmcgui.Dialog().notification('Napiszex', 'Nincs találat!', xbmcgui.NOTIFICATION_INFO, 3000)
        xbmcplugin.endOfDirectory(addon_handle)
        return

    xbmcplugin.setContent(addon_handle, 'videos')
    pattern = re.compile(r'well-sm npszThumb">.*?<a href="(.*?)".*?<img.*?src="(.*?)".*?title="(.*?)".*?class="duration">\s*(.*?)\s*</div>', re.DOTALL)
    
    valid_videos = pattern.findall(html)
    for v_url, thumb, title, dur in valid_videos:
        full_v_url = SITE_URL + v_url if v_url.startswith('/') else v_url
        full_thumb = SITE_URL + thumb if not thumb.startswith('http') else thumb
        title = title.replace('&amp;', '&').replace('&#8211;', '-').strip()
        li = xbmcgui.ListItem(f"[COLOR yellow][{dur.strip()}][/COLOR] {title}")
        li.setArt({'thumb': full_thumb, 'icon': full_thumb})
        li.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'play', 'url': full_v_url}), listitem=li, isFolder=False)

    # --- SZIGORÍTOTT LAPOZÓ ---
    if valid_videos:
        pagination_links = re.findall(r'<li><a\s+href="([^"]+)"[^>]*>(.*?)</a></li>', html, re.DOTALL)
        for link_url, link_text in pagination_links:
            if any(x in link_text for x in ['Következő', 'Next', '»']):
                next_url = SITE_URL + link_url if link_url.startswith('/') else link_url
                
                # Összehasonlítás az aktuálissal (végtelen ciklus ellen)
                if next_url.rstrip('/') != page_url.rstrip('/'):
                    num_match = re.search(r'page=(\d+)', next_url)
                    p_num = num_match.group(1) if num_match else ">"
                    li_next = xbmcgui.ListItem(f"[COLOR cyan][B]>>> KÖVETKEZŐ OLDAL ({p_num}) >>>[/B][/COLOR]")
                    xbmcplugin.addDirectoryItem(handle=addon_handle, url=build_url({'mode': 'list', 'url': next_url}), listitem=li_next, isFolder=True)
                break
    
    xbmcplugin.endOfDirectory(addon_handle)

def play_video(url):
    html = get_html(url)
    if not html: return
    match = re.search(r'<source\s+src=["\'](https?://[^"\']+\.mp4)["\']', html)
    if match:
        play_path = match.group(1) + f"|User-Agent={urllib.parse.quote(USER_AGENT)}&Referer={urllib.parse.quote(url)}"
        xbmcplugin.setResolvedUrl(addon_handle, True, listitem=xbmcgui.ListItem(path=play_path))

def main():
    # Biztonságos mód beolvasás
    mode = args.get('mode', [None])[0]
    
    if not mode:
        list_main_menu()
    elif mode == 'list_categories':
        list_categories()
    elif mode == 'search':
        search()
    elif mode == 'list':
        # Csak akkor hívjuk meg, ha van URL, különben visszadob a főmenübe
        url = args.get('url', [None])[0]
        if url:
            list_videos(url)
        else:
            list_main_menu()
    elif mode == 'play':
        url = args.get('url', [None])[0]
        if url:
            play_video(url)

if __name__ == '__main__':
    main()