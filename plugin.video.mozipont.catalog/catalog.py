# -*- coding: utf-8 -*-
"""MoziPont catalog parser with Cloudflare/Session bypass and rich metadata extraction."""
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse
import re
import urllib.request
import http.cookiejar
import json

BASE = 'https://mozipont.com'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0'

_CARD_PATH = re.compile(r'^/(film|sorozat)/(\d+)/?$')
_YT_ID = re.compile(r'^[A-Za-z0-9_-]{6,20}$')
_YOUTUBE_HOSTS = {
    'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtube-nocookie.com',
    'www.youtube-nocookie.com', 'youtu.be', 'www.youtu.be',
}

_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))

def _log(msg):
    try:
        import xbmc
        xbmc.log(f"[MoziPont DEBUG] {msg}", xbmc.LOGINFO)
    except ImportError:
        print(f"[MoziPont DEBUG] {msg}")

def _make_request(url, referer=None, accept='text/html'):
    headers = {
        'User-Agent': USER_AGENT,
        'Accept': f'{accept},*/*;q=0.8',
        'Accept-Language': 'hu-HU,hu;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    if referer:
        headers['Referer'] = referer
        
    req = urllib.request.Request(url, headers=headers)
    try:
        response = _opener.open(req, timeout=15)
        return response.read().decode('utf-8', 'replace'), response.getcode()
    except urllib.error.HTTPError as e:
        return e.read().decode('utf-8', 'replace') if e.fp else '', e.code
    except Exception as e:
        return str(e), 0

def _init_session():
    try:
        _make_request(BASE)
    except Exception:
        pass

_init_session()

def _youtube_video_id(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if host not in _YOUTUBE_HOSTS:
        return ''
    video_id = ''
    if host.endswith('youtu.be'):
        video_id = parsed.path.strip('/').split('/', 1)[0]
    else:
        if parsed.path.rstrip('/') == '/watch':
            video_id = parse_qs(parsed.query).get('v', [''])[0]
        else:
            match = re.match(r'^/(?:embed|shorts)/([A-Za-z0-9_-]+)', parsed.path)
            if match:
                video_id = match.group(1)
    return video_id if _YT_ID.match(video_id or '') else ''

class _CatalogParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.cards = []
        self.current = None
        self.current_youtube = None
        self.trailer_id = ''
        self.h1 = []
        self.in_h1 = 0
        self.paragraphs = []
        self.in_p = 0
        self.current_p = []
        self.meta = {}
        
        self.in_card = 0
        self.in_strong = 0
        self.in_small = 0
        self.in_label = 0
        self.in_age = 0
        self.in_rating = 0
        self.in_hd = 0
        self.in_tag = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = attrs.get('property') or attrs.get('name')
            if key and attrs.get('content'):
                self.meta[key.lower()] = attrs['content'].strip()
        elif tag == 'a':
            href = attrs.get('href', '')
            class_attr = attrs.get('class', '')
            parsed = urlparse(href)
            match = _CARD_PATH.match(parsed.path)
            
            if 'media-card' in class_attr and match and (not parsed.netloc or parsed.netloc.lower() in ('mozipont.com', 'www.mozipont.com')):
                self.in_card += 1
                self.current = {
                    'path': parsed.path, 'kind': match.group(1), 'id': match.group(2),
                    'title': '', 'year_type': '', 'poster': '',
                    'label': '', 'age': '', 'rating': '', 'hd': False, 'tags': []
                }
            elif (parsed.hostname or '').lower() in _YOUTUBE_HOSTS:
                self.current_youtube = {'href': href, 'text': [attrs.get('aria-label', ''), attrs.get('title', '')]}
        elif tag == 'img' and self.current is not None:
            image = attrs.get('src') or attrs.get('data-src') or ''
            if image and not self.current['poster']:
                self.current['poster'] = image
        elif tag == 'h1':
            self.in_h1 += 1
        elif tag == 'p':
            self.in_p += 1
            if self.in_p == 1:
                self.current_p = []
        elif tag == 'strong' and self.current is not None:
            self.in_strong += 1
        elif tag == 'small' and self.current is not None:
            self.in_small += 1
        elif tag == 'span' and self.current is not None:
            class_attr = attrs.get('class', '')
            if 'poster-label' in class_attr: self.in_label += 1
            elif 'age-badge' in class_attr: self.in_age += 1
            elif 'media-card__rating' in class_attr: self.in_rating += 1
            elif 'media-card__hd' in class_attr: self.in_hd += 1
            elif 'tag-badge' in class_attr: self.in_tag += 1

    def handle_endtag(self, tag):
        if tag == 'a' and self.in_card:
            self.in_card -= 1
            if self.current:
                self.current['title'] = self.current['title'].strip()
                self.current['year_type'] = self.current['year_type'].strip()
                self.current['label'] = self.current['label'].strip()
                self.current['age'] = self.current['age'].strip()
                self.current['rating'] = self.current['rating'].strip()
                if self.current['title']:
                    self.cards.append(self.current)
            self.current = None
            self.in_strong = 0
            self.in_small = 0
            self.in_label = 0
            self.in_age = 0
            self.in_rating = 0
            self.in_hd = 0
            self.in_tag = 0
        elif tag == 'a' and self.current_youtube is not None:
            label = ' '.join(self.current_youtube['text']).casefold()
            if 'előzetes' in label and not self.trailer_id:
                self.trailer_id = _youtube_video_id(self.current_youtube['href'])
            self.current_youtube = None
        elif tag == 'h1' and self.in_h1:
            self.in_h1 -= 1
        elif tag == 'p' and self.in_p:
            self.in_p -= 1
            if self.in_p == 0:
                text = ' '.join(' '.join(self.current_p).split())
                if text: self.paragraphs.append(text)
                self.current_p = []
        elif tag == 'strong' and self.in_strong:
            self.in_strong -= 1
        elif tag == 'small' and self.in_small:
            self.in_small -= 1
        elif tag == 'span':
            if self.in_label: self.in_label -= 1
            if self.in_age: self.in_age -= 1
            if self.in_rating: self.in_rating -= 1
            if self.in_hd: self.in_hd -= 1
            if self.in_tag: self.in_tag -= 1

    def handle_data(self, data):
        if self.current is not None:
            if self.in_strong:
                self.current['title'] += data
            elif self.in_small:
                self.current['year_type'] += data
            elif self.in_label:
                self.current['label'] += data
            elif self.in_age:
                self.current['age'] += data
            elif self.in_rating:
                self.current['rating'] += data
            elif self.in_tag and data.strip():
                self.current['tags'].append(data.strip())
        if self.current_youtube is not None and data.strip():
            self.current_youtube['text'].append(data.strip())
        if self.in_h1:
            self.h1.append(data.strip())
        if self.in_p:
            self.current_p.append(data.strip())

def fetch(path, query=None):
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
        raise ValueError('Invalid catalog path')
    if path.startswith('/nezes/') or '/nezes/' in path:
        raise ValueError('Use get_sources for playback routes')
    url = BASE + path
    if query:
        from urllib.parse import urlencode
        url += '?' + urlencode(query)
    
    _log(f"Fetching URL: {url}")
    html, code = _make_request(url, referer=BASE + '/')
    _log(f"Fetch response code: {code}, HTML length: {len(html) if html else 0}")
    
    if code != 200:
        raise ConnectionError(f'Catalog fetch failed with HTTP {code}')
    return html

def parse_listing(html):
    parser = _CatalogParser()
    parser.feed(html)
    _log(f"Parsed {len(parser.cards)} cards from HTML")
    if parser.cards:
        _log(f"First card example: {parser.cards[0]}")
    
    unique = []
    seen = set()
    for item in parser.cards:
        key = (item['kind'], item['id'])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    _log(f"Returning {len(unique)} unique entries")
    return unique

def get_genres(kind):
    path = '/filmek' if kind == 'films' else '/sorozatok'
    html = fetch(path)
    genres = []
    match = re.search(r'<select\s+name="mufaj"[^>]*>(.*?)</select>', html, re.IGNORECASE | re.DOTALL)
    if match:
        options = re.findall(r'<option\s+value="([^"]*)"[^>]*>([^<]*)</option>', match.group(1), re.IGNORECASE)
        for val, name in options:
            if val:
                genres.append({'name': name.strip(), 'value': val.strip()})
    return genres

def parse_detail(html, kind, content_id):
    parser = _CatalogParser()
    parser.feed(html)
    title = ' '.join(parser.h1).strip()
    if not title:
        title = parser.meta.get('og:title', '').split(' | ', 1)[0].strip()
    title = re.sub(r'\s+HD$', '', title).strip()
    
    desc_match = re.search(r'<p\s+class="detail__desc"[^>]*>(.*?)</p>', html, re.IGNORECASE | re.DOTALL)
    if desc_match:
        description = re.sub(r'<[^>]+>', '', desc_match.group(1))
        description = re.sub(r'\s+', ' ', description).strip()
    else:
        description = parser.meta.get('description', '').strip()
        if description: description = re.sub(r'\s+', ' ', description)
        if not description:
            candidates = [p for p in parser.paragraphs if len(p) > 80 and 'MoziPont:' not in p]
            description = candidates[0] if candidates else ''

    poster = parser.meta.get('og:image', '')
    tags = re.findall(r'<span\s+class="tag-badge"[^>]*>(.*?)</span>', html, re.IGNORECASE)
    tags = [re.sub(r'<[^>]+>', '', tag).strip() for tag in tags]
    
    year, genre, duration = '', '', 0
    brief_match = re.search(r'<p\s+class="detail__brief"[^>]*>(.*?)</p>', html, re.IGNORECASE | re.DOTALL)
    if brief_match:
        brief_text = re.sub(r'<[^>]+>', '', brief_match.group(1)).strip()
        parts = [p.strip() for p in brief_text.split('·')]
        genres_list = []
        for p in parts:
            if re.match(r'^\d{4}$', p): year = p
            elif re.search(r'\d+\s*(?:ó|óra)', p, re.I):
                match = re.search(r'(\d+)\s*(?:ó|óra)\s*(?:(\d+)\s*p)?', p, re.I)
                if match: duration = int(match.group(1)) * 60 + int(match.group(2) or 0)
            else:
                if p: genres_list.append(p)
        genre = ' · '.join(genres_list)
    else:
        for candidate in (title, description):
            found = re.search(r'\b(19\d{2}|20\d{2})\b', candidate)
            if found: year = found.group(1); break
        for paragraph in parser.paragraphs:
            if re.search(r'\b(19\d{2}|20\d{2})\b', paragraph) and len(paragraph) < 180:
                genre = paragraph
                match = re.search(r'(\d+)\s*(?:ó|óra)\s*(?:(\d+)\s*p)?', paragraph, re.I)
                if match: duration = int(match.group(1)) * 60 + int(match.group(2) or 0)
                break

    return {
        'title': title or 'MoziPont cím ' + str(content_id),
        'description': description, 'poster': poster,
        'year': int(year) if year else 0, 'genre': genre, 'duration': duration,
        'mediatype': 'movie' if kind == 'film' else 'tvshow',
        'trailer_id': parser.trailer_id, 'tags': tags,
    }

def get_media_info(content_id):
    """Gyors információ lekérése az API-ról (leírással együtt)."""
    url = BASE + f'/api/media/{content_id}/info'
    try:
        html, code = _make_request(url, referer=BASE + '/')
        if code == 200:
            data = json.loads(html)
            return {
                'description': data.get('description', ''),
                'genres': ' · '.join([g['name'] for g in data.get('genres', [])]),
                'duration': data.get('duration', ''),
                'country': data.get('country', ''),
            }
    except Exception as e:
        _log(f"API info error for {content_id}: {repr(e)}")
    return {'description': '', 'genres': '', 'duration': '', 'country': ''}

def get_series_seasons(series_id):
    url = BASE + f'/sorozat/{series_id}/reszek/1'
    html, code = _make_request(url, referer=BASE + f'/sorozat/{series_id}')
    seasons = []
    if code == 200:
        _log(f"Seasons page fetched successfully for series {series_id}")
        match = re.search(r'<div\s+class="season-tabs"[^>]*>(.*?)</div>', html, re.IGNORECASE | re.DOTALL)
        if match:
            _log("Found season-tabs div")
            tabs_html = match.group(1)
            tab_matches = re.findall(r'<button\b(?=[^>]*data-season="(\d+)")(?=[^>]*data-count="(\d+)")[^>]*>(.*?)</button>', tabs_html, re.IGNORECASE | re.DOTALL)
            _log(f"Found {len(tab_matches)} season buttons")
            for season_num, count, label in tab_matches:
                seasons.append({
                    'season': int(season_num),
                    'count': int(count),
                    'label': re.sub(r'<[^>]+>', '', label).strip()
                })
        else:
            _log("season-tabs div NOT found in HTML")
    else:
        _log(f"Failed to fetch seasons page, HTTP code: {code}")
    return seasons

def get_episodes_for_season(series_id, season):
    url = BASE + f'/sorozat/{series_id}/reszek/{season}'
    html, code = _make_request(url, referer=BASE + f'/sorozat/{series_id}')
    episodes = []
    if code == 200:
        match = re.search(r'<noscript>.*?<ul class="episode-plain">(.*?)</ul>.*?</noscript>', html, re.IGNORECASE | re.DOTALL)
        if match:
            ul_html = match.group(1)
            ep_matches = re.findall(r'<a href="(/nezes/\d+/\d+x\d+)">([^<]+)</a>', ul_html, re.IGNORECASE)
            for href, title in ep_matches:
                episodes.append({'href': href, 'title': title.strip()})
    return episodes

def get_sources_from_url(watch_url, referer):
    sources = []
    html, code = _make_request(watch_url, referer=referer)
    if code != 200:
        return sources

    if "Ez a tartalom egyelőre még nem jött ki, vagy nincs hozzá megbízható forrás." in html:
        return sources

    match = re.search(r'<iframe[^>]+(?:src|data-t|data-src)=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if match:
        src = match.group(1)
        if src.startswith('//'): src = 'https:' + src
        elif src.startswith('/'): src = BASE + src
        
        parsed = urlparse(src)
        hostname = parsed.hostname.replace('www.', '') if parsed.hostname else 'Ismeretlen'
        source_name = hostname[0].upper() + hostname[1:] if hostname else 'Ismeretlen'
        
        sources.append({'name': source_name, 'url': src, 'is_trailer': False})
        
    return sources

def get_sources(content_id):
    """Filmekhez: kinyeri a forrásokat a /nezes/{id} oldalról (SZÓTÁRT ad vissza)."""
    watch_url = BASE + f'/nezes/{content_id}'
    html, code = _make_request(watch_url, referer=BASE + f'/film/{content_id}')
    
    sources = []
    unavailable_msg = ''
    
    if code == 200:
        if "Ez a tartalom egyelőre még nem jött ki, vagy nincs hozzá megbízható forrás." in html:
            unavailable_msg = "Ez a tartalom egyelőre még nem jött ki, vagy nincs hozzá megbízható forrás."
        else:
            match = re.search(r'<iframe[^>]+(?:src|data-t|data-src)=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if match:
                src = match.group(1)
                if src.startswith('//'): src = 'https:' + src
                elif src.startswith('/'): src = BASE + src
                
                parsed = urlparse(src)
                hostname = parsed.hostname.replace('www.', '') if parsed.hostname else 'Ismeretlen'
                source_name = hostname[0].upper() + hostname[1:] if hostname else 'Ismeretlen'
                
                sources.append({'name': source_name, 'url': src, 'is_trailer': False})
                
    return {'sources': sources, 'unavailable_msg': unavailable_msg}