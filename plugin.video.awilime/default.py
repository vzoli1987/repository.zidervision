# -*- coding: utf-8 -*-
import sys
import urllib.parse
import re
import time
import random
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import requests
from bs4 import BeautifulSoup

ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE_URL = "https://www.awilime.com"

# Kapcsolat fenntartása (Sütik és Keep-alive a 429-es hiba ellen)
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'hu-HU,hu;q=0.9,en;q=0.8',
    'Referer': BASE_URL
})

def log(msg):
    xbmc.log(f"[AWILIME-DEBUG] {msg}", xbmc.LOGINFO)

def get_html(url, delay_min=0.8, delay_max=1.5):
    """Javított, Android-kompatibilis lekérés."""
    try:
        # Androidon és Awilime-on 0.8mp alatt szinte biztos a tiltás
        time.sleep(random.uniform(delay_min, delay_max))
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://awilime.com/' # Ezt muszáj látnia a szervernek!
        }
        
        # A session-t használjuk, hogy megmaradjanak a sütik
        r = session.get(url, headers=headers, timeout=15)
        r.encoding = 'utf-8'
        
        if r.status_code == 200:
            return r.text
        elif r.status_code == 429:
            xbmc.log("AWILIME: LIMIT ELÉRVE (429)", xbmc.LOGINFO)
            # Ha limitet kapunk, pihenjünk egy nagyot kényszerítve
            time.sleep(5)
            return "LIMIT"
        
        xbmc.log(f"AWILIME: Szerver hiba: {r.status_code}", xbmc.LOGERROR)
        return None
        
    except Exception as e:
        xbmc.log(f"AWILIME: Hiba a lekérésnél: {str(e)}", xbmc.LOGERROR)
        return None

def main_menu():
    categories = [
        ("Filmek (Összes)", "/tv/filmek"),
        ("Romantikus", "/tv/tematikus_musor/romantikus"),
        ("Akció", "/tv/tematikus_musor/akcio"),
        ("Kaland", "/tv/tematikus_musor/kaland"),
        ("Vígjáték", "/tv/tematikus_musor/vigjatek"),
        ("Horror", "/tv/tematikus_musor/horror"),
        ("Sci-fi", "/tv/tematikus_musor/sci-fi")
    ]
    for name, path in categories:
        url = f"{sys.argv[0]}?action=list&url={urllib.parse.quote(BASE_URL + path)}"
        li = xbmcgui.ListItem(label=name)
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_movies(target_url):
    html = get_html(target_url, 0.5, 1.2)
    if html == "LIMIT":
        xbmcgui.Dialog().ok("Hiba", "Túl sok kérés! A szerver átmenetileg tiltott (429). Kérlek várj pár percet.")
        return
    if not html: return

    soup = BeautifulSoup(html, 'html.parser')
    xbmcplugin.setContent(HANDLE, 'movies')
    
    # Keresünk minden olyan blokkot, ami filmet tartalmaz
    # Az awilime-on a <b> tagben van az időpont, ebből indulunk ki
    all_b_tags = soup.find_all('b')
    seen_urls = set()

    for b_tag in all_b_tags:
        time_text = b_tag.get_text()
        time_match = re.search(r'(\d{2}:\d{2})', time_text)
        if not time_match: continue
        
        time_str = time_match.group(1)
        parent_div = b_tag.find_parent('div')
        if not parent_div: continue

        link_tag = parent_div.find('a', href=re.compile(r'^/tv/'))
        if not link_tag: continue
        
        url_path = link_tag.get('href', '')
        full_url = BASE_URL + url_path
        if full_url in seen_urls: continue
        seen_urls.add(full_url)
        
        title = link_tag.get_text().strip()

        # --- KÉP ÉS LEÍRÁS KERESÉSE ---
        thumb = "DefaultVideo.png"
        plot_text = ""
        yt_id_found = None

        # Először megnézzük, hogy a főoldali listában ott van-e a YT ID
        img_tag = parent_div.find('img')
        if img_tag:
            img_src = img_tag.get('src', '')
            yt_id_match = re.search(r'vi/([a-zA-Z0-9_-]{11})', img_src)
            if yt_id_match:
                yt_id_found = yt_id_match.group(1)
                thumb = f"https://i.ytimg.com/vi/{yt_id_found}/hqdefault.jpg"
            elif 'blob.core.windows.net' in img_src:
                thumb = img_src.replace("_t.", "_b.")
                if thumb.startswith('/'): thumb = BASE_URL + thumb

        # HA NINCS KÉP a listaoldalon, CSAK AKKOR töltjük be az adatlapot (Szerverkímélés!)
        if thumb == "DefaultVideo.png":
            sub_html = get_html(full_url, 0.2, 0.5)
            if sub_html and sub_html != "LIMIT":
                sub_soup = BeautifulSoup(sub_html, 'html.parser')
                
                # 1. IMDb keresés
                imdb_match = re.search(r'imdb\.com/title/(tt\d+)', sub_html)
                if imdb_match:
                    imdb_id = imdb_match.group(1)
                    thumb = f"https://img.omdbapi.com/?i={imdb_id}&apikey=f6667923&h=1000"
                
                # 2. YouTube keresés az adatlapon
                if thumb == "DefaultVideo.png" or "omdbapi" in thumb:
                    yt_patterns = [r'embed/([a-zA-Z0-9_-]{11})', r'v=([a-zA-Z0-9_-]{11})']
                    for p in yt_patterns:
                        yt_m = re.search(p, sub_html)
                        if yt_m:
                            thumb = f"https://i.ytimg.com/vi/{yt_m.group(1)}/hqdefault.jpg"
                            break

                # 3. Leírás az adatlapról
                desc_tag = sub_soup.find('div', class_='m_leiras')
                if desc_tag:
                    plot_text = desc_tag.get_text().strip()

        # Ha még mindig nincs leírás, vesszük a listaoldalit
        if not plot_text:
            p_tag = parent_div.find('p')
            plot_text = p_tag.get_text().strip() if p_tag else ""

        # Csatorna és Értékelés
        channel = "TV"
        chan_tag = parent_div.find('img', class_='tkr')
        if chan_tag and chan_tag.get('b'): channel = chan_tag.get('b')
        
        rating_display = ""
        rating_tag = parent_div.find('a', href=re.compile(r'szavazas\.aspx'))
        if rating_tag:
            rating_display = f"[COLOR yellow]★ {rating_tag.get_text().strip()}[/COLOR] | "

        # Kodi elem összeállítása
        display_label = f"[COLOR orange]{time_str}[/COLOR] | [B]{title}[/B] [COLOR lightblue]({channel})[/COLOR]"
        li = xbmcgui.ListItem(label=display_label)
        li.setArt({'thumb': thumb, 'poster': thumb, 'fanart': thumb})
        
        info = li.getVideoInfoTag()
        info.setTitle(title)
        info.setPlot(f"{rating_display}{plot_text}")
        
        # Kontextus menü: STB.HU keresés
        clean_title = title.split('(')[0].split(':')[0].strip()
        stb_path = f"plugin://plugin.video.stb_hu/?action=get_search_items&search_text={urllib.parse.quote_plus(clean_title)}"
        li.addContextMenuItems([(f'STB.hu keresés: {clean_title}', f'Container.Update({stb_path})')])
        
        li.setProperty('IsPlayable', 'true')
        u = f"{sys.argv[0]}?action=play&url={urllib.parse.quote(full_url)}&title={urllib.parse.quote(title)}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=False)

    xbmcplugin.endOfDirectory(HANDLE)

def play_video(url, title):
    html = get_html(url)
    if not html or html == "LIMIT": return

    yt_id = None
    patterns = [r'embed/([a-zA-Z0-9_-]{11})', r'v=([a-zA-Z0-9_-]{11})', r'youtu\.be/([a-zA-Z0-9_-]{11})']
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            yt_id = match.group(1)
            break

    if yt_id:
        final_url = f"plugin://plugin.video.youtube/play/?video_id={yt_id}"
        li = xbmcgui.ListItem(label=title, path=final_url)
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=li)
    else:
        xbmcgui.Dialog().notification("Info", "Nincs elérhető trailer.", xbmcgui.NOTIFICATION_INFO)

# Router
params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
action = params.get('action')

if not action:
    main_menu()
elif action == 'list':
    list_movies(params.get('url'))
elif action == 'play':
    play_video(params.get('url'), params.get('title'))