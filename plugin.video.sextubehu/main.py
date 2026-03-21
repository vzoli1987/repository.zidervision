# -*- coding: utf-8 -*-
import sys
import urllib.parse
import re
import json
import time
import random
import requests
from bs4 import BeautifulSoup
import xbmcgui
import xbmcplugin
import xbmcaddon

# --- Beállítások ---
BASE_URL = 'https://www.sex-tube.hu'
ADDON_HANDLE = int(sys.argv[1])

def get_html(url):
    """Lekéri a HTML-t, vár 0.5 mp-et és álcázza magát."""
    # Felhasználó kérése alapján: fix várakozási idő a gyanú elkerülésére
    time.sleep(0.5)
    
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
    ]
    
    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Referer': BASE_URL
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        xbmcgui.Dialog().notification('Hiba', 'Nem sikerült az oldal betöltése', xbmcgui.NOTIFICATION_ERROR)
        return None

def main_menu():
    """Főkategóriák listázása."""
    categories = [
        ('Legújabb videók', '/'),
        ('Családi szex', '/szexvideok/családi'),
        ('Anya szex', '/szexvideok/anya'),
        ('Amatőr pornó', '/szexvideok/amatőr'),
        ('Analszex', '/szexvideok/anal'),
        ('Keresés...', 'search')
    ]
    
    for name, path in categories:
        if path == 'search':
            url = f"{sys.argv[0]}?action=search"
        else:
            full_url = BASE_URL + path
            url = f"{sys.argv[0]}?action=list_videos&url={urllib.parse.quote(full_url)}"
        
        li = xbmcgui.ListItem(label=name)
        xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=url, listitem=li, isFolder=True)
    
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_videos(url):
    """Videók listázása a kategóriából, szűrve a szemetet."""
    html = get_html(url)
    if not html:
        return

    soup = BeautifulSoup(html, 'html.parser')
    container = soup.find('div', class_='col8') # A fő tartalom
    
    if not container:
        xbmcplugin.endOfDirectory(ADDON_HANDLE)
        return

    # Sorrendben haladunk a fő konténer elemein
    for child in container.children:
        # 1. Ha elérünk egy címsort, ami nem a kategória címe, megállunk
        if child.name in ['h1', 'h2']:
            txt = child.get_text().lower()
            if any(x in txt for x in ['több ilyen', 'népszerűbb', 'kapcsolódó']):
                break
        
        # 2. Videó blokkok feldolgozása
        if child.name == 'div' and 'onerow' in child.get('class', []):
            video_divs = child.find_all('div', class_='col11')
            for item in video_divs:
                # Szűrjük ki a slider-ben lévő (ajánlott) videókat
                if 'slider_related' in item.get('class', []):
                    continue
                
                link_tag = item.find('a', href=True)
                img_tag = item.find('img')
                
                if link_tag and img_tag:
                    title = img_tag.get('title') or link_tag.get_text(strip=True)
                    v_path = link_tag['href']
                    v_url = BASE_URL + v_path if v_path.startswith('/') else v_path
                    thumb = img_tag.get('data-src') or img_tag.get('src')
                    if thumb and thumb.startswith('/'): thumb = BASE_URL + thumb

                    li = xbmcgui.ListItem(label=title)
                    li.setArt({'thumb': thumb, 'icon': thumb, 'fanart': thumb})
                    li.setInfo('video', {'title': title, 'mediatype': 'video'})
                    li.setProperty('IsPlayable', 'true')
                    
                    # Lejátszási URL készítése
                    u = f"{sys.argv[0]}?action=play&url={urllib.parse.quote(v_url)}"
                    xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=u, listitem=li, isFolder=False)

    # 3. Lapozás keresése
    next_page = soup.find('a', string=re.compile(r'›|Következő'))
    if next_page and next_page.get('href'):
        n_url = BASE_URL + next_page['href']
        li = xbmcgui.ListItem(label='[COLOR green]>>> Következő oldal >>>[/COLOR]')
        u = f"{sys.argv[0]}?action=list_videos&url={urllib.parse.quote(n_url)}"
        xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=u, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def play_video(url):
    """Kinyeri a videó forrását a lejátszó oldalból."""
    html = get_html(url)
    if not html: return
    
    # Közvetlen MP4 keresése a forráskódban (gyorsabb mint a BS4)
    match = re.search(r'source src=\'(.*?\.mp4)\'', html)
    if match:
        video_url = match.group(1)
        li = xbmcgui.ListItem(path=video_url)
        xbmcplugin.setResolvedUrl(ADDON_HANDLE, True, listitem=li)

def search():
    """Keresés funkció."""
    kb = xbmcgui.Dialog().input('Keresés a Sex-Tube.hu-n', type=xbmcgui.INPUT_ALPHANUM)
    if kb:
        search_term = kb.replace(' ', '-')
        url = f"{BASE_URL}/szexvideok/{urllib.parse.quote(search_term)}"
        list_videos(url)

# --- Router ---
params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
action = params.get('action')

if not action:
    main_menu()
elif action == 'list_videos':
    list_videos(params.get('url'))
elif action == 'play':
    play_video(params.get('url'))
elif action == 'search':
    search()