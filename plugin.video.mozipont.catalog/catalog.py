# -*- coding: utf-8 -*-
"""MoziPont catalog client for Kodi.

Only reads public catalog metadata and the player URL explicitly exposed by the
MoziPont watch page. It does not decode obfuscated player data.
"""
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from html.parser import HTMLParser
import hashlib
import http.cookiejar
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse, urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

BASE = 'https://mozipont.com'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) '
              'Gecko/20100101 Firefox/124.0')
API_TTL = 900
LIST_TTL = 180
DETAIL_TTL = 600

_COOKIE_JAR = http.cookiejar.CookieJar()
_OPENER = build_opener(HTTPCookieProcessor(_COOKIE_JAR))


def _log(message):
    try:
        import xbmc
        xbmc.log('[MoziPont] ' + str(message), xbmc.LOGINFO)
    except Exception:
        pass


def _cache_dir():
    """Return a persistent per-addon cache directory when running in Kodi."""
    try:
        import xbmcaddon
        import xbmcvfs
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
    except Exception:
        profile = os.path.join(os.path.dirname(__file__), '.cache')
    path = os.path.join(profile, 'http-cache')
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return None
    return path


def _cache_file(key):
    root = _cache_dir()
    if not root:
        return None
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
    return os.path.join(root, digest + '.json')


def _cache_get(key, ttl):
    path = _cache_file(key)
    if not path:
        return None
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            record = json.load(stream)
        if time.time() - float(record.get('saved', 0)) <= ttl:
            _log('cache hit: ' + key)
            return record.get('value')
    except (OSError, ValueError, TypeError):
        pass
    return None


def _cache_put(key, value):
    path = _cache_file(key)
    if not path:
        return
    temp = path + '.tmp'
    try:
        with open(temp, 'w', encoding='utf-8') as stream:
            json.dump({'saved': time.time(), 'value': value}, stream,
                      ensure_ascii=False, separators=(',', ':'))
        os.replace(temp, path)
    except (OSError, TypeError, ValueError):
        try:
            if os.path.exists(temp):
                os.remove(temp)
        except OSError:
            pass


def _request(url, referer=None, accept='text/html'):
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': accept + ',*/*;q=0.8',
        'Accept-Language': 'hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive',
    }
    if referer:
        headers['Referer'] = referer
    request = Request(url, headers=headers)
    try:
        with _OPENER.open(request, timeout=12) as response:
            body = response.read().decode('utf-8', 'replace')
            return body, response.getcode()
    except HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', 'replace') if exc.fp else ''
        except Exception:
            body = ''
        return body, exc.code
    except (URLError, OSError, TimeoutError) as exc:
        _log('network error for ' + urlparse(url).path + ': ' + repr(exc))
        return '', 0


def _safe_url(path, query=None):
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
        raise ValueError('Invalid MoziPont path')
    url = BASE + path
    if query:
        url += '?' + urlencode(query)
    return url


def fetch(path, query=None, ttl=None):
    """Fetch and cache a public HTML catalog page."""
    url = _safe_url(path, query)
    cache_ttl = ttl if ttl is not None else (LIST_TTL if path in ('/filmek', '/sorozatok', '/kereses') else DETAIL_TTL)
    cached = _cache_get('html:' + url, cache_ttl)
    if isinstance(cached, str):
        return cached
    _log('HTTP GET ' + urlparse(url).path)
    body, status = _request(url, referer=BASE + '/')
    if status != 200:
        raise ConnectionError('MoziPont returned HTTP ' + str(status) + ' for ' + path)
    _cache_put('html:' + url, body)
    return body


_CARD_PATH = re.compile(r'^/(film|sorozat)/(\d+)/?$')
_YT_ID = re.compile(r'^[A-Za-z0-9_-]{6,20}$')
_YOUTUBE_HOSTS = {
    'youtube.com', 'www.youtube.com', 'm.youtube.com',
    'youtube-nocookie.com', 'www.youtube-nocookie.com',
    'youtu.be', 'www.youtu.be',
}


def _youtube_id(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if host not in _YOUTUBE_HOSTS:
        return ''
    video_id = ''
    if host.endswith('youtu.be'):
        video_id = parsed.path.strip('/').split('/', 1)[0]
    elif parsed.path.rstrip('/') == '/watch':
        video_id = parse_qs(parsed.query).get('v', [''])[0]
    else:
        match = re.match(r'^/(?:embed|shorts)/([A-Za-z0-9_-]+)', parsed.path)
        if match:
            video_id = match.group(1)
    return video_id if _YT_ID.fullmatch(video_id or '') else ''


class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards = []
        self.current = None
        self.h1 = []
        self.in_h1 = 0
        self.meta = {}
        self.paragraphs = []
        self.in_p = 0
        self.current_p = []
        self.youtube_link = None
        self.trailer_id = ''
        self._flags = {'strong': 0, 'small': 0, 'label': 0,
                       'age': 0, 'rating': 0, 'tag': 0}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = (attrs.get('property') or attrs.get('name') or '').lower()
            if key and attrs.get('content'):
                self.meta[key] = attrs['content'].strip()
        elif tag == 'a':
            href = attrs.get('href', '')
            parsed = urlparse(href)
            match = _CARD_PATH.match(parsed.path)
            classes = attrs.get('class', '').split()
            if 'media-card' in classes and match and (not parsed.netloc or parsed.hostname in ('mozipont.com', 'www.mozipont.com')):
                self.current = {
                    'path': parsed.path, 'kind': match.group(1), 'id': match.group(2),
                    'title': '', 'year_type': '', 'poster': '', 'label': '',
                    'age': '', 'rating': '', 'hd': False, 'tags': []
                }
                self._flags = {'strong': 0, 'small': 0, 'label': 0,
                               'age': 0, 'rating': 0, 'tag': 0}
            elif (parsed.hostname or '').lower() in _YOUTUBE_HOSTS:
                self.youtube_link = {'href': href, 'text': [attrs.get('aria-label', ''), attrs.get('title', '')]}
        elif tag == 'img' and self.current is not None:
            self.current['poster'] = self.current['poster'] or attrs.get('src') or attrs.get('data-src') or ''
        elif tag == 'h1':
            self.in_h1 += 1
        elif tag == 'p':
            self.in_p += 1
            if self.in_p == 1:
                self.current_p = []
        elif tag == 'strong' and self.current is not None:
            self._flags['strong'] += 1
        elif tag == 'small' and self.current is not None:
            self._flags['small'] += 1
        elif tag == 'span' and self.current is not None:
            classes = attrs.get('class', '').split()
            for cls, flag in (('poster-label', 'label'), ('age-badge', 'age'),
                              ('media-card__rating', 'rating'), ('tag-badge', 'tag')):
                if cls in classes:
                    self._flags[flag] += 1
            if 'media-card__hd' in classes:
                self.current['hd'] = True

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            item = self.current
            item['title'] = item['title'].strip()
            if item['title']:
                item['poster'] = urljoin(BASE + '/', item['poster']) if item['poster'] else ''
                self.cards.append(item)
            self.current = None
            self._flags = {'strong': 0, 'small': 0, 'label': 0,
                           'age': 0, 'rating': 0, 'tag': 0}
        elif tag == 'a' and self.youtube_link is not None:
            label = ' '.join(self.youtube_link['text']).casefold()
            if 'előzetes' in label and not self.trailer_id:
                self.trailer_id = _youtube_id(self.youtube_link['href'])
            self.youtube_link = None
        elif tag == 'h1' and self.in_h1:
            self.in_h1 -= 1
        elif tag == 'p' and self.in_p:
            self.in_p -= 1
            if self.in_p == 0:
                text = ' '.join(' '.join(self.current_p).split())
                if text:
                    self.paragraphs.append(text)
                self.current_p = []
        elif tag in ('strong', 'small') and self._flags.get(tag, 0):
            self._flags[tag] -= 1
        elif tag == 'span':
            for flag in ('label', 'age', 'rating', 'tag'):
                if self._flags[flag]:
                    self._flags[flag] -= 1

    def handle_data(self, data):
        if self.current is not None:
            if self._flags['strong']:
                self.current['title'] += data
            elif self._flags['small']:
                self.current['year_type'] += data
            elif self._flags['label']:
                self.current['label'] += data
            elif self._flags['age']:
                self.current['age'] += data
            elif self._flags['rating']:
                self.current['rating'] += data
            elif self._flags['tag'] and data.strip():
                self.current['tags'].append(data.strip())
        if self.youtube_link is not None and data.strip():
            self.youtube_link['text'].append(data.strip())
        if self.in_h1:
            self.h1.append(data.strip())
        if self.in_p:
            self.current_p.append(data.strip())


def parse_listing(markup):
    parser = _PageParser()
    parser.feed(markup)
    result, seen = [], set()
    for card in parser.cards:
        key = (card['kind'], card['id'])
        if key not in seen:
            seen.add(key)
            result.append(card)
    return result


def get_media_info(content_id):
    content_id = str(content_id)
    key = 'api:media:' + content_id
    cached = _cache_get(key, API_TTL)
    if isinstance(cached, dict):
        return cached
    url = BASE + '/api/media/' + content_id + '/info'
    _log('HTTP GET /api/media/' + content_id + '/info')
    body, status = _request(url, referer=BASE + '/', accept='application/json')
    if status != 200:
        return {'ok': False, 'title': '', 'description': '', 'year': 0,
                'play': '', 'trailer': '', 'genres': [], 'duration': '',
                'rating': '', 'age': '', 'hd': False}
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return {'ok': False, 'title': '', 'description': '', 'year': 0,
                'play': '', 'trailer': '', 'genres': [], 'duration': '',
                'rating': '', 'age': '', 'hd': False}
    result = {
        'ok': True,
        'title': data.get('title') or '',
        'description': data.get('description') or '',
        'year': data.get('year') or 0,
        'play': data.get('play') or '',
        'trailer': data.get('trailer') or '',
        'genres': data.get('genres') or [],
        'duration': data.get('duration') or '',
        'rating': data.get('rating') or '',
        'age': data.get('age') or '',
        'hd': bool(data.get('hd')),
    }
    _cache_put(key, result)
    return result


def get_media_infos(content_ids):
    """Fetch a small page of API metadata concurrently; cache remains on disk."""
    ids = [str(value) for value in content_ids]
    if not ids:
        return []
    with ThreadPoolExecutor(max_workers=5) as pool:
        return list(pool.map(get_media_info, ids))


def get_genres(kind):
    path = '/filmek' if kind == 'films' else '/sorozatok'
    markup = fetch(path)
    match = re.search(r'<select\b[^>]*name=["\']mufaj["\'][^>]*>(.*?)</select>',
                      markup, re.I | re.S)
    if not match:
        return []
    genres = []
    for value, name in re.findall(r'<option\b[^>]*value=["\']([^"\']*)["\'][^>]*>(.*?)</option>', match.group(1), re.I | re.S):
        clean_name = re.sub(r'<[^>]+>', '', name).strip()
        if value:
            genres.append({'name': unescape(clean_name), 'value': unescape(value)})
    return genres


def parse_detail(markup, kind, content_id):
    parser = _PageParser()
    parser.feed(markup)
    title = ' '.join(part for part in parser.h1 if part).strip()
    if not title:
        title = parser.meta.get('og:title', '').split(' | ', 1)[0].strip()
    title = re.sub(r'\s+HD$', '', title).strip()

    desc = re.search(r'<p\b[^>]*class=["\'][^"\']*detail__desc[^"\']*["\'][^>]*>(.*?)</p>', markup, re.I | re.S)
    if desc:
        description = re.sub(r'<[^>]+>', '', desc.group(1))
        description = unescape(' '.join(description.split()))
    else:
        description = parser.meta.get('description', '').strip()

    poster = parser.meta.get('og:image', '')
    if poster:
        poster = urljoin(BASE + '/', poster)

    brief = re.search(r'<p\b[^>]*class=["\'][^"\']*detail__brief[^"\']*["\'][^>]*>(.*?)</p>', markup, re.I | re.S)
    year, genre, duration = 0, '', ''
    if brief:
        brief_text = unescape(re.sub(r'<[^>]+>', '', brief.group(1)))
        groups = [piece.strip() for piece in brief_text.split('·')]
        genre_parts = []
        for piece in groups:
            if re.fullmatch(r'\d{4}', piece):
                year = int(piece)
            elif re.search(r'\d+\s*(?:ó|óra)', piece, re.I):
                duration = piece
            elif piece:
                genre_parts.append(piece)
        genre = ' · '.join(genre_parts)

    tags = [unescape(re.sub(r'<[^>]+>', '', item)).strip()
            for item in re.findall(r'<span\b[^>]*class=["\'][^"\']*tag-badge[^"\']*["\'][^>]*>(.*?)</span>', markup, re.I | re.S)]
    tags = [item for item in tags if item]
    return {
        'title': title or 'MoziPont cím ' + str(content_id),
        'description': description,
        'poster': poster,
        'year': year,
        'genre': genre,
        'duration': duration,
        'mediatype': 'movie' if kind == 'film' else 'tvshow',
        'trailer_id': parser.trailer_id,
        'tags': tags,
    }


def _extract_player_url(markup):
    iframe = re.search(r'<iframe\b([^>]*)>', markup, re.I | re.S)
    if not iframe:
        return ''
    attrs = iframe.group(1)
    # Current MoziPont pages expose the player URL in data-t. Prefer a normal
    # src if present, then accept the public data-t/data-src attributes.
    for name in ('src', 'data-t', 'data-src'):
        match = re.search(r'\b' + name + r'\s*=\s*["\']([^"\']+)["\']', attrs, re.I)
        if match:
            value = unescape(match.group(1)).strip()
            if value:
                return urljoin(BASE + '/', value)
    return ''


def _source_record(url):
    host = (urlparse(url).hostname or '').lower()
    host = host[4:] if host.startswith('www.') else host
    name = host[:1].upper() + host[1:] if host else 'Lejátszó'
    return {'name': name, 'url': url, 'is_trailer': False}


def get_sources_from_url(watch_url, referer=None):
    if not watch_url.startswith(BASE + '/'):
        raise ValueError('Invalid watch URL')
    body, status = _request(watch_url, referer=referer or BASE + '/')
    if status != 200:
        return []
    player_url = _extract_player_url(body)
    return [_source_record(player_url)] if player_url else []


def get_sources(content_id):
    content_id = str(content_id)
    if not content_id.isdigit():
        return {'sources': [], 'unavailable_msg': ''}
    watch_url = BASE + '/nezes/' + content_id
    body, status = _request(watch_url, referer=BASE + '/film/' + content_id)
    if status != 200:
        return {'sources': [], 'unavailable_msg': ''}
    unavailable = 'Ez a tartalom egyelőre még nem jött ki, vagy nincs hozzá megbízható forrás.'
    if unavailable in body:
        return {'sources': [], 'unavailable_msg': unavailable}
    player_url = _extract_player_url(body)
    sources = [_source_record(player_url)] if player_url else []
    return {'sources': sources, 'unavailable_msg': ''}


def get_series_seasons(series_id):
    sid = str(series_id)
    if not sid.isdigit():
        return []
    url = BASE + '/sorozat/' + sid + '/reszek/1'
    body, status = _request(url, referer=BASE + '/sorozat/' + sid)
    if status != 200:
        return []
    block = re.search(r'<div\b[^>]*class=["\'][^"\']*season-tabs[^"\']*["\'][^>]*>(.*?)</div>', body, re.I | re.S)
    if not block:
        return []
    seasons = []
    pattern = re.compile(r'<button\b(?=[^>]*data-season=["\'](\d+)["\'])(?=[^>]*data-count=["\'](\d+)["\'])[^>]*>(.*?)</button>', re.I | re.S)
    for season, count, label in pattern.findall(block.group(1)):
        seasons.append({'season': int(season), 'count': int(count),
                        'label': unescape(re.sub(r'<[^>]+>', '', label)).strip()})
    return seasons


def get_episodes_for_season(series_id, season):
    sid, season = str(series_id), str(season)
    if not sid.isdigit() or not season.isdigit():
        return []
    url = BASE + '/sorozat/' + sid + '/reszek/' + season
    body, status = _request(url, referer=BASE + '/sorozat/' + sid)
    if status != 200:
        return []
    episodes = []
    for href, title in re.findall(r'<a\b[^>]*href=["\'](/nezes/\d+/\d+x\d+)["\'][^>]*>(.*?)</a>', body, re.I | re.S):
        episodes.append({'href': href, 'title': unescape(re.sub(r'<[^>]+>', '', title)).strip()})
    return episodes
