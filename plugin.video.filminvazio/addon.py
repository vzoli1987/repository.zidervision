# -*- coding: utf-8 -*-
"""Filminvazio Kodi 21.3 plugin.

This addon consumes only public HTML and embedded URLs exposed by the site.
It does not bypass DRM, authentication, CAPTCHA, or access controls.
"""
from __future__ import absolute_import

import hashlib
import html
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urlencode, urljoin, urlparse, urlunparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

try:
    import resolveurl
except ImportError:
    resolveurl = None

BASE = 'https://filminvazio.pro/'
HANDLE = int(sys.argv[1])
ADDON = xbmcaddon.Addon()
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36'
ALT_UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36'
SEARCH_NONCE = 'f620484b8f'
CACHE_TTL = 15 * 60
MIRROR_CACHE_TTL = 6 * 60 * 60
SAVED_SEARCH_LIMIT = 20
PROFILE = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
CACHE_DIR = os.path.join(PROFILE, 'cache')
SAVED_SEARCHES_FILE = os.path.join(PROFILE, 'saved_searches.json')
if not xbmcvfs.exists(PROFILE):
    xbmcvfs.mkdirs(PROFILE)
if not xbmcvfs.exists(CACHE_DIR):
    xbmcvfs.mkdirs(CACHE_DIR)


def cache_ttl(url):
    host = urlparse(url).netloc.lower()
    if host == 'filminvazio.pro' or host.endswith('.filminvazio.pro'):
        return CACHE_TTL
    if host == 'videaletoltes.com' or host.endswith('.videaletoltes.com'):
        return MIRROR_CACHE_TTL
    return 0


def cache_path(url):
    key = hashlib.sha256(url.encode('utf-8')).hexdigest()
    return os.path.join(CACHE_DIR, key + '.json')


def read_cached(url, ttl):
    if not ttl:
        return None
    path = cache_path(url)
    try:
        if time.time() - os.path.getmtime(path) > ttl:
            return None
        with open(path, 'r', encoding='utf-8') as handle:
            return json.load(handle).get('body')
    except (IOError, OSError, ValueError, TypeError):
        return None


def write_cached(url, body):
    try:
        with open(cache_path(url), 'w', encoding='utf-8') as handle:
            json.dump({'url': url, 'body': body}, handle, ensure_ascii=False)
    except (IOError, OSError, TypeError) as exc:
        xbmc.log('Filminvazio cache write failed: %s' % exc, xbmc.LOGDEBUG)


def load_saved_searches():
    try:
        with open(SAVED_SEARCHES_FILE, 'r', encoding='utf-8') as handle:
            values = json.load(handle)
        return values if isinstance(values, list) else []
    except (IOError, OSError, ValueError, TypeError):
        return []


def save_search(term):
    term = clean(term)
    if not term:
        return
    values = [item for item in load_saved_searches() if item.lower() != term.lower()]
    values.insert(0, term)
    try:
        with open(SAVED_SEARCHES_FILE, 'w', encoding='utf-8') as handle:
            json.dump(values[:SAVED_SEARCH_LIMIT], handle, ensure_ascii=False)
    except (IOError, OSError, TypeError) as exc:
        xbmc.log('Filminvazio saved search write failed: %s' % exc, xbmc.LOGDEBUG)


def clear_cache():
    removed = 0
    try:
        for name in os.listdir(CACHE_DIR):
            path = os.path.join(CACHE_DIR, name)
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
        if os.path.exists(SAVED_SEARCHES_FILE):
            os.remove(SAVED_SEARCHES_FILE)
    except (IOError, OSError) as exc:
        xbmc.log('Filminvazio cache clear failed: %s' % exc, xbmc.LOGWARNING)
    xbmcgui.Dialog().notification('Filminvazio', 'Gyorsítótár törölve: %d fájl' % removed, xbmcgui.NOTIFICATION_INFO)
    finish()


def get_page(url):
    ttl = cache_ttl(url)
    cached = read_cached(url, ttl)
    if cached is not None:
        xbmc.log('Filminvazio cache hit: %s' % url, xbmc.LOGDEBUG)
        return cached
    last_error = None
    for agent in (UA, ALT_UA):
        headers = {
            'User-Agent': agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'hu-HU,hu;q=0.9,en;q=0.8',
            'Referer': BASE,
            'Cache-Control': 'no-cache',
            'Connection': 'close'
        }
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=20) as response:
                body = response.read().decode('utf-8', 'replace')
                if ttl:
                    write_cached(url, body)
                return body
        except HTTPError as exc:
            last_error = exc
            xbmc.log('Filminvazio HTTP %s for %s using %s' % (exc.code, url, agent), xbmc.LOGWARNING)
            if exc.code < 500:
                raise
        except URLError as exc:
            last_error = exc
            xbmc.log('Filminvazio network error for %s: %s' % (url, exc), xbmc.LOGWARNING)
    if last_error:
        raise last_error
    raise RuntimeError('Filminvazio request failed')


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(value or '')).strip()


def final_url(url):
    try:
        req = Request(url, headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': 'https://videaletoltes.com/',
            'Connection': 'close'
        })
        with urlopen(req, timeout=15) as response:
            body = response.read().decode('utf-8', 'replace')
            # Submitted links use an intermediate HTML page, not an HTTP
            # redirect. Extract the external provider anchor from that page.
            for href in re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>', body, re.IGNORECASE):
                candidate = urljoin(url, html.unescape(href))
                host = urlparse(candidate).netloc.lower()
                if host and 'videaletoltes.com' not in host:
                    return candidate
            return response.geturl()
    except Exception as exc:
        xbmc.log('Filminvazio link redirect failed for %s: %s' % (url, exc), xbmc.LOGDEBUG)
        return url


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items = []
        self.current = None
        self.in_anchor = False
        self.in_heading = False
        self.heading_text = []
        self.img_src = ''
        self.anchor_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and '/videa-film/' in attrs.get('href', ''):
            candidate_url = urljoin(BASE, attrs['href'])
            candidate_path = urlparse(candidate_url).path
            if candidate_path.rstrip('/') == '/videa-film' or re.search(r'/page/\d+/?$', candidate_path):
                return
            self.in_anchor = True
            self.current = {'url': candidate_url, 'title': '', 'thumb': ''}
            self.anchor_text = []
        elif self.in_anchor and tag == 'img':
            self.current['thumb'] = attrs.get('src', '')
        if tag in ('h1', 'h2', 'h3'):
            self.in_heading = True
            self.heading_text = []

    def handle_data(self, data):
        if self.in_anchor:
            self.anchor_text.append(data)
        if self.in_heading:
            self.heading_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.in_anchor:
            self.current['title'] = clean(' '.join(self.anchor_text))
            existing = next((x for x in self.items if x['url'] == self.current['url']), None)
            if self.current['title'] and not self.current['title'].isdigit():
                if existing is None:
                    self.items.append(self.current)
                elif existing['title'].lower() in ('film', '') and self.current['title'].lower() not in ('film', ''):
                    existing['title'] = self.current['title']
            self.current = None
            self.in_anchor = False
        if tag in ('h1', 'h2', 'h3'):
            self.in_heading = False


class DetailParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.poster = ''
        self.description = []
        self.all_text = []
        self.media = []
        self.genres = []
        self.in_genre = False
        self.genre_text = []
        self.ready_for_genres = False
        self.genre_locked = False
        self.in_h1 = False
        self.in_desc = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        src = attrs.get('src', '')
        if tag == 'h1':
            self.in_h1 = True
            self.text = []
        if tag == 'img' and not self.poster and ('upload' in src or 'tmdb' in src):
            self.poster = urljoin(BASE, src)
        if tag in ('p', 'div') and ('description' in attrs.get('class', '') or attrs.get('id') in ('info', 'desc')):
            self.in_desc = True
        if tag == 'a' and self.ready_for_genres and not self.genre_locked and '/online-filmek/' in attrs.get('href', ''):
            self.in_genre = True
            self.genre_text = []
        if tag in ('iframe', 'video', 'source'):
            candidate = attrs.get('src') or attrs.get('data-src') or attrs.get('data-url')
            if candidate:
                candidate = urljoin(BASE, candidate)
                if candidate not in self.media:
                    self.media.append(candidate)

    def handle_data(self, data):
        self.all_text.append(data)
        if clean(data).upper() == 'FILMINFÓ':
            self.genre_locked = True
            self.in_genre = False
        if self.in_h1:
            self.text.append(data)
        if self.in_desc:
            self.description.append(data)
        if self.in_genre:
            self.genre_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'h1' and self.in_h1:
            self.title = clean(' '.join(self.text))
            self.in_h1 = False
            self.ready_for_genres = True
        if tag in ('p', 'div'):
            self.in_desc = False
        if tag == 'a' and self.in_genre:
            genre = clean(' '.join(self.genre_text))
            if genre and genre not in self.genres:
                self.genres.append(genre)
            self.in_genre = False


class SourceTableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cells = []
        self.cell_text = []
        self.row_url = ''
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'table':
            self.in_table = True
        elif self.in_table and tag == 'tr':
            self.in_row = True
            self.cells = []
            self.row_url = ''
        elif self.in_row and tag in ('td', 'th'):
            self.in_cell = True
            self.cell_text = []
        elif self.in_row and tag == 'a' and attrs.get('href'):
            self.row_url = urljoin('https://videaletoltes.com/', attrs['href'])

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text.append(data)

    def handle_endtag(self, tag):
        if self.in_row and self.in_cell and tag in ('td', 'th'):
            self.cells.append(clean(' '.join(self.cell_text)))
            self.in_cell = False
        elif self.in_table and tag == 'tr':
            if len(self.cells) >= 3 and self.row_url and self.cells[0].lower() not in ('watch online', 'watch'):
                self.rows.append({
                    'host': self.cells[0],
                    'quality': self.cells[1],
                    'language': self.cells[2],
                    'clicks': self.cells[3] if len(self.cells) > 3 else '',
                    'submitted': self.cells[4] if len(self.cells) > 4 else '',
                    'url': self.row_url,
                })
            self.in_row = False
        elif tag == 'table':
            self.in_table = False


def add_item(label, url, folder, thumb='', info=None):
    item = xbmcgui.ListItem(label=label)
    if thumb:
        item.setArt({'thumb': thumb, 'poster': thumb, 'fanart': thumb})
    if info:
        item.setInfo('video', info)
    item.setProperty('IsPlayable', 'true' if not folder else 'false')
    xbmcplugin.addDirectoryItem(HANDLE, url, item, folder)


def finish(content='videos'):
    xbmcplugin.setContent(HANDLE, content)
    xbmcplugin.endOfDirectory(HANDLE)


def route_url(**params):
    query = urlencode(params)
    return sys.argv[0] + '?' + query if query else sys.argv[0]


CATEGORIES = [
    ('Akció', 'akcio-filmek-online'), ('Animációs', 'animacios'),
    ('Bűnügyi', 'bunugyi'), ('Családi', 'csaladi'), ('Dokumentum', 'dokumentum'),
    ('Dráma', 'drama'), ('Életrajzi', 'eletrajzi'), ('Fantasy', 'fantasy'),
    ('Háborús', 'haborus'), ('Harcművészeti', 'harcmuveszeti'), ('Horror', 'horror'),
    ('Kaland', 'kaland'), ('Karácsonyi', 'karacsonyi'), ('Katasztrófa', 'katasztrofa'),
    ('Mese filmek', 'animacio-filmek-online'), ('Misztikus', 'misztikus'),
    ('Premier filmek', 'premier-filmek'), ('Rejtély', 'rejtely'),
    ('Romantikus', 'romantikus'), ('Sci-Fi', 'sci-fi'), ('Sport', 'sport'),
    ('Thriller', 'thriller'), ('Történelmi', 'tortenelmi'), ('TV film', 'tv-film'),
    ('Vígjáték', 'vigjatek'), ('Western', 'western'), ('Zenei', 'zenei')
]
YEARS = list(range(2026, 1977, -1))


def home():
    add_item('Filmek', route_url(mode='catalog', url=urljoin(BASE, 'videa-film/')), True)
    add_item('Kategóriák', route_url(mode='categories'), True)
    add_item('Évek', route_url(mode='years'), True)
    add_item('Keresés', route_url(mode='search'), True)
    add_item('Korábbi keresések', route_url(mode='saved_searches'), True)
    add_item('[COLOR orange]Gyorsítótár törlése[/COLOR]', route_url(mode='clear_cache'), False)
    finish()


def saved_searches():
    values = load_saved_searches()
    if not values:
        xbmcgui.Dialog().notification('Filminvazio', 'Nincs mentett keresés', xbmcgui.NOTIFICATION_INFO)
    for term in values:
        add_item(term, route_url(mode='saved_search', term=term), True)
    finish('movies')


def categories():
    for label, slug in CATEGORIES:
        add_item(label, route_url(mode='catalog', url=urljoin(BASE, 'online-filmek/%s/' % slug)), True)
    finish('videos')


def years():
    for year in YEARS:
        add_item(str(year), route_url(mode='catalog', url=urljoin(BASE, 'filmek/%s/' % year)), True)
    finish('videos')


def page_number(url):
    match = re.search(r'/page/(\d+)(?:/|$)', urlparse(url).path)
    return int(match.group(1)) if match else 1


def page_url(url, page):
    parsed = urlparse(url)
    path = re.sub(r'/page/\d+/?', '/', parsed.path)
    path = path.rstrip('/') + '/' if not path.endswith('/') else path
    if page > 1:
        path = path.rstrip('/') + '/page/%d/' % page
    return urlunparse((parsed.scheme, parsed.netloc, path, '', parsed.query, ''))


def catalog(url):
    try:
        source = get_page(url)
        parser = CatalogParser()
        parser.feed(source)
        current_page = page_number(url)
        total_match = re.search(r'Page\s+\d+\s+of\s+(\d+)', source, re.IGNORECASE)
        total_pages = int(total_match.group(1)) if total_match else None

        for item in parser.items:
            add_item(item['title'], route_url(mode='detail', url=item['url']), True, item['thumb'])

        # Site-style pager at the bottom. Page count is part of the
        # clickable navigation label; there is no separate page-count row.
        page_info = ' [COLOR lime](Oldal %d / %s)[/COLOR]' % (current_page, total_pages or '?')
        if parser.items and (total_pages is None or current_page < total_pages):
            add_item('[COLOR skyblue]Következő oldal »[/COLOR]' + page_info,
                     route_url(mode='catalog', url=page_url(url, current_page + 1)), True)
        if not parser.items:
            xbmcgui.Dialog().notification('Filminvazio', 'Nincs találat vagy a webhely nem érhető el', xbmcgui.NOTIFICATION_WARNING)
    except Exception as exc:
        xbmc.log('Filminvazio catalog error: %s' % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().notification('Filminvazio', 'Katalógus betöltési hiba', xbmcgui.NOTIFICATION_ERROR)
    finish()


def search_nonce():
    try:
        source = get_page(BASE)
        match = re.search(r'"nonce"\s*:\s*"([a-zA-Z0-9]+)"', source)
        if match:
            return match.group(1)
    except Exception as exc:
        xbmc.log('Filminvazio nonce fetch failed: %s' % exc, xbmc.LOGDEBUG)
    return SEARCH_NONCE


def live_search(term):
    api_url = urljoin(BASE, 'wp-json/dooplay/search/')
    query = urlencode({'keyword': term, 'nonce': search_nonce()})
    data = json.loads(get_page(api_url + '?' + query))
    if not isinstance(data, dict) or 'error' in data:
        return False
    count = 0
    for entry in data.values():
        if not isinstance(entry, dict) or not entry.get('url') or not entry.get('title'):
            continue
        extra = entry.get('extra') or {}
        info = {'title': entry['title'], 'mediatype': 'movie'}
        if extra.get('date'):
            info['year'] = int(extra['date']) if str(extra['date']).isdigit() else extra['date']
        if extra.get('imdb'):
            try:
                info['rating'] = float(extra['imdb'])
            except (TypeError, ValueError):
                pass
        add_item(entry['title'], route_url(mode='detail', url=entry['url']), True, entry.get('img', ''), info)
        count += 1
    if count:
        finish('movies')
        return True
    return False


def search():
    keyboard = xbmc.Keyboard('', 'Film kereső')
    keyboard.doModal()
    if not keyboard.isConfirmed():
        return finish()
    term = keyboard.getText().strip()
    if not term:
        return finish()
    save_search(term)
    try:
        if live_search(term):
            return
    except Exception as exc:
        xbmc.log('Filminvazio live search error: %s' % exc, xbmc.LOGWARNING)
    catalog(urljoin(BASE, '?' + urlencode({'s': term})))


def provider_name(url):
    host = urlparse(url).netloc.lower().split('@')[-1].split(':')[0]
    if host.startswith('www.'):
        host = host[4:]
    return host or 'ismeretlen szolgáltató'


def is_trailer_url(url):
    host = provider_name(url)
    return host in ('youtube.com', 'youtu.be') or host.endswith('.youtube.com')


def duration_label(text):
    match = re.search(r'(\d+)\s*(?:perc|min|minutes?)', clean(text).lower())
    if not match:
        return '--:--:--'
    total = int(match.group(1)) * 60
    return '%d:%02d:00' % (total // 3600, (total % 3600) // 60)


def source_label(index, host, language, quality, duration):
    return '%02d | [B]%s[/B] | [COLOR lime]%s[/COLOR] | [COLOR skyblue]%s[/COLOR] | %s' % (index, host, language or '--', quality or '--', duration or '--:--:--')


def trailer_label(host, language, quality, duration):
    return '[COLOR orange][B]Előzetes[/B][/COLOR] | [B]%s[/B] | [COLOR lime]%s[/COLOR] | [COLOR orange]Előzetes[/COLOR] | [COLOR grey]%s[/COLOR]' % (host, language or '--', duration or '--:--:--')


def resolveurl_compatible(url):
    if not resolveurl:
        return False
    try:
        media = resolveurl.HostedMediaFile(url)
        if not media:
            return False
        # ResolveURL can recognize a host even when its optional valid_url
        # preflight rejects a redirect-style URL. Let resolve() decide playback.
        return True
    except Exception as exc:
        xbmc.log('Filminvazio compatibility check failed for %s: %s' % (url, exc), xbmc.LOGDEBUG)
        return False


def extract_plot(source):
    marker = re.search(r'teljes\s+film\s+le[ií]r[aá]s\s+magyarul\s*,?\s*videa\s*/\s*indavideo', source, re.IGNORECASE)
    if not marker:
        return ''
    tail = source[marker.end():]
    paragraph = re.search(r'<p\b[^>]*>(.*?)</p\s*>', tail, re.IGNORECASE | re.DOTALL)
    if not paragraph:
        return ''
    text = re.sub(r'<[^>]+>', ' ', paragraph.group(1))
    return clean(html.unescape(text))


def detail_metadata(parser, title, duration):
    text = clean(' '.join(parser.all_text))
    title_year = re.search(re.escape(title) + r'\s+(19\d{2}|20\d{2})\s+online', text, re.IGNORECASE)
    year = title_year.group(1) if title_year else ''
    rating_match = re.search(r'(\d+(?:\.\d+)?)\s+(\d+)\s+(?:votes|Szavazat)', text, re.IGNORECASE)
    rating = rating_match.group(1) if rating_match else ''
    original_match = re.search(r'Eredeti filmcím\s*(.+?)\s*IMDb', text, re.IGNORECASE)
    original = clean(original_match.group(1)) if original_match else ''
    pieces = []
    if year:
        pieces.append(year)
    if parser.genres:
        pieces.append(', '.join(parser.genres))
    if duration and duration != '--:--:--':
        pieces.append(duration)
    if rating:
        pieces.append('IMDb ' + rating)
    if original:
        pieces.append('Eredeti: ' + original)
    label = ' | '.join(pieces) or 'Film információ'
    info = {'title': title, 'mediatype': 'movie'}
    if year.isdigit():
        info['year'] = int(year)
    if parser.genres:
        info['genre'] = parser.genres
    if rating:
        try:
            info['rating'] = float(rating)
        except (TypeError, ValueError):
            pass
    return '[COLOR gold]%s[/COLOR]' % label, info


def detail(url):
    parser = DetailParser()
    try:
        source = get_page(url)
        parser.feed(source)
    except Exception as exc:
        xbmc.log('Filminvazio detail error: %s' % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().notification('Filminvazio', 'Film betöltési hiba', xbmcgui.NOTIFICATION_ERROR)
        return finish()
    title = parser.title or urlparse(url).path.rstrip('/').split('/')[-1].replace('-', ' ').title()
    duration = duration_label(' '.join(parser.all_text))
    metadata_label, info = detail_metadata(parser, title, duration)
    # Keep the concise metadata summary and append only the genuine plot paragraph.
    summary = re.sub(r'\[/?COLOR[^\]]*\]', '', metadata_label)
    plot = extract_plot(source)
    info['plot'] = summary + ('\n\n' + plot if plot else '')

    # The mirror table contains the actual movie links and their metadata.
    slug = urlparse(url).path.strip('/').split('/')[-1]
    mirror_url = 'https://videaletoltes.com/videa-film/%s/' % slug
    mirror_rows = []
    try:
        table = SourceTableParser()
        table.feed(get_page(mirror_url))
        mirror_rows = table.rows
    except Exception as exc:
        xbmc.log('Filminvazio mirror table error: %s' % exc, xbmc.LOGDEBUG)

    # Put the trailer first, then list the full-film sources underneath it.
    for media_url in parser.media:
        trailer_target = final_url(media_url)
        if not is_trailer_url(trailer_target) or not resolveurl_compatible(trailer_target):
            continue
        trailer_info = dict(info)
        trailer_info['mediatype'] = 'video'
        add_item(trailer_label(provider_name(trailer_target), 'Magyar', 'Előzetes', '--:--:--'),
                 route_url(mode='play', url=trailer_target), False, parser.poster, trailer_info)

    added = 0
    seen_movies = set()
    for row in mirror_rows:
        target = final_url(row['url'])
        if target in seen_movies or is_trailer_url(target) or not resolveurl_compatible(target):
            continue
        seen_movies.add(target)
        added += 1
        row_info = dict(info)
        row_info['studio'] = row['host']
        row_info['genre'] = '%s | %s' % (row['language'], row['quality'])
        add_item(source_label(added, row['host'], row['language'], row['quality'], duration),
                 route_url(mode='play', url=target), False, parser.poster, row_info)

    # Dooplay may expose additional full-film embeds that are not in the mirror table.
    for media_url in parser.media:
        target = final_url(media_url)
        if is_trailer_url(target) or target in seen_movies or not resolveurl_compatible(target):
            continue
        seen_movies.add(target)
        added += 1
        add_item(source_label(added, provider_name(target), 'Magyar', 'HD', duration),
                 route_url(mode='play', url=target), False, parser.poster, info)
    finish('movies')


def play(url):
    if not resolveurl:
        xbmcgui.Dialog().ok('Filminvazio', 'A ResolveURL kiegészítő nincs telepítve.')
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    try:
        media = resolveurl.HostedMediaFile(url)
        resolved = media.resolve() if media else False
        if not resolved or not isinstance(resolved, str):
            raise RuntimeError('ResolveURL nem talált lejátszható médiát')
        item = xbmcgui.ListItem(path=resolved)
        item.setProperty('IsPlayable', 'true')
        xbmcplugin.setResolvedUrl(HANDLE, True, item)
    except Exception as exc:
        xbmc.log('Filminvazio ResolveURL error: %s' % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().notification('Filminvazio', 'A videó feloldása sikertelen', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def main():
    query = parse_qs(urlparse(sys.argv[2]).query)
    mode = query.get('mode', ['home'])[0]
    if mode == 'catalog':
        catalog(query.get('url', [BASE])[0])
    elif mode == 'categories':
        categories()
    elif mode == 'years':
        years()
    elif mode == 'search':
        search()
    elif mode == 'saved_searches':
        saved_searches()
    elif mode == 'saved_search':
        term = query.get('term', [''])[0]
        try:
            if not live_search(term):
                catalog(urljoin(BASE, '?' + urlencode({'s': term})))
        except Exception as exc:
            xbmc.log('Filminvazio saved search error: %s' % exc, xbmc.LOGWARNING)
            catalog(urljoin(BASE, '?' + urlencode({'s': term})))
    elif mode == 'clear_cache':
        clear_cache()
    elif mode == 'detail':
        detail(query.get('url', [BASE])[0])
    elif mode == 'play':
        play(query.get('url', [''])[0])
    elif mode == 'pageinfo':
        finish()
    else:
        home()


if __name__ == '__main__':
    main()
