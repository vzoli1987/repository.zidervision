import xbmcplugin
import xbmcgui
import xbmc
import xbmcvfs
import sys
import requests
from bs4 import BeautifulSoup
import resolveurl
import re
import urllib.parse
import os
import json
import time
import hashlib
from concurrent.futures import ThreadPoolExecutor

def translate_path(path):
    if hasattr(xbmcvfs, 'translatePath'): return xbmcvfs.translatePath(path)
    return xbmc.translatePath(path)

SESSION = requests.Session()
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
HEADERS = {
    'User-Agent': UA,
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'hu-HU,hu;q=0.8,en-US;q=0.5,en;q=0.3',
    'Referer': 'https://www.napiszar.biz/',
    'Connection': 'keep-alive'
}
SESSION.headers.update(HEADERS)

CACHE_DIR = translate_path('special://temp/')
CACHE_EXPIRE = 1800 

BLACKLIST = [
    'napiszar.biz/kategoria/', 'napiszar.biz/tag/',
    'x.com', 'twitter.com', 'instagram.com', 'tiktok.com', 
    'ajax.googleapis.com', 'googletagmanager.com', 'google-analytics',
    'doubleclick', 'amazon-adsystem', 'adnxs', 'smartadserver'
]

BAD_EXTENSIONS = ['.js', '.css', '.json', '.xml', '.php', '.txt', '.pdf', '.jpg', '.jpeg', '.png']

def get_html(url, use_cache=False):
    url_hash = hashlib.md5(url.encode()).hexdigest()
    cache_file = os.path.join(CACHE_DIR, f'napiszar_h_{url_hash}.json')
    if use_cache and os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                d = json.load(f)
                if time.time() - d['timestamp'] < CACHE_EXPIRE: return d['content']
        except: pass
    try:
        r = SESSION.get(url, timeout=10)
        r.encoding = 'utf-8'
        if r.status_code == 200:
            if use_cache:
                with open(cache_file, 'w', encoding='utf-8') as f:
                    json.dump({'timestamp': time.time(), 'content': r.text}, f)
            return r.text
    except: pass
    return None

def get_host_label(url):
    u = url.lower()
    if '.gif' in u: return " [COLOR cyan][GIF Video][/COLOR]"
    if 'redgifs.com' in u: return " [COLOR pink][RedGifs][/COLOR]"
    if 'videa.hu' in u: return " [COLOR green][Videa][/COLOR]"
    if any(x in u for x in ['facebook.com', 'fb.watch', 'fb.com']): return " [COLOR blue][Facebook][/COLOR]"
    if 'youtube' in u or 'youtu.be' in u: return " [COLOR red][YouTube][/COLOR]"
    if 'pornhub.com' in u: return " [COLOR orange][PornHub][/COLOR]"
    if 'xvideos.com' in u: return " [COLOR orange][XVideos][/COLOR]"
    
    try:
        hmf = resolveurl.HostedMediaFile(url)
        if hmf and hmf.valid_url():
            h_name = hmf.get_host()
            return f" [COLOR yellow][{h_name.capitalize() if h_name else 'Link'}][/COLOR]"
    except: pass
    
    if any(x in u for x in ['.mp4', '.m3u8']): return " [COLOR yellow][Direct][/COLOR]"
    return ""

def check_single_post(post_data):
    title, page_url, thumb = post_data
    html = get_html(page_url)
    if not html: return None

    found_src = None
    
    # 1. Először az igazi beágyazott videó iframe-eket keressük (v25 szűrés)
    fb_plugins = re.findall(r'facebook\.com/plugins/video\.php\?.*?href=(.*?)&', html)
    if fb_plugins:
        # Dekódoljuk és ellenőrizzük, hogy nem üres-e
        candidate = urllib.parse.unquote(fb_plugins[0])
        if 'facebook.com' in candidate:
            found_src = candidate

    # 2. Ha nem találtunk iframe-et, keressük a HTML-ben a nyers linkeket
    if not found_src:
        sources = re.findall(r'https?://[^\s"\'<>\\{}]+', html)
        for src in sources:
            src = src.replace('\\/', '/')
            src = src.split('"')[0].split("'")[0].split('\\')[0].rstrip('.)')
            src = urllib.parse.unquote(src).replace('&amp;', '&')
            src_low = src.lower()

            if any(bad in src_low for bad in BLACKLIST): continue
            
            # Facebook specifikus szűrés (v25)
            if 'facebook.com' in src_low:
                # KIZÁRJUK a Likebox-ot és a sima profilokat
                if 'likebox.php' in src_low or 'plugins/like.php' in src_low: continue
                
                # Csak akkor fogadjuk el, ha videó/poszt azonosító van benne
                if any(x in src_low for x in ['/videos/', '/watch', '/posts/', 'v=']):
                    found_src = src
                    break
                else:
                    continue # Sima profil link nem kell
            
            # Egyéb szolgáltatók (Videa, Pornhub, stb.)
            label = get_host_label(src)
            if label:
                if 'napiszar.biz' in src_low and not any(x in src_low for x in ['.gif', '.mp4']):
                    continue
                found_src = src
                break

    if found_src:
        return {'title': title + get_host_label(found_src), 'url': page_url, 'thumb': thumb, 'video_src': found_src}
    return None

def list_videos(page=1):
    handle = int(sys.argv[1])
    # v23 kényszerített frissítés
    cache_path = os.path.join(CACHE_DIR, f'napiszar_list_v23_p{page}.json')
    
    if os.path.exists(cache_path) and (time.time() - os.path.getmtime(cache_path) < CACHE_EXPIRE):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                valid_videos = json.load(f)
        except: valid_videos = None
    else: valid_videos = None

    if valid_videos is None:
        base_url = "https://www.napiszar.biz" 
        url = f"{base_url}/kategoria/video/" if page == 1 else f"{base_url}/kategoria/video/oldal/{page}/"
        
        pDialog = xbmcgui.DialogProgress()
        pDialog.create('Napiszar', f'Tartalom elemzése - {page}. oldal')
        
        html = get_html(url)
        if not html: return
        
        soup = BeautifulSoup(html, 'html.parser')
        candidate_data = []
        for post in soup.find_all('h2'):
            a = post.find('a')
            if not a: continue
            art = post.find_parent('article')
            img = art.find('img') if art else None
            t = (img.get('data-src') or img.get('src') or '') if img else ''
            candidate_data.append((a.text.strip(), a['href'], t))

        with ThreadPoolExecutor(max_workers=10) as executor:
            valid_videos = [r for r in list(executor.map(check_single_post, candidate_data)) if r]
        
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(valid_videos, f)
        pDialog.close()

    for vid in valid_videos:
        li = xbmcgui.ListItem(label=vid['title'])
        if vid['thumb']: li.setArt({'thumb': vid['thumb'], 'icon': vid['thumb']})
        li.setProperty('IsPlayable', 'true')
        li.setInfo('video', {'title': vid['title']})
        u = f"{sys.argv[0]}?action=play&url={urllib.parse.quote_plus(vid['video_src'])}"
        xbmcplugin.addDirectoryItem(handle=handle, url=u, listitem=li, isFolder=False)

    next_page = page + 1
    u_next = f"{sys.argv[0]}?action=list&page={next_page}"
    li_next = xbmcgui.ListItem(label=f"[B][COLOR yellow]>>> {next_page}. OLDAL[/COLOR][/B]")
    xbmcplugin.addDirectoryItem(handle=handle, url=u_next, listitem=li_next, isFolder=True)
    xbmcplugin.setContent(handle, 'videos')
    xbmcplugin.endOfDirectory(handle)

def play_video(video_src):
    video_src = urllib.parse.unquote(video_src).replace('&amp;', '&')
    xbmc.log(f"NAPISZAR DEBUG: Feloldás indítása: {video_src}", xbmc.LOGINFO)
    final_url = None
    
# 1. RedGifs speciális kezelés (v34 - API + Fallback)
    if 'redgifs.com' in video_src:
        video_id = video_src.split('/')[-1].split('?')[0]
        watch_url = f"https://www.redgifs.com/watch/{video_id}"
        
        try:
            # Token kérése az API-tól
            auth_url = "https://api.redgifs.com/v2/auth/temporary"
            req_auth = urllib.request.Request(auth_url, headers=HEADERS)
            with urllib.request.urlopen(req_auth, timeout=7) as response:
                token_data = json.loads(response.read())
                token = token_data.get('token')
            
            # Videó adatok kérése a tokennel
            api_url = f"https://api.redgifs.com/v2/gifs/{video_id}"
            api_headers = HEADERS.copy()
            api_headers['Authorization'] = f"Bearer {token}"
            
            req_api = urllib.request.Request(api_url, headers=api_headers)
            with urllib.request.urlopen(req_api, timeout=7) as response:
                data = json.loads(response.read())
                base_link = data.get('gif', {}).get('urls', {}).get('hd')
                
                if base_link:
                    final_url = f"{base_link}|Referer=https%3A//www.redgifs.com/&User-Agent={urllib.parse.quote(UA)}"
                    xbmc.log("NAPISZAR DEBUG: RedGifs API SIKER!", xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f"NAPISZAR API HIBA, FALLBACK: {str(e)}", xbmc.LOGWARNING)
            # Ha az API elhasal, megpróbáljuk a direkt HTML-ből (v30-as módszer)
            h = get_html(watch_url)
            if h:
                m = re.search(r'property="og:video" content="([^"]+\.mp4)"', h)
                if m:
                    final_url = m.group(1) + f"|Referer={urllib.parse.quote(watch_url)}&User-Agent={urllib.parse.quote(UA)}"

    # 2. Facebook
    elif 'facebook.com' in video_src:
        if 'video.php?href=' in video_src:
            video_src = urllib.parse.unquote(video_src.split('href=')[1].split('&')[0])
        m_url = video_src.replace('www.', 'm.').replace('facebook.com', 'm.facebook.com')
        h = get_html(m_url)
        if h:
            m = re.search(r'"browser_native_hd_url":"([^"]+)"', h) or \
                re.search(r'"browser_native_sd_url":"([^"]+)"', h)
            if m: final_url = m.group(1).replace('\\/', '/') + f"|User-Agent={urllib.parse.quote(UA)}"

    # 3. YouTube
    elif 'youtube' in video_src or 'youtu.be' in video_src:
        y_id = None
        if 'v=' in video_src: y_id = video_src.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in video_src: y_id = video_src.split('youtu.be/')[1].split('/')[-1].split('?')[0]
        if y_id: final_url = f"plugin://plugin.video.youtube/play/?video_id={y_id}"

    # 4. Közvetlen forrás keresés (Pornhub, XVideos, stb.)
    if not final_url:
        h = get_html(video_src)
        if h:
            # Pornhub/XVideos MP4 keresés
            m = re.search(r'"videoUrl":"([^"]+)"', h) or \
                re.search(r'setVideoUrlHigh\(\'([^\']+)\'', h) or \
                re.search(r'<source src="([^"]+\.mp4)"', h)
            if m:
                final_url = m.group(1).replace('\\/', '/').replace('&amp;', '&')
                if '|' not in final_url:
                    final_url += f"|User-Agent={urllib.parse.quote(UA)}"

    # 5. Végső mentőöv: ResolveURL (Ha a fentiek mind elbuknak)
    if not final_url:
        try:
            import resolveurl
            final_url = resolveurl.resolve(video_src)
        except: pass

    if final_url:
        xbmc.log(f"NAPISZAR LEJÁTSZÁS: {final_url}", xbmc.LOGINFO)
        xbmcplugin.setResolvedUrl(int(sys.argv[1]), True, xbmcgui.ListItem(path=final_url))
    else:
        xbmcgui.Dialog().notification('Hiba', 'Nem sikerült kinyerni a videót!', xbmcgui.NOTIFICATION_ERROR)

def main():
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
    a = params.get('action', 'list')
    if a == 'list': list_videos(int(params.get('page', 1)))
    elif a == 'play': play_video(params.get('url'))

if __name__ == '__main__':
    main()