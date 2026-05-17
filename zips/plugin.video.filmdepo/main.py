# -*- coding: utf-8 -*-
import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmc
import requests
from bs4 import BeautifulSoup
import re
import time

# RESOLVEURL IMPORT
try:
    import resolveurl
except ImportError:
    resolveurl = None

# ALAPADATOK
ADDON = xbmcaddon.Addon()
BASE_URL = "https://filmdepo.hu"
HANDLE = int(sys.argv[1])

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': BASE_URL
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ── SEGÉDFÜGGVÉNYEK ──────────────────────────────────────────────────────────

def get_html(url):
    """Lekéri a HTML-t fél másodperces késleltetéssel a szerver védelmében."""
    time.sleep(0.5)
    try:
        r = SESSION.get(url, timeout=15)
        r.encoding = 'utf-8'
        return r.text
    except:
        return ""

def clean_title(title):
    """Kitisztítja a címet a felesleges kategórianevektől."""
    if not title: return ""
    garbage = [
        "Legnézettebb", "Legjobbra értékelt", "Értékelt", "Összes film", "Keresés", "Top 50",
        "Akció", "Thriller", "Horror", "Vígjáték", "Dráma", "Sci-Fi", "Romantikus", 
        "Kaland", "Fantasy", "Animáció", "Családi", "Bűnügyi", "Misztikus", 
        "Háborús", "Történelmi", "Dokumentum", "Western", "Filmek", "Keresési találatok:"
    ]
    for word in garbage:
        pattern = re.compile(re.escape(word), re.IGNORECASE)
        title = pattern.sub("", title)
    title = re.sub(r'\(\s*\d{4}\s*\)', '', title)
    title = title.replace('..', '').replace('...', '').strip()
    title = title.lstrip('. /-_„”"').rstrip('. /-_„”"').strip()
    return title

def get_plot_from_details(url):
    html = get_html(url)
    if not html: return "Nincs leírás."
    soup = BeautifulSoup(html, 'html.parser')
    plot_el = soup.select_one('.plot-text') or soup.select_one('#plot') or soup.select_one('.fd-plot')
    return plot_el.get_text(strip=True) if plot_el else "Nincs leírás."

# ── MENÜK ────────────────────────────────────────────────────────────────────

def list_categories():
    items = [
        ("Filmek (Összes)", f"{BASE_URL}/ajax/movies_ajax.php?page=1", "list"),
        ("Top 50 (Hivatalos)", f"{BASE_URL}/top50.php", "list"),
        ("Top 50 (Legjobbra értékelt)", f"{BASE_URL}/top50.php?t=rating", "list"),
        ("Műfajok", "", "genres"),
        ("Évszámok", "", "years"),
        ("Keresés", "", "search"),
    ]
    for name, url, action in items:
        li = xbmcgui.ListItem(label=name)
        param = f"{sys.argv[0]}?action={action}&url={urllib.parse.quote_plus(url)}"
        xbmcplugin.addDirectoryItem(HANDLE, param, li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_genres():
    genres = ["Akció", "Thriller", "Horror", "Vígjáték", "Dráma", "Sci-Fi", "Romantikus", "Kaland", "Fantasy", "Animáció", "Családi", "Bűnügyi"]
    for g in genres:
        url = f"{BASE_URL}/top50.php?t=genre&g={urllib.parse.quote(g)}"
        li = xbmcgui.ListItem(label=g)
        param = f"{sys.argv[0]}?action=list&url={urllib.parse.quote_plus(url)}"
        xbmcplugin.addDirectoryItem(HANDLE, param, li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

def list_years():
    for year in range(2026, 1950, -1):
        url = f"{BASE_URL}/top50.php?t=year&y={year}"
        li = xbmcgui.ListItem(label=str(year))
        param = f"{sys.argv[0]}?action=list&url={urllib.parse.quote_plus(url)}"
        xbmcplugin.addDirectoryItem(HANDLE, param, li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)

# ── LISTÁZÁS ÉS LEJÁTSZÁS ─────────────────────────────────────────────────────

def list_movies(url):
    html = get_html(url)
    if not html:
        xbmcplugin.endOfDirectory(HANDLE, False)
        return

    soup = BeautifulSoup(html, 'html.parser')
    
    # Keresési találatok (.col) és normál listák (.d-flex)
    items = soup.select('.col') + soup.select('.d-flex.gap-3')
    
    if not items:
        items = soup.find_all('a', href=re.compile(r'details\.php\?id=\d+'))

    seen_hrefs = set()
    for item in items:
        link_tag = item if item.name == 'a' else item.find('a', href=True)
        if not link_tag: continue
        
        href = link_tag.get('href', '')
        if not href or href in seen_hrefs or any(x in href for x in ["/category/", "/user/", "javascript"]):
            continue
        
        seen_hrefs.add(href)
        full_href = href if href.startswith('http') else f"{BASE_URL}/{href.lstrip('/')}"

        # Cím keresése
        title_el = item.select_one('.fw-semibold') or item.select_one('.top50-title') or item.select_one('.fd-title')
        raw_title = title_el.get_text(" ", strip=True) if title_el else link_tag.get_text(" ", strip=True)
        
        year_match = re.search(r'\((\d{4})\)', raw_title)
        year = year_match.group(1) if year_match else "0"
        title = clean_title(raw_title)

        if not title or len(title) < 2: continue

        # Leírást csak akkor rakunk be, ha az oldalon eleve ott van (nem töltünk be külön URL-t)
        plot = ""
        plot_el = item.find('div', style=lambda x: x and 'line-height:1.25' in x) or item.select_one('.fd-plot')
        if plot_el: 
            plot = plot_el.get_text(strip=True)

        li = xbmcgui.ListItem(label=title)
        li.setInfo('video', {'title': title, 'plot': plot, 'year': int(year)})
        li.setProperty('IsPlayable', 'true')

        # Poszter keresése
        poster = ""
        img = item.find('img', class_='card-img-top') or item.find('img')
        if img: 
            poster = img.get('src') or img.get('data-src') or img.get('data-original')
        
        if poster:
            if "http" in poster[4:]:
                poster = poster[poster.find("http", 4):]
            if not poster.startswith('http'): 
                poster = f"{BASE_URL}/{poster.lstrip('/')}"
            li.setArt({'poster': poster, 'thumb': poster, 'icon': poster})

        param = f"{sys.argv[0]}?action=play&url={urllib.parse.quote_plus(full_href)}"
        xbmcplugin.addDirectoryItem(HANDLE, param, li, isFolder=False)

    # Lapozás kezelése
    if "ajax" in url:
        curr_page = int(re.search(r'page=(\d+)', url).group(1)) if "page=" in url else 1
        next_url = re.sub(r'page=\d+', f'page={curr_page + 1}', url)
        li_next = xbmcgui.ListItem(label=f">> KÖVETKEZŐ OLDAL ({curr_page + 1})")
        xbmcplugin.addDirectoryItem(HANDLE, f"{sys.argv[0]}?action=list&url={urllib.parse.quote_plus(next_url)}", li_next, isFolder=True)
        
    xbmcplugin.endOfDirectory(HANDLE)

def play_video(url):
    html = get_html(url)
    video_url = None
    fd_urls_match = re.search(r'main\s*:\s*["\']([^"\']+)["\']', html)
    if fd_urls_match:
        video_url = fd_urls_match.group(1).replace('\\/', '/')
    else:
        soup = BeautifulSoup(html, 'html.parser')
        iframe = soup.find('iframe', src=re.compile(r'video|embed|player|stream'))
        if iframe: video_url = iframe.get('src')
    
    resolved_url = None
    if video_url:
        if video_url.startswith('//'): video_url = 'https:' + video_url
        elif video_url.startswith('/'): video_url = BASE_URL + video_url
        try:
            if resolveurl:
                resolved_url = resolveurl.resolve(video_url)
            else:
                resolved_url = video_url
        except:
            resolved_url = None

    if resolved_url:
        xbmcplugin.setResolvedUrl(HANDLE, True, xbmcgui.ListItem(path=resolved_url))
    else:
        xbmcgui.Dialog().notification('Hiba', 'A videó nem elérhető!', xbmcgui.NOTIFICATION_ERROR, 5000)

# ── ROUTER ───────────────────────────────────────────────────────────────────

def router(paramstring):
    params = dict(urllib.parse.parse_qsl(paramstring or ''))
    action = params.get('action')
    if action == 'list': list_movies(params['url'])
    elif action == 'genres': list_genres()
    elif action == 'years': list_years()
    elif action == 'search':
        kb = xbmc.Keyboard('', 'Film keresése...')
        kb.doModal()
        if kb.isConfirmed() and kb.getText():
            q = urllib.parse.quote_plus(kb.getText())
            # A log alapján ez a helyes URL struktúra:
            list_movies(f"{BASE_URL}/search.php?q={q}")
    elif action == 'play': play_video(params['url'])
    else: list_categories()

if __name__ == '__main__':
    router(sys.argv[2][1:])