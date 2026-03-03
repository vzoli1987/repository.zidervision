# -*- coding: utf-8 -*-
import xbmc, xbmcgui, xbmcplugin, xbmcvfs, xbmcaddon
import requests
from bs4 import BeautifulSoup
import sys, urllib.parse, re, json, os, time
from datetime import datetime, timedelta

# --- KONFIGURÁCIÓ ---
ADDON = xbmcaddon.Addon()
BASE_URL = "https://musor.tv"
HANDLE = int(sys.argv[1])
ADDON_DATA = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))

if not xbmcvfs.exists(ADDON_DATA):
    xbmcvfs.mkdir(ADDON_DATA)

CACHE_FILE = os.path.join(ADDON_DATA, 'musortv_cache.json')
HISTORY_FILE = os.path.join(ADDON_DATA, 'search_history.json')
CACHE_TIME = 600 

MONTH_NAMES = {
    "01": "jan.", "02": "febr.", "03": "márc.", "04": "ápr.",
    "05": "máj.", "06": "jún.", "07": "júl.", "08": "aug.",
    "09": "szept.", "10": "okt.", "11": "nov.", "12": "dec."
}

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})

# --- SEGÉDFÜGGVÉNYEK ---

def get_html(url):
    time.sleep(0.5) # Szervervédelem (2026-01-05 kérés)
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
    except: return None

def get_deep_desc(url):
    html = get_html(url)
    if not html: return None
    soup = BeautifulSoup(html, 'html.parser')
    desc_tag = soup.select_one('.eventinfolongdesc, .showeventlongdesc')
    if desc_tag:
        import copy
        temp_tag = copy.copy(desc_tag)
        for extra in temp_tag.find_all(["div", "img", "script", "style"]): extra.decompose()
        for br in temp_tag.find_all(["br", "p"]): br.replace_with("\n")
        return temp_tag.get_text().strip()
    return None

def format_dynamic_date(date_str):
    try:
        dt_obj = datetime.strptime(date_str, "%Y.%m.%d")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        if dt_obj == today: return "" 
        elif dt_obj == tomorrow: return "[Holnap] "
        else:
            p = date_str.split('.')
            return f"[{MONTH_NAMES.get(p[1], p[1])} {p[2]}.] "
    except: return ""

# --- KERESÉS ÉS ELŐZMÉNYEK ---

def get_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return []
    return []

def save_to_history(query):
    if not query: return
    history = get_history()
    if query in history: history.remove(query)
    history.insert(0, query)
    history = history[:15]
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f)

def clear_history():
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    xbmc.executebuiltin('Container.Refresh')

def list_search_menu():
    u = f"{sys.argv[0]}?action=do_search"
    li = xbmcgui.ListItem(label="[COLOR yellow][B]🔍 ÚJ KERESÉS...[/B][/COLOR]")
    li.setArt({'icon': "DefaultAddonsSearch.png"})
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)

    history = get_history()
    for item in history:
        u = f"{sys.argv[0]}?action=do_search&query={urllib.parse.quote(item)}"
        li = xbmcgui.ListItem(label=f"🕒 {item}")
        li.setArt({'icon': "DefaultFolder.png"})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)
    
    if history:
        u = f"{sys.argv[0]}?action=clear_history"
        li = xbmcgui.ListItem(label="[COLOR red]✖ ELŐZMÉNYEK TÖRLÉSE[/COLOR]")
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=False)
    xbmcplugin.endOfDirectory(HANDLE)

def do_search(query=None):
    if not query:
        kb = xbmc.Keyboard('', 'Keresés:')
        kb.doModal()
        if kb.isConfirmed() and kb.getText(): query = kb.getText().strip()
        else: return
    save_to_history(query)
    search_slug = re.sub(r'\s+', '-', query)
    list_programs(f"{BASE_URL}/musorkereso/{urllib.parse.quote(search_slug)}", False)

# --- MENÜK ---

def list_main_menu():
    m = [("[COLOR yellow][B]>>> Keresés <<<[/B][/COLOR]", "search_menu", "DefaultAddonsSearch.png"),
         ("[COLOR lightblue][B]>>> FILMEK <<<[/B][/COLOR]", "movie_menu", "DefaultMovies.png"),
         ("[COLOR orange][B]>>> SPORTMŰSOROK <<<[/B][/COLOR]", "sport_menu", "DefaultIconSports.png"),
         ("[COLOR plum][B]>>> SOROZATOK ÉS EGYÉB <<<[/B][/COLOR]", "extra_menu", "DefaultTVShows.png")]
    for n, a, i in m:
        u = f"{sys.argv[0]}?action={a}"; li = xbmcgui.ListItem(label=n)
        li.setArt({'icon': i, 'thumb': i})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_sport_categories():
    c = [("[COLOR springgreen][B][ FOCI ÉLŐBEN ][/B][/COLOR]", "/foci_eloben"),
         ("[COLOR orange][B][ LIVERPOOL ][/B][/COLOR]", "/liverpool_mai_meccs_kozvetites"),
         ("[COLOR yellow][B][ KÉZILABDA ][/B][/COLOR]", "/kezilabda_kozvetitesek_ma"),
         ("[COLOR cyan][B][ TENISZ ][/B][/COLOR]", "/tenisz"),
         ("[COLOR grey][B][ ÖSSZES SPORT ][/B][/COLOR]", "/sportmusorok")]
    for n, p in c:
        u = f"{sys.argv[0]}?action=list&url={urllib.parse.quote(BASE_URL + p)}&is_sport=True"
        li = xbmcgui.ListItem(label=n); li.setArt({'icon': "DefaultIconSports.png"})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_movie_categories():
    c = [("[COLOR yellow][B][ FILMEK Rövidesen ][/B][/COLOR]", "/filmek"),
         ("[B][ VÍGJÁTÉKOK ][/B]", "/vigjatekok"),
         ("[B][ ROMANTIKUS FILMEK ][/B]", "/romantikus_filmek"),
         ("[B][ HORROR FILMEK ][/B]", "/horror_filmek")]
    for n, p in c:
        u = f"{sys.argv[0]}?action=list&url={urllib.parse.quote(BASE_URL + p)}&is_sport=False"
        li = xbmcgui.ListItem(label=n); li.setArt({'icon': "DefaultMovies.png"})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_extra_categories():
    c = [("[COLOR orchid][B][ SOROZATOK ][/B][/COLOR]", "/sorozatok"),
         ("[COLOR plum][B][ INDULÓ SOROZATOK ][/B][/COLOR]", "/indulo_sorozatok"),
         ("[COLOR khaki][B][ SZÓRAKOZTATÓ MŰSOROK ][/B][/COLOR]", "/szorakoztato_musorok"),
         ("[COLOR lightgreen][B][ GYERMEKMŰSOROK ][/B][/COLOR]", "/gyermekmusorok")]
    for n, p in c:
        u = f"{sys.argv[0]}?action=list&url={urllib.parse.quote(BASE_URL + p)}&is_sport=False"
        li = xbmcgui.ListItem(label=n); li.setArt({'icon': "DefaultTVShows.png"})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

# --- LISTÁZÁS ÉS MEGJELENÍTÉS ---

def list_programs(target_url, is_sport_mode):
    html = get_html(target_url)
    if not html: return
    soup = BeautifulSoup(html, 'html.parser') 
    items = soup.select('table.showeventtable') 
    seen = set()
    for item in items:
        try:
            time_tag = item.select_one('.showeventtime')
            if not time_tag: continue
            raw_t = time_tag.get_text().strip() 
            tm = re.search(r'(\d{4}\.\d{2}\.\d{2})\s+(\d{2}:\d{2})', raw_t)
            time_val = tm.group(2) if tm else (re.search(r'(\d{2}:\d{2})', raw_t).group(1) if ":" in raw_t else "--:--")
            display_date = format_dynamic_date(tm.group(1)) if tm else ""

            title_tag = item.select_one('.showeventtitle a')
            main_cat = title_tag.text.strip()
            link = BASE_URL + title_tag['href']
            if link in seen: continue
            seen.add(link)

            # ÉLŐ / PREMIER / KÉPEK
            extra_prefix = ""
            rec_tag = item.select_one('.smartpe_recommendation_text_common, .smartpe_recommendation_live')
            if rec_tag:
                txt = rec_tag.text.upper()
                if "ÉLŐ" in txt: extra_prefix = "[COLOR red][B][ÉLŐ][/B][/COLOR] "
                elif "PREMIER" in txt: extra_prefix = "[COLOR lightblue][B][PREMIER][/B][/COLOR] "

            img_tag = item.select_one('img.showeventimg')
            image_url = (BASE_URL + img_tag['src'] if img_tag and not img_tag['src'].startswith('http') else img_tag['src'] if img_tag else "").replace('/small/', '/normal/')
            
            logo_tag = item.select_one('img.channelheaderlink')
            logo_url = BASE_URL + logo_tag['src'] if logo_tag and not logo_tag['src'].startswith('http') else logo_tag['src'] if logo_tag else ""

            ev_tag = item.find(attrs={"itemprop": "name"})
            ev_name = ev_tag.get_text().strip() if ev_tag else ""
            display_title = f"{ev_name} ({main_cat})" if ev_name and ev_name.lower() != main_cat.lower() else main_cat
            search_text = ev_name if ev_name else main_cat

            ch_img = item.select_one('.showeventchannel img')
            channel = ch_img['alt'].replace("(HD)", "").strip() if ch_img else "TV"
            
            d_parts = []
            sd = item.find(attrs={"itemprop": "description"})
            if sd: d_parts.append(f"[B]{sd.get_text().strip()}[/B]")
            ld = item.select_one('.showeventlongdesc, .eventinfolongdesc')
            if ld: d_parts.append(ld.get_text().strip())
            full_desc = "\n".join(d_parts)

            label = f"{'[COLOR grey]'+display_date+'[/COLOR] ' if display_date else ''}[COLOR orange][B]{time_val}[/B][/COLOR] | {extra_prefix}[B]{display_title}[/B] [COLOR gold][B][{channel}][/B][/COLOR]"
            li = xbmcgui.ListItem(label=label)
            li.setArt({'thumb': image_url, 'icon': "DefaultVideo.png", 'landscape': logo_url, 'fanart': image_url})
            
            info = li.getVideoInfoTag()
            info.setTitle(display_title)
            info.setPlot(f"[B]{display_date if display_date else 'Ma'} {time_val}[/B]\n[B]Csatorna:[/B] {channel}\n\n{full_desc}")

            clean_q = search_text.split('(')[0].split(':')[0].strip()
            desc_u = f"{sys.argv[0]}?action=only_desc&url={urllib.parse.quote(link)}&title={urllib.parse.quote(display_title)}&time={urllib.parse.quote(time_val)}&desc={urllib.parse.quote(full_desc)}&channel={urllib.parse.quote(channel)}"
            li.addContextMenuItems([
                ('[COLOR yellow]Műsor részletes leírása[/COLOR]', f'RunPlugin({desc_u})'),
                (f'STB.hu keresés: {clean_q}', f'Container.Update(plugin://plugin.video.stb_hu/?action=get_search_items&search_text={urllib.parse.quote_plus(clean_q)})')
            ])

            u = f"{sys.argv[0]}?action=play&url={urllib.parse.quote(link)}&title={urllib.parse.quote(display_title)}&time={time_val}&q={urllib.parse.quote(search_text)}&channel={urllib.parse.quote(channel)}&desc={urllib.parse.quote(full_desc)}"
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=False)
        except: continue
    xbmcplugin.endOfDirectory(HANDLE)

def play_video(url, title, time_val, q, channel, desc):
    clean_t = q.split('(')[0].split(':')[0].strip()
    deep = get_deep_desc(url)
    xbmcgui.Dialog().textviewer(f"{time_val} - {title} [{channel}]", deep if deep else desc)
    
    ret = xbmcgui.Dialog().select(f"{clean_t}", ["STB.hu keresés", "YouTube előzetes"])
    if ret == 0: 
        xbmc.executebuiltin(f"Container.Update(plugin://plugin.video.stb_hu/?action=get_search_items&search_text={urllib.parse.quote_plus(clean_t)})")
    elif ret == 1: 
        xbmc.executebuiltin(f"ActivateWindow(Videos,plugin://plugin.video.youtube/kodion/search/query/?q={urllib.parse.quote_plus(clean_t + ' előzetes')},return)")

def router(paramstring):
    p = dict(urllib.parse.parse_qsl(paramstring.lstrip('?')))
    a = p.get('action')
    if a == 'search_menu': list_search_menu()
    elif a == 'do_search': do_search(p.get('query'))
    elif a == 'clear_history': clear_history()
    elif a == 'list': list_programs(p.get('url'), p.get('is_sport') == 'True')
    elif a == 'play': play_video(p.get('url'), p.get('title'), p.get('time'), p.get('q'), p.get('channel'), p.get('desc'))
    elif a == 'only_desc':
        deep = get_deep_desc(p.get('url'))
        xbmcgui.Dialog().textviewer(f"{p.get('time')} - {p.get('title')}", deep if deep else p.get('desc'))
    elif a == 'sport_menu': list_sport_categories()
    elif a == 'movie_menu': list_movie_categories()
    elif a == 'extra_menu': list_extra_categories()
    else: list_main_menu()

if __name__ == '__main__':
    router(sys.argv[2])