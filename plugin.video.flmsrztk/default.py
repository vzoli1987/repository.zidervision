# -*- coding: utf-8 -*-
import sys
import re
import os
import json
import time
import base64
import hashlib
import threading
import traceback
import unicodedata
import urllib.parse
import urllib.request
import http.cookiejar
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import xbmcvfs

try:
    import resolveurl
except ImportError:
    resolveurl = None

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')
BASE_URL = sys.argv[0]
HANDLE = int(sys.argv[1])

SITES = {
    'fs': {'name': 'Filmek-Sorozatok.hu', 'base': 'https://www.filmek-sorozatok.hu',
           'cat_movies': '/online-filmek/', 'cat_series': '/online-sorozatok/'},
    'cn': {'name': 'CineNuovo.hu', 'base': 'https://www.cinenuovo.hu',
           'cat_movies': '/online-filmek/', 'cat_series': '/online-sorozatok/'},
}
JS_CANDIDATES = {
    'movies': ['videopass2.js', 'videopass.js', 'videopass3.js'],
    'series': ['passsorozat2.js', 'sorozatpass2.js', 'passsorozat.js', 'sorozatpass.js'],
}
DM_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')
HIST_MAX = 20
JS_TTL = 6 * 3600
LIST_TTL = 15 * 60
THEME_TTL = 24 * 3600

PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
CACHE_DIR = os.path.join(PROFILE, 'cache')
HIST_FILE = os.path.join(PROFILE, 'search_history.json')
LAST_FILE = os.path.join(PROFILE, 'last_search.json')
for _d in (PROFILE, CACHE_DIR):
    if not xbmcvfs.exists(_d):
        xbmcvfs.mkdirs(_d)

_js_cache = {}
_js_url_cache = {}
_theme_cache = {}


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON_NAME, msg), level)


# ---------------- TÁROLÁS ----------------

def _read_json(path, default):
    try:
        if xbmcvfs.exists(path):
            f = xbmcvfs.File(path)
            data = f.read()
            f.close()
            if data:
                return json.loads(data)
    except Exception as e:
        log("Tárolás olvasási hiba (%s): %s" % (path, e), xbmc.LOGWARNING)
    return default


def _write_json(path, obj):
    try:
        f = xbmcvfs.File(path, 'w')
        f.write(json.dumps(obj))
        f.close()
        return True
    except Exception as e:
        log("Tárolás írási hiba (%s): %s" % (path, e), xbmc.LOGERROR)
        return False


def get_history():
    h = _read_json(HIST_FILE, [])
    return h if isinstance(h, list) else []


def add_history(q):
    h = [x for x in get_history() if x.lower() != q.lower()]
    h.insert(0, q)
    _write_json(HIST_FILE, h[:HIST_MAX])


def clear_history():
    _write_json(HIST_FILE, [])


def get_last_search():
    d = _read_json(LAST_FILE, None)
    return d if isinstance(d, dict) and d.get('q') else None


def set_last_search(site, kind, q, url):
    _write_json(LAST_FILE, {'site': site, 'kind': kind, 'q': q, 'url': url})


# ---------------- CACHE ----------------

def cache_path(key):
    return os.path.join(CACHE_DIR, hashlib.md5(key.encode('utf-8')).hexdigest() + '.json')


def cache_get(key, ttl):
    d = _read_json(cache_path(key), None)
    if d and time.time() - d.get('ts', 0) < ttl:
        return d.get('data')
    return None


def cache_set(key, data):
    _write_json(cache_path(key), {'ts': time.time(), 'data': data})


def cache_clear():
    try:
        _, files = xbmcvfs.listdir(CACHE_DIR)
        for fn in files:
            xbmcvfs.delete(os.path.join(CACHE_DIR, fn))
    except Exception:
        pass
    _js_cache.clear()
    _js_url_cache.clear()
    _theme_cache.clear()


# ---------------- SEGÉD ----------------

def host_of(url):
    try:
        return urllib.parse.urlparse(url).netloc.replace('www.', '')
    except Exception:
        return '?'


def get_html(url):
    req = urllib.request.Request(url, headers={'User-Agent': DM_UA})
    try:
        return urllib.request.urlopen(req, timeout=15).read().decode('utf-8', 'replace')
    except Exception as e:
        log("Hálózati hiba (%s): %s" % (url, e), xbmc.LOGERROR)
        return ""


def normalize_title(s):
    s = unescape(s).lower()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9]+', ' ', s).strip()


def clean_title(title):
    title = unescape(title)
    if '|' in title:
        title = title.split('|')[0]
    title = re.sub(r'\s*x\d+\s*$', '', title, flags=re.IGNORECASE).strip()
    cleaned = re.sub(
        r'(?:[\s\-–—|:,.]*(?:teljes|online|magyarul|film|filmek|sorozat|sorozatok)\b)+$',
        '', title, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip(' -–—|:,.')
    return cleaned if len(cleaned) >= 2 else title


def norm_embed(u):
    u = unescape(u)
    if u.startswith('//'):
        return 'https:' + u
    return u


def get_theme(site):
    if site in _theme_cache:
        return _theme_cache[site]
    c = cache_get('theme:' + site, THEME_TTL)
    if c:
        _theme_cache[site] = c
        return c
    m = re.search(r'wp-content/themes/([A-Za-z0-9_-]+)/', get_html(SITES[site]['base'] + '/'))
    theme = m.group(1) if m else 'tortuga'
    _theme_cache[site] = theme
    cache_set('theme:' + site, theme)
    return theme


def find_js_url(site, source):
    ck = (site, source)
    if ck in _js_url_cache:
        return _js_url_cache[ck]
    theme = get_theme(site)
    for fname in JS_CANDIDATES[source]:
        url = '%s/wp-content/themes/%s/assets/js/%s' % (SITES[site]['base'], theme, fname)
        content = get_html(url)
        if content and re.search(r"['\"][^'\"]+['\"]\s*:\s*['\"](?:https?:)?//", content):
            _js_url_cache[ck] = url
            _js_cache[url] = content
            cache_set('js:' + url, content)
            log("JS fájl megtalálva: %s" % url)
            return url
    log("Nem található JS fájl: %s / %s" % (site, source), xbmc.LOGERROR)
    _js_url_cache[ck] = None
    return None


def get_js_content(js_url):
    if not js_url:
        return ""
    if js_url in _js_cache:
        return _js_cache[js_url]
    c = cache_get('js:' + js_url, JS_TTL)
    if c:
        _js_cache[js_url] = c
        return c
    c = get_html(js_url)
    if c:
        _js_cache[js_url] = c
        cache_set('js:' + js_url, c)
    return c


def js_url_from_html(html, site, source):
    sm = re.search(r'<script[^>]+src=["\']([^"\']*(?:videopass|sorozatpass|passsorozat)[^"\']*\.js)["\']',
                   html, re.IGNORECASE)
    if sm:
        u = unescape(sm.group(1))
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("/"):
            return SITES[site]['base'] + u
        return u
    return find_js_url(site, source)


def parse_js_library(js_content):
    items = []
    for key, url, comment in re.findall(
            r"['\"]([^'\"]+)['\"]\s*:\s*['\"]([^'\"]+)['\"](?:\s*,)?\s*(?://\s*([^\n\r]*))?", js_content):
        comment = comment.strip()
        mozis = bool(re.search(r'\bmozis\b', comment, re.IGNORECASE))
        comment = re.sub(r'\bmozis\b', '', comment, flags=re.IGNORECASE)
        title = clean_title(comment) if comment.strip() else key
        items.append({'title': title, 'url': norm_embed(url), 'key': key,
                      'mozis': mozis, 'norm': normalize_title(title)})
    return items


# ---------------- EGYSÉGES PLAYER-KINYERŐ ----------------

def extract_players(html):
    """
    Mindkét mechanizmus:
      askPassword(this,'kulcs')  -> {'key':...,'url':None}
      loadVideo/showVideo/playVideo(this,'url') -> {'key':None,'url':...}
    Sorrendben, duplikátumok nélkül.
    """
    players = []
    seen = set()
    for om in re.finditer(r'onclick=(["\'])(.*?)\1', html, re.IGNORECASE | re.DOTALL):
        call = om.group(2)
        km = re.search(r'askPassword\w*\s*\(\s*[^,]+,\s*["\']([^"\']+)["\']', call, re.IGNORECASE)
        if km:
            ident = ('k', km.group(1))
            if ident not in seen:
                seen.add(ident)
                players.append({'key': km.group(1), 'url': None})
            continue
        lm = re.search(r'(?:loadVideo|showVideo|playVideo)\w*\s*\(\s*[^,]+,\s*["\']([^"\']+)["\']',
                       call, re.IGNORECASE)
        if lm:
            u = norm_embed(lm.group(1))
            ident = ('u', u)
            if ident not in seen:
                seen.add(ident)
                players.append({'key': None, 'url': u})
    return players


def scrape_listing(url):
    c = cache_get('list:' + url, LIST_TTL)
    if c:
        return c.get('items', []), c.get('next')
    html = get_html(url)
    if not html:
        return [], None
    items = []
    for am in re.finditer(r'<article\b([^>]*)>(.*?)</article>', html, re.DOTALL | re.IGNORECASE):
        attrs, art = am.group(1), am.group(2)
        cats = re.findall(r'category-([a-z0-9-]+)', attrs, re.IGNORECASE)
        is_series = any('sorozat' in c for c in cats)
        m = re.search(r'<h[1-6][^>]*class="[^"]*entry-title[^"]*"[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                      art, re.DOTALL | re.IGNORECASE)
        if not m:
            m = re.search(r'<a[^>]*href="([^"]*)"[^>]*rel="bookmark"[^>]*>(.*?)</a>',
                          art, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        link = unescape(m.group(1))
        title = clean_title(re.sub(r'<[^>]+>', '', m.group(2)).strip())
        if not title:
            continue
        if not is_series:
            is_series = bool(re.search(r'sorozat|evad', link, re.IGNORECASE)) or \
                        bool(re.search(r'évad|sorozat', title, re.IGNORECASE))
        img = re.search(r'<img[^>]*class="[^"]*wp-post-image[^"]*"[^>]*src="([^"]*)"', art, re.IGNORECASE)
        if not img:
            img = re.search(r'<img[^>]*src="([^"]*)"', art, re.IGNORECASE)
        thumb = unescape(img.group(1)) if img else ""
        plot_m = re.search(r'<div[^>]*class="[^"]*(?:entry-summary|entry-content)[^"]*"[^>]*>(.*?)</div>',
                           art, re.DOTALL | re.IGNORECASE)
        if plot_m:
            plot = unescape(re.sub(r'<[^>]+>', ' ', plot_m.group(1)))
            plot = re.sub(r'\s+', ' ', plot).strip()
            parts = re.split(r'teljes tartalom', plot, flags=re.IGNORECASE)
            if len(parts) > 1:
                plot = parts[1].strip()
            plot = re.split(r'stáblista', plot, flags=re.IGNORECASE)[0].strip()
            if len(plot) > 300:
                plot = plot[:297] + "..."
        else:
            plot = title
        items.append({'title': title, 'url': link, 'thumb': thumb, 'plot': plot,
                      'is_series': is_series})
    next_url = None
    for tag in re.findall(r'<a\b[^>]*>', html, re.IGNORECASE):
        if re.search(r'class="[^"]*\bnext\b[^"]*"', tag, re.IGNORECASE) or \
           re.search(r'rel=["\']next["\']', tag, re.IGNORECASE):
            hm = re.search(r'href="([^"]*)"', tag)
            if hm:
                next_url = unescape(hm.group(1))
                break
    if items:
        cache_set('list:' + url, {'items': items, 'next': next_url})
    return items, next_url


def get_embed_url(page_url, site, source):
    html = get_html(page_url)
    if not html:
        return None
    players = extract_players(html)
    if players:
        p = players[0]
        if p.get('url'):
            return p['url']
        if p.get('key'):
            js = get_js_content(js_url_from_html(html, site, source))
            if js:
                um = re.search(r"['\"]%s['\"]\s*:\s*['\"]([^'\"]+)['\"]" % re.escape(p['key']), js)
                if um:
                    return norm_embed(um.group(1))
            log("Nincs URL a JS-ben ehhez: %s" % p['key'], xbmc.LOGERROR)
            return None
    im = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if im:
        return norm_embed(im.group(1))
    log("Nem található lejátszó: %s" % page_url, xbmc.LOGERROR)
    return None


def get_episodes(page_url, site):
    html = get_html(page_url)
    if not html:
        return []
    players = extract_players(html)
    lib_list = parse_js_library(get_js_content(js_url_from_html(html, site, 'series')))
    lib = {j['key']: j for j in lib_list}

    labels = {}
    for bm in re.finditer(r'<button\b[^>]*>(.*?)</button>', html, re.DOTALL | re.IGNORECASE):
        om = re.search(r'onclick=(["\'])(.*?)\1', bm.group(0), re.DOTALL | re.IGNORECASE)
        if not om:
            continue
        call = om.group(2)
        ident = None
        km = re.search(r'askPassword\w*\s*\(\s*[^,]+,\s*["\']([^"\']+)["\']', call, re.IGNORECASE)
        if km:
            ident = km.group(1)
        else:
            lm = re.search(r'(?:loadVideo|showVideo|playVideo)\w*\s*\(\s*[^,]+,\s*["\']([^"\']+)["\']',
                           call, re.IGNORECASE)
            if lm:
                ident = norm_embed(lm.group(1))
        if not ident:
            continue
        text = unescape(re.sub(r'<[^>]+>', '', bm.group(1)).strip())
        if re.fullmatch(r'\d+', text):
            text = '%s. rész' % text
        if text:
            labels[ident] = clean_title(text)

    episodes = []
    if players:
        for i, p in enumerate(players, 1):
            if p.get('url'):
                title = labels.get(p['url']) or '%d. rész' % i
                episodes.append({'title': title, 'url': p['url'], 'mozis': False})
            elif p.get('key'):
                j = lib.get(p['key'])
                if not j:
                    continue
                title = labels.get(p['key']) or (j['title'] if j['title'] != p['key'] else '') or '%d. rész' % i
                episodes.append({'title': title, 'url': j['url'], 'mozis': j.get('mozis', False)})
    else:
        title_hint = ''
        hm = re.search(r'<h1[^>]*class="[^"]*entry-title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
        if hm:
            title_hint = clean_title(re.sub(r'<[^>]+>', '', hm.group(1)).strip())
        if title_hint:
            base_norm = normalize_title(title_hint)
            series_norm = re.split(r'\s*\d+\s*(?:evad|season|resz|part)\b', base_norm)[0].strip() or base_norm
            m_ev = re.search(r'(\d+)\s*(?:evad|season)', base_norm)
            ev = m_ev.group(1) if m_ev else None
            cands = [j for j in lib_list if series_norm and series_norm in j['norm']]
            if ev and cands:
                narrowed = [j for j in cands if
                            re.search(r'\b%s\s*(?:x|evad|season)\s*\d*' % ev, j['norm']) or
                            re.search(r'\bs%s\b' % ev, j['norm'])]
                if narrowed:
                    cands = narrowed
            for i, j in enumerate(cands, 1):
                episodes.append({'title': j['title'] or '%d. rész' % i,
                                 'url': j['url'], 'mozis': j.get('mozis', False)})
    log("Epizódok találva: %d (%s)" % (len(episodes), page_url))
    return episodes


# ---------------- DAILYMOTION proxy ----------------

def b64u(s):
    return base64.urlsafe_b64encode(s.encode('utf-8')).decode('ascii').rstrip('=')


def unb64u(s):
    return base64.urlsafe_b64decode(s + '=' * (-len(s) % 4)).decode('utf-8')


def proxy_url(u, port):
    return 'http://127.0.0.1:%d/p?u=%s' % (port, b64u(u))


def rewrite_manifest(text, base_url, port):
    base_url = base_url.split('#')[0]
    base_dir = base_url.rsplit('/', 1)[0] + '/'

    def prox(u):
        absu = urllib.parse.urljoin(base_url, u)
        if absu.startswith(base_dir) and '?' not in absu and '#' not in absu:
            rel = absu[len(base_dir):]
            return 'http://127.0.0.1:%d/r/%s/%s' % (port, b64u(base_dir), rel)
        return proxy_url(absu, port)

    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('#'):
            line = re.sub(r'URI=(["\']?)([^"\',\s]+)\1',
                          lambda m: 'URI="%s"' % prox(m.group(2)), line)
            out.append(line)
        elif s:
            out.append(prox(s))
        else:
            out.append(line)
    return '\n'.join(out) + '\n'


class DMProxyHandler(BaseHTTPRequestHandler):
    dm_headers = {}
    dm_cookie = ''
    last_base = ''

    def log_message(self, *a):
        pass

    def _resolve(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        if 'u' in q:
            return unb64u(q['u'][0])
        if parsed.path.startswith('/r/'):
            parts = parsed.path[3:].split('/', 1)
            base = unb64u(parts[0])
            rel = parts[1] if len(parts) > 1 else ''
            return urllib.parse.urljoin(base, rel)
        if DMProxyHandler.last_base:
            return urllib.parse.urljoin(DMProxyHandler.last_base, parsed.path.lstrip('/'))
        raise KeyError('u')

    def do_GET(self):
        try:
            u = self._resolve()
            hdrs = dict(self.dm_headers)
            if self.dm_cookie:
                hdrs['Cookie'] = self.dm_cookie
            if self.headers.get('Range'):
                hdrs['Range'] = self.headers.get('Range')
            resp = urllib.request.urlopen(urllib.request.Request(u, headers=hdrs), timeout=30)
            data = resp.read()
            ctype = resp.headers.get('Content-Type', '')
            final = resp.geturl()
            if 'mpegurl' in ctype or u.split('?')[0].split('#')[0].endswith('.m3u8'):
                text = data.decode('utf-8', 'replace')
                if '#EXTINF' in text:
                    DMProxyHandler.last_base = final
                data = rewrite_manifest(text, final, self.server.server_address[1]).encode('utf-8')
                ctype = 'application/vnd.apple.mpegurl'
                self.send_response(200)
            else:
                self.send_response(getattr(resp, 'status', 200) or 200)
                for h in ('Content-Range', 'Accept-Ranges'):
                    v = resp.headers.get(h)
                    if v:
                        self.send_header(h, v)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            log("Proxy hiba: %s (%s)" % (e, self.path), xbmc.LOGERROR)
            try:
                self.send_response(502)
                self.end_headers()
            except Exception:
                pass


def start_proxy(headers, cookie):
    DMProxyHandler.dm_headers = headers
    DMProxyHandler.dm_cookie = cookie
    DMProxyHandler.last_base = ''
    srv = ThreadingHTTPServer(('127.0.0.1', 0), DMProxyHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait_playback_end(start_timeout=20):
    mon = xbmc.Monitor()
    player = xbmc.Player()
    for _ in range(start_timeout):
        if player.isPlaying() or mon.abortRequested():
            break
        if mon.waitForAbort(1):
            return
    while not mon.abortRequested() and player.isPlaying():
        if mon.waitForAbort(1):
            return


def keep_alive(srv):
    wait_playback_end()
    try:
        srv.shutdown()
        srv.server_close()
    except Exception:
        pass


def go_back(url):
    try:
        xbmc.executebuiltin('Container.Update(%s)' % url)
    except Exception as e:
        log("Visszaugrás hiba: %s" % e, xbmc.LOGERROR)


def dm_video_id(url):
    m = re.search(r'dailymotion\.com/(?:embed/)?video/([A-Za-z0-9]+)', url)
    if not m:
        m = re.search(r'[?&]video=([A-Za-z0-9]+)', url)
    return m.group(1) if m else None


def resolve_dailymotion(embed_url):
    vid = dm_video_id(embed_url)
    if not vid:
        return None
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    geo = 'geo.dailymotion' in embed_url
    ref = 'https://geo.dailymotion.com/' if geo else 'https://www.dailymotion.com/'
    headers = {'User-Agent': DM_UA, 'Referer': ref, 'Origin': ref.rstrip('/')}
    try:
        op.open(urllib.request.Request('https://www.dailymotion.com/',
                                       headers={'User-Agent': DM_UA}), timeout=10)
    except Exception:
        pass
    cookie = '; '.join('%s=%s' % (c.name, c.value) for c in cj)
    data = None
    for attempt_id in (vid, None):
        if attempt_id is None:
            break
        try:
            r = op.open(urllib.request.Request(
                'https://www.dailymotion.com/player/metadata/video/%s' % attempt_id,
                headers=headers), timeout=15)
            data = json.loads(r.read().decode('utf-8', 'replace'))
        except Exception as e:
            log("DM metadata hiba: %s" % e, xbmc.LOGERROR)
            data = None
        if data:
            qualities = data.get('qualities') or {}
            for q in ('1080', '720', '480', '380', '240', '144'):
                for s in qualities.get(q) or []:
                    if s.get('type') == 'video/mp4' and s.get('url'):
                        log("DM muxolt MP4: %s" % q)
                        return {'url': s['url'], 'kind': 'mp4',
                                'headers': headers, 'cookie': cookie}
            xid = data.get('id') or data.get('video_id')
            if xid and xid != attempt_id:
                attempt_id = xid
                continue
            break
    if not data:
        return None
    for s in (data.get('qualities') or {}).get('auto') or []:
        if s.get('url') and 'mpegURL' in (s.get('type') or ''):
            hls = s['url']
            for hdrs in (headers,
                         {'User-Agent': DM_UA, 'Referer': 'https://www.dailymotion.com/'},
                         {'User-Agent': DM_UA}):
                try:
                    r = op.open(urllib.request.Request(hls, headers=hdrs), timeout=15)
                    txt = r.read().decode('utf-8', 'replace')
                    if '#EXTM3U' in txt:
                        log("DM HLS master (Python TLS OK)")
                        return {'url': r.geturl(), 'kind': 'hls',
                                'headers': hdrs, 'cookie': cookie}
                except Exception as e:
                    log("DM HLS próba hiba: %s" % e, xbmc.LOGWARNING)
    return None


# ---------------- LISTÁK / LEJÁTSZÁS ----------------

def add_play_item(item, site, source, direct=False, back=None):
    label = item['title']
    if item.get('mozis'):
        label += ' [COLOR yellow][MOZIS][/COLOR]'
    if direct:
        label += ' [COLOR grey](%s)[/COLOR]' % host_of(item['url'])
        action, is_folder = 'play', False
    elif source == 'series':
        action, is_folder = 'episodes', True
    else:
        action, is_folder = 'play', False
    url = "%s?action=%s&url=%s&site=%s&source=%s&direct=%d" % (
        BASE_URL, action, urllib.parse.quote(item['url'], safe=''), site, source, 1 if direct else 0)
    if action == 'episodes':
        url += "&thumb=%s" % urllib.parse.quote(item.get('thumb') or '', safe='')
    if back:
        url += "&back=%s" % urllib.parse.quote(back, safe='')
    li = xbmcgui.ListItem(label=label)
    li.setArt({'thumb': item.get('thumb') or 'DefaultMovies.png',
               'icon': item.get('thumb') or 'DefaultMovies.png',
               'poster': item.get('thumb') or 'DefaultMovies.png'})
    if not is_folder:
        li.setProperty('IsPlayable', 'true')
    li.setInfo('video', {'title': item['title'], 'plot': item.get('plot') or item['title']})
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=is_folder)


def list_category(url, site, source):
    items, next_url = scrape_listing(url)
    direct = False
    if not items:
        log("HTML lista üres, visszaesés a JS könyvtárra: %s / %s" % (site, source), xbmc.LOGWARNING)
        js_url = find_js_url(site, source)
        items = parse_js_library(get_js_content(js_url)) if js_url else []
        direct = True
        next_url = None
    else:
        js_url = find_js_url(site, source)
        mozis_map = {j['norm']: j for j in parse_js_library(get_js_content(js_url))
                     if j.get('mozis')} if js_url else {}
        if mozis_map:
            for item in items:
                norm = normalize_title(item['title'])
                j = mozis_map.get(norm)
                if not j:
                    for k, v in mozis_map.items():
                        if k and (k in norm or norm in k):
                            j = v
                            break
                if j:
                    item['mozis'] = True
    if not items:
        xbmcgui.Dialog().ok(ADDON_NAME, "Nem található tartalom ezen az oldalon.")
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for item in items:
        add_play_item(item, site, source, direct=direct)
    if next_url:
        li_next = xbmcgui.ListItem(label="[COLOR yellow]Következő oldal >>[/COLOR]")
        li_next.setArt({'thumb': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(
            HANDLE, "%s?action=list&url=%s&site=%s&source=%s" % (
                BASE_URL, urllib.parse.quote(next_url, safe=''), site, source), li_next, isFolder=True)
    xbmcplugin.setContent(HANDLE, 'movies' if source == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(HANDLE)


def list_search(site, kind, q, url=None):
    page_url = url or (SITES[site]['base'] + '/?s=' + urllib.parse.quote(q))
    set_last_search(site, kind, q, page_url)
    back_url = "%s?action=search_results&site=%s&kind=%s&q=%s&url=%s" % (
        BASE_URL, site, kind, urllib.parse.quote(q, safe=''), urllib.parse.quote(page_url, safe=''))
    want_series = (kind == 'series')
    items, next_url = scrape_listing(page_url)
    tries = 0
    while not [i for i in items if i.get('is_series') == want_series] and next_url and tries < 5:
        page_url = next_url
        items, next_url = scrape_listing(page_url)
        tries += 1
    items = [i for i in items if i.get('is_series') == want_series]
    if not items and not next_url:
        xbmcgui.Dialog().ok(ADDON_NAME, "Nincs %s találat: %s" % (
            'sorozat' if want_series else 'film', q))
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for item in items:
        add_play_item(item, site, 'series' if want_series else 'movies', back=back_url)
    if next_url:
        li_next = xbmcgui.ListItem(label="[COLOR yellow]Következő oldal >>[/COLOR]")
        li_next.setArt({'thumb': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(
            HANDLE, "%s?action=search_results&site=%s&kind=%s&q=%s&url=%s" % (
                BASE_URL, site, kind, urllib.parse.quote(q, safe=''),
                urllib.parse.quote(next_url, safe='')), li_next, isFolder=True)
    xbmcplugin.setContent(HANDLE, 'tvshows' if want_series else 'movies')
    xbmcplugin.endOfDirectory(HANDLE)


def search_menu(site, kind):
    li = xbmcgui.ListItem(label="[COLOR yellow]Új keresés…[/COLOR]")
    li.setArt({'thumb': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(
        HANDLE, "%s?action=search_input&site=%s&kind=%s" % (BASE_URL, site, kind), li, isFolder=True)
    for q in get_history():
        li = xbmcgui.ListItem(label=q)
        li.setArt({'thumb': 'DefaultAddonsSearch.png'})
        xbmcplugin.addDirectoryItem(
            HANDLE, "%s?action=search_results&site=%s&kind=%s&q=%s" % (
                BASE_URL, site, kind, urllib.parse.quote(q, safe='')), li, isFolder=True)
    if get_history():
        li = xbmcgui.ListItem(label="[COLOR red]Előzmények törlése[/COLOR]")
        li.setArt({'thumb': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(
            HANDLE, "%s?action=search_clear&site=%s&kind=%s" % (BASE_URL, site, kind), li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def search_input(site, kind):
    kb = xbmc.Keyboard('', 'Keresés (%s) - %s' % (
        'sorozatok' if kind == 'series' else 'filmek', SITES[site]['name']))
    kb.doModal()
    if not kb.isConfirmed():
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    q = kb.getText().strip()
    if not q:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    add_history(q)
    list_search(site, kind, q)


def list_episodes(page_url, site, thumb='', back=None):
    episodes = get_episodes(page_url, site)
    if not episodes:
        xbmcgui.Dialog().ok(ADDON_NAME, "Nem találhatók epizódok ezen az oldalon.")
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for ep in episodes:
        ep['thumb'] = thumb
        ep['plot'] = ep['title']
        add_play_item(ep, site, 'series', direct=True, back=back)
    xbmcplugin.setContent(HANDLE, 'episodes')
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(HANDLE)


def play_video(url, site, source, direct=False, via_player=False, back=None):
    if not resolveurl:
        xbmcgui.Dialog().ok(ADDON_NAME, "Hiba: a 'script.module.resolveurl' nincs telepítve!")
        if not via_player:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    dialog = xbmcgui.DialogProgress()
    dialog.create(ADDON_NAME, "Videó előkészítése...")
    srv = None
    try:
        stream_url, kind = None, None
        if direct:
            embed_url = url
        else:
            dialog.update(30, "Videó kulcs keresése...")
            embed_url = get_embed_url(url, site, source)
        if not embed_url:
            dialog.close()
            xbmcgui.Dialog().ok(ADDON_NAME, "Nem sikerült megtalálni a videó forrását.")
            if not via_player:
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        host = host_of(embed_url)
        dm = ('dailymotion.' in embed_url) or ('dmcdn' in embed_url)
        if dm:
            dialog.update(60, "Dailymotion előkészítése (proxy)... [%s]" % host)
            info = resolve_dailymotion(embed_url)
            if info:
                srv = start_proxy(info['headers'], info['cookie'])
                stream_url = proxy_url(info['url'], srv.server_address[1])
                kind = info['kind']
        if not stream_url:
            dialog.update(70, "Stream feloldása... [%s]" % host)
            stream_url = resolveurl.resolve(embed_url)
        dialog.close()
        if not stream_url:
            xbmcgui.Dialog().ok(ADDON_NAME, "A videó forrása nem elérhető.")
            if not via_player:
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        if not kind:
            kind = 'hls' if '.m3u8' in stream_url else 'mp4'
        li = xbmcgui.ListItem(path=stream_url)
        li.setProperty('IsPlayable', 'true')
        li.setContentLookup(False)
        if kind == 'hls':
            li.setProperty('inputstream', 'inputstream.adaptive')
            li.setMimeType('application/vnd.apple.mpegurl')
        else:
            li.setMimeType('video/mp4')
        log("Lejátszás (%s) host: %s -> %s" % (kind, host, stream_url))
        xbmcgui.Dialog().notification(ADDON_NAME, 'Host: %s' % host,
                                      xbmcgui.NOTIFICATION_INFO, 2500)
        if via_player:
            xbmc.Player().play(stream_url, li)
        else:
            xbmcplugin.setResolvedUrl(HANDLE, True, li)
        if srv:
            keep_alive(srv)
        elif back:
            wait_playback_end()
        if back:
            go_back(back)
    except Exception as e:
        dialog.close()
        log("Lejátszási hiba: %s\n%s" % (e, traceback.format_exc()), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(ADDON_NAME, "Hiba: %s" % e)
        if not via_player:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        if srv:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass


def site_menu(site):
    li_m = xbmcgui.ListItem(label="Filmek")
    li_m.setArt({'thumb': 'DefaultMovies.png'})
    xbmcplugin.addDirectoryItem(HANDLE, "%s?action=list&site=%s&source=movies" % (BASE_URL, site),
                                li_m, isFolder=True)
    li_s = xbmcgui.ListItem(label="Sorozatok")
    li_s.setArt({'thumb': 'DefaultTVShows.png'})
    xbmcplugin.addDirectoryItem(HANDLE, "%s?action=list&site=%s&source=series" % (BASE_URL, site),
                                li_s, isFolder=True)
    ls = get_last_search()
    if ls:
        li = xbmcgui.ListItem(label="[COLOR yellow]Legutóbbi keresés: %s[/COLOR]" % ls.get('q', ''))
        li.setArt({'thumb': 'DefaultAddonsSearch.png'})
        xbmcplugin.addDirectoryItem(
            HANDLE, "%s?action=search_results&site=%s&kind=%s&q=%s&url=%s" % (
                BASE_URL, ls.get('site', site), ls.get('kind', 'movies'),
                urllib.parse.quote(ls.get('q', ''), safe=''),
                urllib.parse.quote(ls.get('url', ''), safe='')), li, isFolder=True)
    li_km = xbmcgui.ListItem(label="[COLOR yellow]Keresés: Filmek[/COLOR]")
    li_km.setArt({'thumb': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(HANDLE, "%s?action=search&site=%s&kind=movies" % (BASE_URL, site),
                                li_km, isFolder=True)
    li_ks = xbmcgui.ListItem(label="[COLOR yellow]Keresés: Sorozatok[/COLOR]")
    li_ks.setArt({'thumb': 'DefaultAddonsSearch.png'})
    xbmcplugin.addDirectoryItem(HANDLE, "%s?action=search&site=%s&kind=series" % (BASE_URL, site),
                                li_ks, isFolder=True)
    li_c = xbmcgui.ListItem(label="Cache törlése")
    li_c.setArt({'thumb': 'DefaultFolder.png'})
    xbmcplugin.addDirectoryItem(HANDLE, "%s?action=cache_clear&site=%s" % (BASE_URL, site),
                                li_c, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def main_menu():
    for key, cfg in SITES.items():
        li = xbmcgui.ListItem(label=cfg['name'])
        li.setArt({'thumb': 'DefaultFolder.png'})
        xbmcplugin.addDirectoryItem(HANDLE, "%s?action=site_menu&site=%s" % (BASE_URL, key),
                                    li, isFolder=True)
    xbmcplugin.endOfDirectory(HANDLE)


def router(paramstring):
    params = dict(urllib.parse.parse_qsl(paramstring))
    action = params.get('action')
    site = params.get('site', 'fs')
    source = params.get('source', 'movies')
    kind = params.get('kind', 'movies')
    back = params.get('back')
    if action == 'play':
        play_video(params.get('url'), site, source, direct=params.get('direct') == '1', back=back)
    elif action == 'episodes':
        list_episodes(params.get('url'), site, params.get('thumb', ''), back=back)
    elif action == 'list':
        list_category(params.get('url') or (SITES[site]['base'] + SITES[site]['cat_' + source]),
                      site, source)
    elif action == 'search':
        search_menu(site, kind)
    elif action == 'search_input':
        search_input(site, kind)
    elif action == 'search_results':
        list_search(site, kind, params.get('q', ''), params.get('url'))
    elif action == 'search_clear':
        clear_history()
        search_menu(site, kind)
    elif action == 'cache_clear':
        cache_clear()
        xbmcgui.Dialog().notification(ADDON_NAME, 'Cache törölve', xbmcgui.NOTIFICATION_INFO, 2000)
        site_menu(site)
    elif action == 'site_menu':
        site_menu(site)
    else:
        main_menu()


if __name__ == '__main__':
    try:
        router(sys.argv[2][1:])
    except Exception as e:
        log("Végzetes hiba: %s\n%s" % (e, traceback.format_exc()), xbmc.LOGERROR)
        xbmcgui.Dialog().ok(ADDON_NAME, "Hiba: %s" % e)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)