import sys
import urllib.parse
import requests
from bs4 import BeautifulSoup
import xbmcgui
import xbmcplugin
import xbmc

# --- Alapbeállítások ---
BASE_URL = 'https://porno1.hu'
syshandle = int(sys.argv[1])

def get_html(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:146.0) Gecko/20100101 Firefox/146.0'
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'utf-8'
        return r.text
    except:
        return None

def endDirectory(content_type='videos'):
    xbmcplugin.setContent(syshandle, content_type)
    xbmcplugin.endOfDirectory(syshandle, succeeded=True, cacheToDisc=True)

def add_directory_item(name, params, is_folder=True, thumb='', info=None):
    url = f"{sys.argv[0]}?{urllib.parse.urlencode(params)}"
    list_item = xbmcgui.ListItem(label=name)
    if thumb:
        list_item.setArt({'thumb': thumb, 'icon': thumb})
    if info:
        list_item.setInfo('video', info)
    if not is_folder:
        list_item.setProperty('IsPlayable', 'true')
    xbmcplugin.addDirectoryItem(syshandle, url, list_item, is_folder)

# --- Funkciók ---

def list_categories():
    """Főmenü."""
    add_directory_item("Legújabb videók", {'action': 'list_videos', 'url': f"{BASE_URL}/friss-porno/"})
    add_directory_item("Legjobb szexvideók", {'action': 'list_videos', 'url': f"{BASE_URL}/legjobb-szexvideok/"})
    add_directory_item("Kategóriák", {'action': 'list_subcats', 'url': f"{BASE_URL}/kategoriak/"})
    add_directory_item("[COLOR orange]Keresés...[/COLOR]", {'action': 'search_menu'})
    endDirectory('files')

def list_subcategories(url):
    html = get_html(url)
    if not html:
        xbmcplugin.endOfDirectory(syshandle)
        return
    
    soup = BeautifulSoup(html, 'html.parser')
    # A beküldött HTML-edben ezek <a> tagek 'item' class-szal
    items = soup.find_all('a', class_='item')
    
    for item in items:
        href = item.get('href', '')
        if '/kategoriak/' in href:
            # Cím kinyerése
            title_tag = item.find('strong', class_='title')
            title = title_tag.text.strip() if title_tag else "Kategória"
            
            # --- HIÁNYPÓTLÁS: Videók száma ---
            count_tag = item.find('div', class_='videos')
            if count_tag:
                v_count = count_tag.text.strip() # pl. "394 videó"
                display_name = f"{title} [COLOR gray]({v_count})[/COLOR]"
            else:
                display_name = title
            
            if not href.startswith('http'): href = BASE_URL + href
            
            img = item.find('img', class_='thumb')
            thumb = img.get('src') if img else ''
            
            add_directory_item(display_name, {'action': 'list_videos', 'url': href}, is_folder=True, thumb=thumb)
            
    xbmcplugin.setContent(syshandle, 'files')
    xbmcplugin.endOfDirectory(syshandle)

def list_videos(url):
    html = get_html(url)
    if not html:
        xbmcplugin.endOfDirectory(syshandle)
        return
    
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.find_all('div', class_='item')
    
    valid_count = 0
    for item in items:
        link = item.find('a')
        if not link or '/szexkepek/' in link.get('href', ''): continue
        
        v_url = link.get('href')
        if not v_url.startswith('http'): v_url = BASE_URL + v_url
        
        # --- HIÁNYPÓTLÁS: Időtartam (Duration) ---
        dur_tag = item.find('div', class_='duration')
        duration = dur_tag.text.strip() if dur_tag else ""
        
        title = link.get('title') or (item.find('strong').text if item.find('strong') else "Videó")
        
        # Sárga időtartam a cím elé
        if duration:
            display_title = f"[COLOR yellow][{duration}][/COLOR] {title}"
        else:
            display_title = title
            
        img = item.find('img')
        thumb = img.get('data-original') or img.get('src') if img else ''
        
        valid_count += 1
        add_directory_item(display_title, {'action': 'play', 'url': v_url}, is_folder=False, thumb=thumb, info={"duration": duration})
    
    # Lapozó rész (a korábbi stabil URL-összehasonlítással)
    if valid_count > 0:
        next_li = soup.find('li', class_='next')
        if next_li and next_li.find('a'):
            n_url = next_li.find('a').get('href')
            if not n_url.startswith('http'): n_url = BASE_URL + n_url
            if n_url.rstrip('/') != url.rstrip('/'):
                add_directory_item("[COLOR yellow]>>> KÖVETKEZŐ OLDAL >>>[/COLOR]", {'action': 'list_videos', 'url': n_url}, is_folder=True)

    xbmcplugin.setContent(syshandle, 'videos')
    xbmcplugin.endOfDirectory(syshandle)

def search():
    """Kodi keresőablak."""
    kb = xbmcgui.Dialog().input('Keresés...', type=xbmcgui.INPUT_ALPHANUM)
    if kb:
        # A keresési URL-nél fontos a megfelelő paraméterezés
        search_url = f"{BASE_URL}/kereses/?q={urllib.parse.quote_plus(kb)}"
        list_videos(search_url)

def play_video(url):
    """Videó lejátszása."""
    html = get_html(url)
    if not html: return
    soup = BeautifulSoup(html, 'html.parser')
    
    video_src = None
    v_tag = soup.find('video')
    if v_tag and v_tag.find('source'):
        video_src = v_tag.find('source').get('src')
    
    if not video_src:
        meta = soup.find('meta', itemprop='contentUrl')
        if meta: video_src = meta.get('content')

    if video_src:
        if video_src.startswith('//'): video_src = 'https:' + video_src
        play_item = xbmcgui.ListItem(path=video_src)
        xbmcplugin.setResolvedUrl(syshandle, True, play_item)

# --- Router ---

def router(paramstring):
    params = dict(urllib.parse.parse_qsl(paramstring))
    if not params:
        list_categories()
    elif params['action'] == 'list_videos':
        list_videos(params['url'])
    elif params['action'] == 'list_subcats':
        list_subcategories(params['url'])
    elif params['action'] == 'search_menu':
        search()
    elif params['action'] == 'play':
        play_video(params['url'])

if __name__ == '__main__':
    router(sys.argv[2][1:])