# -*- coding: utf-8 -*-
import sys
import urllib.parse
import re
import time
import requests
import xbmc
import xbmcgui
import xbmcplugin
import json
import resolveurl
import html

# Globális változók
HANDLE = int(sys.argv[1])
BASE_URL = "https://www.fuggetlenfilmek.hu"

def get_html(url):
    """Lekéri a HTML/JSON tartalmat fix várakozással."""
    # [2026-01-05] Kis szünet, hogy ne legyen gyanús a szervernek
    time.sleep(0.5)
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'{BASE_URL}/lista'
        }
        r = requests.get(url, timeout=15, headers=headers)
        r.encoding = 'utf-8'
        return r.text
    except Exception as e:
        xbmc.log(f"FuggetlenFilmek - Hiba a letöltésnél: {str(e)}", xbmc.LOGERROR)
        return ""

def main_menu():
    """Főmenü a kategóriákkal."""
    categories = [
        ("Összes film", f"{BASE_URL}/lista"),
        ("Kisjátékfilm", f"{BASE_URL}/lista?cat=1"),
        ("Játékfilm", f"{BASE_URL}/lista?cat=2"),
        ("Dokumentum film", f"{BASE_URL}/lista?cat=3"),
        ("Zenei videoklip", f"{BASE_URL}/lista?cat=4"),
        ("Egyéb", f"{BASE_URL}/lista?cat=5"),
    ]
    
    for name, url in categories:
        li = xbmcgui.ListItem(label=name)
        u = sys.argv[0] + "?" + urllib.parse.urlencode({'action': 'list_movies', 'url': url})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_movies(url):
    """Film lista lekérése és megjelenítése nagy borítóképekkel."""
    xbmcplugin.setContent(HANDLE, 'movies') 
    html_content = get_html(url)
    
    pattern = r'<div>\s*<img src="([^"]+)" alt="([^"]+)" />.*?href="([^"]+)">.*?</a>\s*<span>\s*\((\d{4})\)\s*</span>.*?<div class="description[^"]*">(.*?)</div>'
    matches = re.findall(pattern, html_content, re.DOTALL)

    for thumb, alt_title, link, year, desc in matches:
        title = html.unescape(alt_title.strip())
        clean_desc = re.sub('<[^<]+?>', '', desc)
        clean_desc = html.unescape(clean_desc).replace('\n', ' ').strip()
        
        full_link = BASE_URL + "/" + link.lstrip('/')
        
        big_img = thumb.replace('_t.', '.')
        if '?' in big_img:
            big_img = big_img.split('?')[0]
            
        img_url = BASE_URL + "/" + big_img.lstrip('/')
        
        li = xbmcgui.ListItem(label=f"{title} ({year})")
        
        info = li.getVideoInfoTag()
        info.setTitle(title)
        info.setPlot(clean_desc)
        try: 
            info.setYear(int(year))
        except: 
            pass
        
        li.setArt({
            'thumb': img_url, 
            'poster': img_url, 
            'fanart': img_url,
            'landscape': img_url
        })
        
        u = sys.argv[0] + "?" + urllib.parse.urlencode({
            'url': full_link, 
            'action': 'list_versions', 
            'title': title, 
            'thumb': img_url
        })
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)

    next_page = re.search(r'href="(lista\?p=\d+)"[^>]*><i class="fa fa-forward"', html_content)
    if next_page:
        next_url = BASE_URL + "/" + next_page.group(1)
        li = xbmcgui.ListItem(label="[COLOR orange]>>> Következő oldal[/COLOR]")
        li.setArt({'thumb': 'DefaultFolder.png'})
        u = sys.argv[0] + "?" + urllib.parse.urlencode({'action': 'list_movies', 'url': next_url})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(HANDLE)

def list_versions(url, title, thumb):
    """Előzetes vagy Teljes film választó bővített adatokkal és színes formázással."""
    html_page = get_html(url)
    
    # --- EXTRA ADATOK KINYERÉSE ---
    # Játékidő
    duration_secs = 0
    h_match = re.search(r'(\d+)\s*óra', html_page)
    m_match = re.search(r'(\d+)\s*perc', html_page)
    if h_match: duration_secs += int(h_match.group(1)) * 3600
    if m_match: duration_secs += int(m_match.group(1)) * 60
        
    # Műfajok
    genres = re.findall(r'genre=\d+">([^<]+)</a>', html_page)
    genre_str = " / ".join(genres) if genres else ""
    
    # Korhatár
    age_match = re.search(r'age(\d+)', html_page)
    mpaa = age_match.group(1) if age_match else ""

    # Részletes leírás
    desc_match = re.search(r'id="main-description-box"[^>]*>(.*?)</div>', html_page, re.DOTALL)
    plot = ""
    if desc_match:
        plot = re.sub('<[^<]+?>', '', desc_match.group(1)).strip()
        plot = html.unescape(plot)

    # Összetett Plot (Műfaj színesben + leírás)
    full_plot = ""
    if genre_str: 
        full_plot += f"[COLOR grey]Műfaj: {genre_str}[/COLOR]\n\n"
    full_plot += plot

    # --- LISTA ELEMEK ---
    # Előzetes (videotype1)
    if 'videotype1' in html_page:
        label = f"[COLOR orange]►[/COLOR] [COLOR yellow]Előzetes:[/COLOR] {title}"
        li = xbmcgui.ListItem(label=label)
        
        info = li.getVideoInfoTag()
        info.setTitle(f"{title} (Előzetes)")
        info.setPlot(full_plot)
        info.setGenres(genres)
        info.setDuration(duration_secs)
        if mpaa: info.setMpaa(f"HU:{mpaa}")
        
        li.setArt({'thumb': thumb, 'poster': thumb, 'fanart': thumb})
        li.setProperty('IsPlayable', 'true')
        
        u = sys.argv[0] + "?" + urllib.parse.urlencode({'url': url, 'action': 'play', 'type': 'trailer'})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=False)

    # Teljes film (videotype3)
    if 'videotype3' in html_page:
        label = f"[COLOR lime]►[/COLOR] [COLOR green]Teljes film:[/COLOR] {title} [COLOR gold][Full HD][/COLOR]"
        li = xbmcgui.ListItem(label=label)
        
        info = li.getVideoInfoTag()
        info.setTitle(title)
        info.setPlot(full_plot)
        info.setGenres(genres)
        info.setDuration(duration_secs)
        if mpaa: info.setMpaa(f"HU:{mpaa}")
        
        li.setArt({'thumb': thumb, 'poster': thumb, 'fanart': thumb})
        li.setProperty('IsPlayable', 'true')
        
        u = sys.argv[0] + "?" + urllib.parse.urlencode({'url': url, 'action': 'play', 'type': 'movie'})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(HANDLE)

def play_video(params):
    url = params.get('url')
    video_type = params.get('type')
    
    v_id = url.strip('/').split('-')[-1]
    playlist_url = f"{BASE_URL}/alkotas/playlist/{v_id}"
    
    json_str = get_html(playlist_url)
    try:
        data = json.loads(json_str)
        target_type = "1" if video_type == 'trailer' else "3"
        final_url = ""
        
        for item in data.get("list", []):
            if str(item.get("video_type")) == target_type:
                final_url = item.get("video_url", "").replace('\\/', '/')
                break

        if final_url:
            video_id = ""
            if "v=" in final_url: video_id = final_url.split('v=')[-1].split('&')[0]
            elif "youtu.be/" in final_url: video_id = final_url.split('/')[-1].split('?')[0]

            if video_id:
                path = f"plugin://plugin.video.youtube/play/?video_id={video_id}"
            else:
                path = resolveurl.resolve(final_url) or final_url

            xbmcplugin.setResolvedUrl(HANDLE, True, listitem=xbmcgui.ListItem(path=path))
        else:
            xbmcplugin.setResolvedUrl(HANDLE, False, listitem=xbmcgui.ListItem())
    except:
        xbmcplugin.setResolvedUrl(HANDLE, False, listitem=xbmcgui.ListItem())

if __name__ == '__main__':
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
    action = params.get('action')
    
    if not action:
        main_menu()
    elif action == 'list_movies':
        list_movies(params.get('url'))
    elif action == 'list_versions':
        list_versions(params.get('url'), params.get('title'), params.get('thumb'))
    elif action == 'play':
        play_video(params)