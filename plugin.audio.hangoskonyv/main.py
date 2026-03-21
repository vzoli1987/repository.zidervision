# -*- coding: utf-8 -*-
import sys
import time
import urllib.parse
import xbmc
import xbmcgui
import xbmcplugin
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    from bs4 import BeautifulSoup
except ImportError:
    xbmcgui.Dialog().ok("Hiba", "A BeautifulSoup4 modul hiányzik!")

BASE_URL = "https://www.hangoskonyv.net"
ADDON_HANDLE = int(sys.argv[1])
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:148.0) Gecko/20100101 Firefox/148.0'

def get_html(url, referer=None):
    if not url: return None
    time.sleep(0.25) 
    headers = {'User-Agent': USER_AGENT}
    if referer: headers['Referer'] = referer
    try:
        r = requests.get(url, headers=headers, timeout=10, verify=False)
        if r.encoding == 'ISO-8859-1':
            r.encoding = r.apparent_encoding
        return r.text
    except: return None

def clean_image_url(raw_url):
    if not raw_url: return ""
    url = raw_url.split('?')[0]
    if '/styles/' in url:
        parts = url.split('/public/')
        if len(parts) > 1:
            url = BASE_URL + '/sites/default/files/' + parts[1]
    if not url.startswith('http'):
        url = urllib.parse.urljoin(BASE_URL, url)
    return url + "|User-Agent=" + urllib.parse.quote(USER_AGENT)

def list_categories():
    html = get_html(BASE_URL)
    if not html: return
    soup = BeautifulSoup(html, 'html.parser')
    menu = soup.find('ul', class_='menu')
    if menu:
        for a in menu.find_all('a', href=True):
            if 'hangoskonyv-letoltes' in a['href'] or 'hangosk%C3%B6nyv-let%C3%B6lt%C3%A9s' in a['href']:
                u = build_url({'action': 'list_books', 'url': urllib.parse.urljoin(BASE_URL, a['href'])})
                xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=u, listitem=xbmcgui.ListItem(label=a.text.strip()), isFolder=True)
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_books(url):
    html = get_html(url)
    if not html: return
    soup = BeautifulSoup(html, 'html.parser')
    
    articles = soup.find_all(['article', 'div'], class_=['node-hangoskonyvek', 'node-teaser'])
    
    if not articles:
        xbmcgui.Dialog().notification("Infó", "Ebben a kategóriában nincs tartalom.", xbmcgui.NOTIFICATION_INFO, 3000)
    
    for item in articles:
        h2_tag = item.find('h2')
        if not h2_tag or not h2_tag.find('a'): continue
        
        book_title = h2_tag.get_text(strip=True)
        book_url = urllib.parse.urljoin(BASE_URL, h2_tag.find('a')['href'])
        
        img = ""
        img_tag = item.find('img')
        if img_tag and img_tag.get('src'):
            img = clean_image_url(img_tag['src'])

        summary = ""
        body_div = item.find('div', class_=['field-name-body', 'content'])
        if body_div:
            summary = body_div.get_text(separator=" ").strip()

        li = xbmcgui.ListItem(label=book_title)
        li.setInfo('video', {'plot': summary, 'title': book_title})
        if img:
            li.setArt({'thumb': img, 'icon': img, 'fanart': img, 'poster': img})

        u = build_url({'action': 'list_chapters', 'url': book_url, 'title': book_title, 'image': img})
        xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=u, listitem=li, isFolder=True)
        
    pager = soup.find('ul', class_='pager')
    if pager and pager.find('li', class_='pager-next'):
        n_a = pager.find('li', class_='pager-next').find('a')
        if n_a:
            next_url = urllib.parse.urljoin(url, n_a['href'])
            xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=build_url({'action': 'list_books', 'url': next_url}), 
                                        listitem=xbmcgui.ListItem(label=">> Következő oldal"), isFolder=True)
    
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_chapters(url, title, image):
    html = get_html(url)
    if not html: return
    soup = BeautifulSoup(html, 'html.parser')
    
    # Részletes leírás kinyerése
    plot = ""
    body = soup.find('div', class_='field-name-body')
    if body: plot = body.get_text(separator="\n").strip()

    # Forrás link keresése
    l_cont = soup.find('div', class_='field-name-field-link')
    source_url = l_cont.find('a')['href'].split('#')[0] if l_cont and l_cont.find('a') else ""
    
    # HIBAKEZELÉS: Ha nincs link, értesítés ÉS automatikus visszalépés
    if not source_url:
        xbmcgui.Dialog().notification("Figyelem", "Nincs lejátszható forrás.", xbmcgui.NOTIFICATION_WARNING, 3000)
        # Ez a parancs szimulálja a 'Back' gombot, így nem maradsz az üres mappában
        xbmc.executebuiltin("Action(ParentDir)")
        return

    all_tracks = []
    clean_url = source_url.rstrip('/')
    targets = [clean_url + "/mp3/index.html", clean_url + "/index.html", source_url]
    
    for t_url in targets:
        content = get_html(t_url, referer=url)
        if not content: continue
        s = BeautifulSoup(content, 'html.parser')
        for a in s.find_all('a', href=True):
            if a['href'].lower().endswith('.mp3'):
                all_tracks.append({'url': urllib.parse.urljoin(t_url, a['href']), 'label': a.get_text(strip=True)})
        if all_tracks: break

    # HIBAKEZELÉS: Ha nincsenek MP3-ak, értesítés ÉS automatikus visszalépés
    if not all_tracks:
        xbmcgui.Dialog().notification("Figyelem", "Nem találhatók MP3 fájlok.", xbmcgui.NOTIFICATION_WARNING, 3000)
        xbmc.executebuiltin("Action(ParentDir)")
        return

    # Ha minden oké, kilistázzuk a fájlokat
    for i, track in enumerate(sorted(all_tracks, key=lambda x: x['url'])):
        label = track['label'].replace(".mp3", "").replace(".MP3", "").split("(")[0].strip()
        li = xbmcgui.ListItem(label=f"{i+1:02d}. {label}")
        li.setInfo('video', {'plot': plot, 'title': label})
        if image: li.setArt({'thumb': image, 'icon': image})
        li.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(handle=ADDON_HANDLE, url=track['url'], listitem=li, isFolder=False)

    xbmcplugin.setContent(ADDON_HANDLE, 'songs')
    xbmcplugin.endOfDirectory(ADDON_HANDLE)

def build_url(query): return sys.argv[0] + '?' + urllib.parse.urlencode(query)

def router(ps):
    p = dict(urllib.parse.parse_qsl(ps))
    a = p.get('action')
    if not a: list_categories()
    elif a == 'list_books': list_books(p['url'])
    elif a == 'list_chapters': list_chapters(p['url'], p.get('title'), p.get('image'))

if __name__ == '__main__': router(sys.argv[2][1:])