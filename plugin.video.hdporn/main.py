import sys
import re
import time
import requests
import urllib.parse
import os
import hashlib
from bs4 import BeautifulSoup
import xbmcgui
import xbmcplugin
import xbmcvfs

# --- Beállítások ---
HANDLE = int(sys.argv[1])
BASE_URL = "https://hdporn.hu"
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0'
COOKIES = 'kt_tcookie=1; kt_agecheck=1'

TEMP_DIR = xbmcvfs.translatePath('special://temp/hdporn_thumbs/')
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

def get_html(url):
    time.sleep(0.5)
    headers = {'User-Agent': UA, 'Referer': BASE_URL + '/', 'Cookie': COOKIES}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'utf-8'
        return r.text
    except:
        return ""

def get_local_thumb(t_url):
    if not t_url: return ""
    if t_url.startswith('//'): t_url = "https:" + t_url
    img_hash = hashlib.md5(t_url.encode()).hexdigest()
    local_thumb = os.path.join(TEMP_DIR, f"{img_hash}.webp")
    if not os.path.exists(local_thumb):
        try:
            r = requests.get(t_url, headers={'User-Agent': UA}, timeout=5)
            if r.status_code == 200:
                with open(local_thumb, 'wb') as f:
                    f.write(r.content)
                return local_thumb
        except:
            return t_url
    return local_thumb

def main_menu():
    menu_items = [
        ("Friss videók", f"{BASE_URL}/uj-videok/", "list_videos"),
        ("Felkapott videók", f"{BASE_URL}/felkapott-videok/", "list_videos"),
        ("Legnézettebb videók", f"{BASE_URL}/nezett-videok/", "list_videos"),
        ("Kategóriák", f"{BASE_URL}/kategoriak/", "list_categories"),
        ("Keresés", "SEARCH_TRIGGER", "list_videos")
    ]
    for label, url, action in menu_items:
        list_item = xbmcgui.ListItem(label=f"[COLOR orange]➔[/COLOR] {label}")
        u = f"{sys.argv[0]}?action={action}&url={urllib.parse.quote_plus(url)}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=list_item, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_categories(url):
    html = get_html(url)
    if not html: return
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.find_all('a', class_='item')
    for item in items:
        title_tag = item.find('strong', class_='title')
        if not title_tag: continue
        title = title_tag.text.strip()
        cat_url = item.get('href')
        img_tag = item.find('img')
        thumb_url = img_tag.get('src') if img_tag else ""
        final_thumb = get_local_thumb(thumb_url)
        v_count = item.find('div', class_='videos')
        label = f"{title} [COLOR grey]({v_count.text.strip() if v_count else ''})[/COLOR]"
        list_item = xbmcgui.ListItem(label=label)
        list_item.setArt({'thumb': final_thumb, 'icon': final_thumb, 'fanart': final_thumb})
        u = f"{sys.argv[0]}?action=list_videos&url={urllib.parse.quote_plus(cat_url)}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=list_item, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_videos(url):
    if url == "SEARCH_TRIGGER":
        kb = xbmcgui.Dialog().input("Keresés", type=xbmcgui.INPUT_ALPHANUM)
        if not kb: return
        url = f"{BASE_URL}/kereses/{urllib.parse.quote_plus(kb)}/"

    html = get_html(url)
    if not html: return
    soup = BeautifulSoup(html, 'html.parser')
    
    items = soup.find_all('div', class_='item')
    for item in items:
        link_tag = item.find('a')
        if not link_tag: continue
        page_url = link_tag.get('href', '')
        if 'video' not in page_url: continue 
        title = link_tag.get('title', '').strip()
        
        duration = ""
        d_tag = item.find('div', class_='duration')
        if d_tag: duration = d_tag.find('em').text.strip() if d_tag.find('em') else d_tag.text.strip()

        img_tag = item.find('img')
        thumb_url = img_tag.get('data-webp') or img_tag.get('data-original') or img_tag.get('src') if img_tag else ""
        final_thumb = get_local_thumb(thumb_url)

        display_label = f"[COLOR orange][{duration}][/COLOR] {title}" if duration else title
        list_item = xbmcgui.ListItem(label=display_label)
        list_item.setArt({'thumb': final_thumb, 'icon': final_thumb, 'fanart': final_thumb, 'poster': final_thumb})
        list_item.setInfo('video', {'title': title, 'duration': duration, 'mediatype': 'video'})
        list_item.setProperty('IsPlayable', 'true')
        
        play_url = f"{sys.argv[0]}?action=play&url={urllib.parse.quote_plus(page_url)}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=play_url, listitem=list_item, isFolder=False)

    # --- HIBRID LAPOZÁS ---
    more_btn = soup.find('a', attrs={'data-action': 'ajax'})
    if more_btn:
        next_url = None
        href = more_btn.get('href', '')
        
        # 1. eset: Van benne rendes URL (pl. /felkapott-videok/2/)
        if href and href != '#' and not href.startswith('javascript'):
            next_url = href if href.startswith('http') else BASE_URL + href
        
        # 2. eset: AJAX paraméterek vannak (data-parameters="from:5")
        elif 'data-parameters' in more_btn.attrs:
            match = re.search(r'from:(\d+)', more_btn['data-parameters'])
            if match:
                from_val = match.group(1)
                parsed_url = urllib.parse.urlparse(url)
                query = dict(urllib.parse.parse_qsl(parsed_url.query))
                query['from'] = from_val
                next_url = urllib.parse.urlunparse(parsed_url._replace(query=urllib.parse.urlencode(query)))
                if '?' not in next_url:
                    next_url = f"{url.rstrip('/')}/?from={from_val}"

        if next_url:
            li = xbmcgui.ListItem(label="[COLOR lime]>>> KÖVETKEZŐ OLDAL >>>[/COLOR]")
            u = f"{sys.argv[0]}?action=list_videos&url={urllib.parse.quote_plus(next_url)}"
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(HANDLE)

def play_video(page_url):
    html = get_html(page_url)
    match = re.search(r"video_url:\s*'([^']+)'", html) or re.search(r'source\s+src="([^"]+)"', html)
    if match:
        video_link = match.group(1)
        headers = {'User-Agent': UA, 'Cookie': COOKIES, 'Referer': page_url}
        full_url = f"{video_link}|{urllib.parse.urlencode(headers)}"
        play_item = xbmcgui.ListItem(path=full_url)
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=play_item)

# --- Router ---
params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
action = params.get('action')
url = params.get('url')

if not action:
    main_menu()
elif action == 'list_videos':
    list_videos(url)
elif action == 'list_categories':
    list_categories(url)
elif action == 'play':
    play_video(url)