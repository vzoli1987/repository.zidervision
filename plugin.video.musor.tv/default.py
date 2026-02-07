# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcplugin, xbmcvfs
import requests
from bs4 import BeautifulSoup
import sys, urllib.parse, re, json, os, time
from datetime import datetime, timedelta

# --- KONFIGURÁCIÓ ---
BASE_URL = "https://musor.tv"
HANDLE = int(sys.argv[1])
CACHE_FILE = xbmcvfs.translatePath('special://temp/musortv_cache.json')
CACHE_TIME = 600 

MONTH_NAMES = {
    "01": "jan.", "02": "febr.", "03": "márc.", "04": "ápr.",
    "05": "máj.", "06": "jún.", "07": "júl.", "08": "aug.",
    "09": "szept.", "10": "okt.", "11": "nov.", "12": "dec."
}

def log(msg, level=xbmc.LOGINFO):
    xbmc.log(f"[plugin.video.musortv] {msg}", level)

session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
})

def get_html(url):
    log(f"Lekérés: {url}")
    time.sleep(0.5) # 2026-01-05-i kérés: fix várakozás

    cache_data = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
        except: pass

    if url in cache_data and (time.time() - cache_data[url]['timestamp'] < CACHE_TIME):
        return cache_data[url]['content']

    try:
        resp = session.get(url, timeout=15)
        resp.encoding = 'utf-8' 
        if resp.status_code != 200: return None
        html = resp.text
        cache_data[url] = {'timestamp': time.time(), 'content': html}
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f)
        return html
    except Exception as e:
        log(f"Hiba: {str(e)}", xbmc.LOGERROR)
        return None

def format_dynamic_date(date_str):
    try:
        dt_obj = datetime.strptime(date_str, "%Y.%m.%d")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        if dt_obj == today:
            return "" 
        elif dt_obj == tomorrow:
            return "[Holnap] "
        else:
            parts = date_str.split('.')
            month_name = MONTH_NAMES.get(parts[1], parts[1])
            return f"[{month_name} {parts[2]}.] "
    except:
        return ""

def list_main_menu():
    menu = [
        ("[COLOR orange][B]>>> SPORTMŰSOROK <<<[/B][/COLOR]", "sport_menu", "DefaultIconSports.png"),
        ("[COLOR lightblue][B]>>> FILMEK <<<[/B][/COLOR]", "movie_menu", "DefaultMovies.png"),
        ("[COLOR plum][B]>>> SOROZATOK ÉS EGYÉB <<<[/B][/COLOR]", "extra_menu", "DefaultTVShows.png")
    ]
    for name, action, icon in menu:
        url = f"{sys.argv[0]}?action={action}"
        li = xbmcgui.ListItem(label=name)
        li.setArt({'icon': icon, 'thumb': icon})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_sport_categories():
    cats = [
        ("[COLOR springgreen][B][ FOCI ÉLŐBEN ][/B][/COLOR]", "/foci_eloben"),
        ("[COLOR orange][B][ LIVERPOOL MECCSEK ][/B][/COLOR]", "/liverpool_mai_meccs_kozvetites"),
        ("[COLOR yellow][B][ KÉZILABDA ][/B][/COLOR]", "/kezilabda_kozvetitesek_ma"),
        ("[COLOR cyan][B][ TENISZ ][/B][/COLOR]", "/tenisz"),
        ("[COLOR grey][B][ ÖSSZES SPORT ][/B][/COLOR]", "/sportmusorok")
    ]
    for name, path in cats:
        url = f"{sys.argv[0]}?action=list&url={urllib.parse.quote(BASE_URL + path)}&is_sport=True"
        li = xbmcgui.ListItem(label=name)
        li.setArt({'icon': "DefaultIconSports.png", 'thumb': "DefaultIconSports.png"})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_movie_categories():
    cats = [
        ("[COLOR yellow][B][ FILMEK Rövidesen ][/B][/COLOR]", "/filmek"),
        ("[B][ VÍGJÁTÉKOK ][/B]", "/vigjatekok"),
        ("[B][ ROMANTIKUS FILMEK ][/B]", "/romantikus_filmek"),
        ("[B][ HORROR FILMEK ][/B]", "/horror_filmek")
    ]
    for name, path in cats:
        url = f"{sys.argv[0]}?action=list&url={urllib.parse.quote(BASE_URL + path)}&is_sport=False"
        li = xbmcgui.ListItem(label=name)
        li.setArt({'icon': "DefaultMovies.png", 'thumb': "DefaultMovies.png"})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_extra_categories():
    cats = [
        ("[COLOR orchid][B][ SOROZATOK ][/B][/COLOR]", "/sorozatok"),
        ("[COLOR plum][B][ INDULÓ SOROZATOK ][/B][/COLOR]", "/indulo_sorozatok"),
        ("[COLOR khaki][B][ SZÓRAKOZTATÓ MŰSOROK ][/B][/COLOR]", "/szorakoztato_musorok"),
        ("[COLOR lightgreen][B][ GYERMEKMŰSOROK ][/B][/COLOR]", "/gyermekmusorok")
    ]
    for name, path in cats:
        url = f"{sys.argv[0]}?action=list&url={urllib.parse.quote(BASE_URL + path)}&is_sport=False"
        li = xbmcgui.ListItem(label=name)
        li.setArt({'icon': "DefaultTVShows.png", 'thumb': "DefaultTVShows.png"})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_programs(target_url, is_sport_mode):
    html = get_html(target_url)
    if not html: return
    soup = BeautifulSoup(html, 'html.parser') 
    items = soup.select('table.showeventtable') 
    seen_urls = set()

    for item in items:
        try:
            time_tag = item.select_one('.showeventtime')
            if not time_tag: continue
            raw_time_text = time_tag.get_text().strip() 
            time_match = re.search(r'(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2})', raw_time_text)
            
            if time_match:
                full_date = time_match.group(1)
                time_val = time_match.group(2)
                display_date = format_dynamic_date(full_date)
            else:
                time_val = re.search(r'(\d{2}:\d{2})', raw_time_text).group(1) if ":" in raw_time_text else "--:--"
                display_date = ""

            title_tag = item.select_one('.showeventtitle a')
            if not title_tag: continue
            main_cat = title_tag.text.strip()
            link = title_tag['href']
            if not link.startswith('http'): link = BASE_URL + link
            if link in seen_urls: continue
            seen_urls.add(link)

            image_url = ""
            logo_url = ""
            img_tag = item.select_one('img.showeventimg')
            if img_tag and img_tag.get('src'):
                src = img_tag['src']
                full_url = BASE_URL + src if not src.startswith('http') else src
                image_url = full_url.replace('/small/', '/normal/')
            
            logo_tag = item.select_one('img.channelheaderlink')
            if logo_tag and logo_tag.get('src'):
                l_src = logo_tag['src']
                logo_url = BASE_URL + l_src if not l_src.startswith('http') else l_src

            event_name_tag = item.find(attrs={"itemprop": "name"})
            event_name = event_name_tag.get_text().strip() if event_name_tag else ""
            display_title = f"{event_name} ({main_cat})" if event_name and event_name.lower() != main_cat.lower() else main_cat
            search_text = event_name if event_name else main_cat

            channel_img = item.select_one('.showeventchannel img')
            channel = channel_img['alt'].replace("(HD)", "").strip() if channel_img else "TV"

            extra_label = ""
            rec_tag = item.select_one('.smartpe_recommendation_text_common, .smartpe_recommendation_live')
            if rec_tag:
                tag_raw = rec_tag.text.upper()
                if "ÉLŐ" in tag_raw: extra_label = "[COLOR red][B][ÉLŐ][/B][/COLOR] "
                elif "PREMIER" in tag_raw: extra_label = "[COLOR lightblue][B][PREMIER][/B][/COLOR] "

            desc_parts = []
            extra_desc_tag = item.find(attrs={"itemprop": "description"})
            if extra_desc_tag:
                e_text = extra_desc_tag.get_text().strip()
                if e_text: desc_parts.append(f"[B]{e_text}[/B]")

            ld_tag = item.select_one('.showeventlongdesc')
            if ld_tag:
                import copy
                temp_ld = copy.copy(ld_tag)
                for br in temp_ld.find_all(["br", "p"]): br.replace_with("\n")
                l_text = temp_ld.get_text().strip()
                if l_text: desc_parts.append(l_text)
            full_desc = "\n".join(desc_parts)

            # --- KODI MEGJELENÍTÉS FINOMÍTVA ---
            # Dátum (szürke bold), Idő (narancs bold), Cím (fehér bold), Csatorna (powderblue bold)
            date_part = f"[COLOR lightgrey][B]{display_date}[/COLOR]" if display_date else ""
            time_part = f"[COLOR orange][B]{time_val}[/B][/COLOR]"
            title_part = f"{extra_label}{display_title}"
            channel_part = f"[COLOR gold][B][{channel}][/B][/COLOR]"
            
            label = f"{date_part}{time_part} | {title_part} {channel_part}"
            
            li = xbmcgui.ListItem(label=label)
            art = {}
            if image_url: art.update({'thumb': image_url, 'icon': image_url, 'fanart': image_url, 'landscape': image_url})
            if logo_url: art.update({'clearlogo': logo_url, 'logo': logo_url, 'banner': logo_url})
            li.setArt(art)

            info = li.getVideoInfoTag()
            info.setTitle(display_title)
            info.setPlot(f"[B]{display_date if display_date else 'Ma'} {time_val}[/B]\n[B]Csatorna:[/B] {channel}\n\n{full_desc}")

            if is_sport_mode:
                u = f"{sys.argv[0]}?action=sport_info&title={urllib.parse.quote(display_title)}&channel={urllib.parse.quote(channel)}&time={urllib.parse.quote(time_val)}&desc={urllib.parse.quote(full_desc)}"
                li.setProperty('IsPlayable', 'false')
                xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=False)
            else:
                u = f"{sys.argv[0]}?action=play&url={urllib.parse.quote(link)}&q={urllib.parse.quote(search_text)}"
                clean_search = search_text.split('(')[0].split(':')[0].strip()
                stb_path = f"plugin://plugin.video.stb_hu/?action=get_search_items&search_text={urllib.parse.quote_plus(clean_search)}"
                li.addContextMenuItems([(f'STB.hu keresés: {clean_search}', f'Container.Update({stb_path})')])
                xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=False)

        except: continue
    xbmcplugin.endOfDirectory(HANDLE)

def show_sport_gui(title, channel, time_str, desc):
    header = f"{time_str} - {title} [{channel}]"
    xbmcgui.Dialog().textviewer(header, desc)

def play_video(url, search_query):
    clean_title = search_query.split('(')[0].split(':')[0].strip()
    dialog = xbmcgui.Dialog()
    ret = dialog.select(f"{clean_title}", ["Keresés az STB.hu-n", "YouTube Előzetes/Klip"])
    if ret == 0:
        path = f"plugin://plugin.video.stb_hu/?action=get_search_items&search_text={urllib.parse.quote_plus(clean_title)}"
        xbmc.executebuiltin(f"Container.Update({path})")
    elif ret == 1:
        yt_path = f"plugin://plugin.video.youtube/kodion/search/query/?q={urllib.parse.quote_plus(clean_title + ' előzetes')}"
        xbmc.executebuiltin(f"ActivateWindow(Videos,{yt_path},return)")

def router(paramstring):
    params = dict(urllib.parse.parse_qsl(paramstring.lstrip('?')))
    action = params.get('action')
    if action == 'sport_menu': list_sport_categories()
    elif action == 'movie_menu': list_movie_categories()
    elif action == 'extra_menu': list_extra_categories()
    elif action == 'list': list_programs(params.get('url'), params.get('is_sport') == 'True')
    elif action == 'play': play_video(params.get('url'), params.get('q'))
    elif action == 'sport_info': show_sport_gui(params.get('title'), params.get('channel'), params.get('time'), params.get('desc'))
    else: list_main_menu()

if __name__ == '__main__':
    router(sys.argv[2])