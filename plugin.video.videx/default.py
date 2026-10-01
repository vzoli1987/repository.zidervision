import sys
import re
import json
import urllib.parse
import requests
from datetime import datetime

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

# --- Alapbeállítások ---
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]
MAIN_PAGE_URL = "https://videx.lol/"
BASE_DOMAIN = "https://videx.lol"

def get_session():
    """Létrehoz egy requests session-t a megfelelő sütikkel és fejlécekkel."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    })
    session.cookies.set('site_lang', 'en', domain='videx.lol')
    return session

def get_main_page_events():
    """Kigyűjti az eseményeket a főoldal HTML-jéből, javított Élő detektálással."""
    session = get_session()
    try:
        response = session.get(MAIN_PAGE_URL, timeout=15)
        response.raise_for_status()
        html = response.text
        
        events = []
        # Robusztusabb regex: az egész <a> blokkot lekezeli, nem csak egy soros egyezést keres
        pattern = r'<a\s+([^>]*class="[^"]*nf-card[^"]*"[^>]*)>(.*?)</a>'
        matches = re.finditer(pattern, html, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            attrs = match.group(1)
            content = match.group(2)
            
            # href kinyerése
            href_match = re.search(r'href="([^"]+)"', attrs)
            if not href_match:
                continue
            href = href_match.group(1)
            
            # kép src kinyerése
            img_match = re.search(r'<img\s+[^>]*src="([^"]+)"', content)
            img_src = img_match.group(1) if img_match else ""
            
            # cím kinyerése (az alt attribútumból vagy a title div-ből)
            title_match = re.search(r'alt="([^"]+)"', content)
            if not title_match:
                title_match = re.search(r'class="[^"]*nf-card__title[^"]*"[^>]*>([^<]+)', content)
            
            title = title_match.group(1).strip() if title_match else "Ismeretlen esemény"
            
            # Élő státusz ellenőrzése (Több feltétel is élhet a biztonság kedvéért)
            is_live = (
                'nf-card--live' in attrs or 
                'badge-live' in content or 
                'EN VIVO' in content.upper() or 
                'LIVE' in content.upper()
            )
            
            # Debug naplózás a Kodi logjába, hogy ellenőrizhető legyen
            xbmc.log(f"VIDEX ADDON: '{title}' - is_live: {is_live}", xbmc.LOGINFO)
            
            # Kezdési idő keresése (ha van data-start attribútum)
            time_match = re.search(r'data-start=["\']?(\d+)["\']?', attrs)
            start_time_str = ""
            if time_match:
                try:
                    ts = int(time_match.group(1))
                    if ts > 1e10: 
                        ts = ts // 1000 # Ha ms-ban van
                    dt = datetime.fromtimestamp(ts)
                    start_time_str = dt.strftime("%H:%M")
                except Exception:
                    pass
            
            full_url = href if href.startswith('http') else f"{BASE_DOMAIN}{href}"
            
            events.append({
                'title': title,
                'image': img_src,
                'url': full_url,
                'is_live': is_live,
                'start_time': start_time_str
            })
            
        return events

    except Exception as e:
        xbmcgui.Dialog().notification('Hiba', f'Főoldal betöltése: {str(e)}', xbmcgui.NOTIFICATION_ERROR)
        xbmc.log(f"VIDEX ADDON ERROR: {str(e)}", xbmc.LOGERROR)
        return []

def list_events():
    """Megjeleníti az eseményeket a Kodi főmenüjében."""
    events = get_main_page_events()
    
    if not events:
        xbmcgui.Dialog().notification('Infó', 'Nincs elérhető esemény.', xbmcgui.NOTIFICATION_INFO)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    for event in events:
        # Címke formázása státusz alapján
        if event['is_live']:
            display_title = f"[COLOR red][B][ÉLŐ][/B][/COLOR] {event['title']}"
        elif event['start_time']:
            display_title = f"[COLOR yellow][{event['start_time']}][/COLOR] {event['title']}"
        else:
            display_title = event['title']

        params = {
            'action': 'event_detail',
            'title': event['title'],
            'image': event['image'],
            'url': event['url']
        }
        url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
        
        list_item = xbmcgui.ListItem(label=display_title)
        list_item.setInfo('video', {'title': event['title'], 'mediatype': 'video'})
        list_item.setArt({'thumb': event['image'], 'icon': event['image']})
        
        # Natív Kodi Élő jelzés beállítása (ha a skin támogatja)
        if event['is_live']:
            list_item.setProperty('IsLive', 'true')
            
        xbmcplugin.addDirectoryItem(HANDLE, url, list_item, isFolder=True)
        
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(HANDLE)

def get_event_streams(event_url):
    """Kinyeri a CFG JSON-t az adott esemény oldaláról."""
    session = get_session()
    try:
        response = session.get(event_url, timeout=15)
        response.raise_for_status()
        
        # A var CFG = {...}; rész kinyerése
        match = re.search(r'var\s+CFG\s*=\s*(\{.*?\});\s*CFG\.session', response.text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
            
        # Fallback, ha a struktúra minimálisan eltérne
        match = re.search(r'var\s+CFG\s*=\s*(\{.*?\});\s*\n', response.text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
            
        return None
    except Exception as e:
        xbmcgui.Dialog().notification('Hiba', f'Event oldal hiba: {str(e)}', xbmcgui.NOTIFICATION_ERROR)
        xbmc.log(f"VIDEX ADDON EVENT ERROR: {str(e)}", xbmc.LOGERROR)
        return None

def list_channels_for_event(event_url, title, image):
    """Listázza a csatornákat a kiválasztott eseményhez."""
    cfg_data = get_event_streams(event_url)
    
    if not cfg_data or 'channels' not in cfg_data:
        xbmcgui.Dialog().notification('Hiba', 'Nem találhatók streamek.', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    for channel in cfg_data['channels']:
        if channel.get('playable') and channel.get('src'):
            params = {
                'action': 'play',
                'title': f"{title} - {channel['name']}",
                'url': channel['src'],
                'image': image
            }
            url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
            
            list_item = xbmcgui.ListItem(label=channel['name'])
            list_item.setInfo('video', {'title': f"{title} - {channel['name']}"})
            list_item.setArt({'thumb': image, 'icon': image})
            list_item.setProperty('IsPlayable', 'true')
            
            xbmcplugin.addDirectoryItem(HANDLE, url, list_item, isFolder=False)
            
    xbmcplugin.endOfDirectory(HANDLE)

def play_stream(url, title, image):
    """Lejátszás indítása InputStream Adaptive-del."""
    list_item = xbmcgui.ListItem(label=title, path=url)
    list_item.setArt({'thumb': image, 'icon': image})
    list_item.setProperty('IsPlayable', 'true')
    
    # HLS (.m3u8) streamekhez elengedhetetlen
    list_item.setProperty('inputstream', 'inputstream.adaptive')
    list_item.setProperty('inputstream.adaptive.manifest_type', 'hls')
    
    # A HAR fájl alapján a szerver ellenőrzi a Referer fejlécet
    list_item.setProperty('inputstream.adaptive.stream_headers', f"Referer={BASE_DOMAIN}")
    
    xbmcplugin.setResolvedUrl(HANDLE, True, listitem=list_item)

def router(param_string):
    """Útválasztó a műveletek között."""
    params = dict(urllib.parse.parse_qsl(param_string))
    action = params.get('action')
    
    if action == 'event_detail':
        list_channels_for_event(params.get('url'), params.get('title'), params.get('image'))
    elif action == 'play':
        play_stream(params.get('url'), params.get('title'), params.get('image'))
    else:
        list_events()

if __name__ == '__main__':
    param_string = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    router(param_string)