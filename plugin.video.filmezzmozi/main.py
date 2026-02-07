import sys
import urllib.parse
import requests
import xbmcgui
import xbmcplugin
import xbmc
import resolveurl
import re

URL = "https://filmezzmozi.do.am/"
HANDLE = int(sys.argv[1])

def get_movies():
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(URL, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        html = r.text
        
        # Ez a minta kifejezetten a beküldött HTML-re épül:
        # Keresi a <tr id="bk_title"> utáni linket és a címet
        pattern = r'<tr id="bk_title"><td><a href="([^"]+)">([^<]+)</a>'
        matches = re.findall(pattern, html)
        
        items = []
        seen_urls = set() # Duplikációk kiszűrése (mert az oldalon több helyen is ott van ugyanaz)
        
        for link, title in matches:
            if link not in seen_urls:
                seen_urls.add(link)
                items.append({
                    'title': title.strip(),
                    'url': link
                })
            
        return items
    except Exception as e:
        xbmc.log(f"FILMEZZ ERROR: {str(e)}", xbmc.LOGERROR)
        return []

def main_menu():
    xbmcplugin.setContent(HANDLE, 'movies')
    movies = get_movies()
    
    if not movies:
        xbmcgui.Dialog().ok("Hiba", "Nem sikerült kinyerni a filmeket a forráskódból.")
        
    for m in movies:
        li = xbmcgui.ListItem(label=m['title'])
        li.setInfo('video', {'title': m['title']})
        li.setProperty('IsPlayable', 'true')
        
        # Paraméterek átadása a lejátszáshoz
        query = urllib.parse.urlencode({'action': 'play', 'url': m['url']})
        path = f"{sys.argv[0]}?{query}"
        xbmcplugin.addDirectoryItem(HANDLE, path, li, False)
    
    xbmcplugin.endOfDirectory(HANDLE)

def play_video(page_url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        r = requests.get(page_url, headers=headers, timeout=15)
        html = r.text
        
        sources = []

        # 1. IFRAME-ek keresése (VK, OK, stb.)
        iframes = re.findall(r'<iframe.*?src=["\']([^"\']+)["\']', html)
        for url in iframes:
            if url.startswith('//'): url = 'https:' + url
            sources.append({'name': 'Fő lejátszó', 'url': url})

        # 2. SZÖVEGES LINKEK keresése (Mixdrop, Vidoza, stb.)
        # Kifejezetten a táblázat alján lévő linkekre vadászunk
        link_patterns = [
            (r'https?://mixdrop\.[a-z]+/e/[^"\']+', 'Mixdrop'),
            (r'https?://vidoza\.net/[^"\']+', 'Vidoza'),
            (r'https?://vkvideo\.ru/[^"\']+', 'VK Video'),
            (r'https?://ds2play\.com/e/[^"\']+', 'Vidoza (DS2)'),
        ]

        for pattern, label in link_patterns:
            matches = re.findall(pattern, html)
            for m in matches:
                sources.append({'name': label, 'url': m})

        if not sources:
            xbmcgui.Dialog().notification('Hiba', 'Nem található videó link.', xbmcgui.NOTIFICATION_ERROR, 5000)
            return

        # 3. Ha több forrás van, választatunk a felhasználóval
        if len(sources) > 1:
            labels = [s['name'] for s in sources]
            selected = xbmcgui.Dialog().select("Válassz forrást", labels)
            if selected == -1: return
            target_url = sources[selected]['url']
        else:
            target_url = sources[0]['url']

        # 4. Feloldás a ResolveURL-lel
        xbmc.log(f"RESOLVING: {target_url}", xbmc.LOGINFO)
        playable_url = resolveurl.resolve(target_url)

        if playable_url:
            li = xbmcgui.ListItem(path=playable_url)
            xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, li)
        else:
            xbmcgui.Dialog().notification('Hiba', 'ResolveURL nem tudta feloldani.', xbmcgui.NOTIFICATION_ERROR, 5000)

    except Exception as e:
        xbmc.log(f"HIBA: {str(e)}", xbmc.LOGERROR)

# Útvonalválasztó (Router)
params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
action = params.get('action')

if not action:
    main_menu()
elif action == 'play':
    play_video(params['url'])