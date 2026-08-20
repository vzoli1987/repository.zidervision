# -*- coding: utf-8 -*-
"""S365 catalog, season and playback service adapter for Kodi Python 3."""
from __future__ import absolute_import, division, print_function, unicode_literals

import gzip
import html as html_module
from base64 import b64decode
import json
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen

import xbmcaddon

ADDON = xbmcaddon.Addon()
DEFAULT_CATALOG = 'https://sorozat365.hu'
USER_AGENT = 'Mozilla/5.0 (Kodi; S365 add-on/0.4; +https://sorozat365.hu/)'
PROBE_CACHE_SETTING = 'source_probe_cache'
PROBE_CACHE_TTL = 6 * 60 * 60
PROBE_CACHE_LIMIT = 160
AVAILABILITY_CACHE_SETTING = 'availability_cache'
AVAILABILITY_CACHE_TTL = 20 * 60
AVAILABILITY_CACHE_LIMIT = 480
PENDING_SOURCE_PATTERN = re.compile(r'szinkroniz[aá]l[aá]s\s+alatt', re.I)


class S365Error(Exception):
    """A user-presentable service error."""


def _clean(value):
    value = html_module.unescape(value or '')
    value = re.sub(r'<[^>]+>', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def _attribute(attrs, name):
    match = re.search(r'\b{}\s*=\s*(["\'])(.*?)\1'.format(re.escape(name)), attrs, re.I | re.S)
    return html_module.unescape(match.group(2).strip()) if match else ''


def _setting(name, default=''):
    value = ADDON.getSetting(name)
    return value.strip() if value and value.strip() else default


def catalog_base():
    return _setting('catalog_base', DEFAULT_CATALOG).rstrip('/')


def timeout():
    try:
        return max(5, min(60, int(_setting('request_timeout', '15'))))
    except ValueError:
        return 15


def absolute(url, base=None):
    return urljoin((base or catalog_base()) + '/', html_module.unescape(url or '').strip())


def fetch(url, headers=None):
    request_headers = {
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.4',
        'Accept-Language': 'hu-HU,hu;q=0.9,en;q=0.5',
    }
    if headers:
        request_headers.update(headers)
    try:
        request = Request(url, headers=request_headers)
        with urlopen(request, timeout=timeout(), context=ssl.create_default_context()) as response:
            raw = response.read()
            if response.headers.get('Content-Encoding', '').lower() == 'gzip':
                raw = gzip.decompress(raw)
            return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace'), response.geturl()
    except HTTPError as exc:
        raise S365Error('A szolgáltatás HTTP {} hibával válaszolt.'.format(exc.code))
    except (URLError, OSError) as exc:
        raise S365Error('A szolgáltatás nem érhető el: {}.'.format(getattr(exc, 'reason', exc)))


def fetch_html(path_or_url, base=None):
    target = path_or_url if path_or_url.startswith(('http://', 'https://')) else absolute(path_or_url, base)
    return fetch(target)[0]


def _cover_from_page(page):
    patterns = [
        r'(?:\.src\s*=|backgroundImage\s*=)\s*["\'](?:url\()?([^\'"\)]+)',
        r'<img\b[^>]*\bsrc=["\']([^"\']+)',
        r'(/covers/[^\'"\)\s]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, page, re.I | re.S)
        if match and '/style/pont.png' not in match.group(1):
            return absolute(match.group(1))
    return ''


def page_metadata(page):
    def meta(property_name):
        pattern = r'<meta\b[^>]*(?:property|name)=["\']{}["\'][^>]*content=["\']([^"\']*)'.format(re.escape(property_name))
        match = re.search(pattern, page, re.I | re.S)
        return _clean(match.group(1)) if match else ''

    title_match = re.search(r'<title[^>]*>(.*?)</title>', page, re.I | re.S)
    return {
        'title': _clean(meta('og:title') or (title_match.group(1) if title_match else 'S365')),
        'plot': meta('og:description') or meta('description'),
        'thumb': absolute(meta('og:image')) if meta('og:image') else _cover_from_page(page),
    }


def _cover_from_body(body):
    for pattern in (
        r'(?:backgroundImage|background-image)\s*(?:=|:)\s*["\']?url\(["\']?([^\'"\)]+)',
        r'<img\b[^>]*\bsrc=["\']([^"\']+)',
        r'(/covers/[^\'"\)\s]+)',
    ):
        match = re.search(pattern, body, re.I | re.S)
        if match and '/style/pont.png' not in match.group(1):
            return absolute(match.group(1))
    return ''


def _card_title(body, fallback):
    match = re.search(r'<div\b[^>]*\bclass=["\'][^"\']*\bd1\b[^"\']*["\'][^>]*>(.*?)</div>', body, re.I | re.S)
    return _clean(match.group(1)) if match else _clean(fallback)


def _card_details(body):
    values = re.findall(r'<div\b[^>]*\bclass=["\'][^"\']*\bd2\b[^"\']*["\'][^>]*>(.*?)</div>', body, re.I | re.S)
    return ' • '.join(filter(None, (_clean(value) for value in values)))


def _kind_from_href(href):
    path = urlparse(absolute(href)).path
    if '/r/' in path:
        return 'episode'
    if '/e/' in path:
        return 'season'
    if '/f/' in path:
        return 'series'
    return ''


def _primary_catalogue_html(page):
    """Remove only the persistent ``EZ IS TETSZHET`` recommendation carousel."""
    # The front page also contains other flowbars (for example Kiemelt), which
    # are legitimate catalogue content. The repeated block is identified by its
    # visible title rather than by the generic ``flowbar`` class.
    recommendation = re.search(
        r'<div\b[^>]*\bclass=["\'][^"\']*\bflowbar\b[^"\']*["\'][^>]*>\s*<div\b[^>]*\bclass=["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>\s*<span>\s*EZ\s+IS\s+TETSZHET\s*</span>',
        page,
        re.I | re.S,
    )
    return page[:recommendation.start()] if recommendation else page


def parse_cards(page, base=None):
    """Parse primary catalogue cards; series detail pages are handled separately."""
    cards, seen = [], set()
    catalogue = _primary_catalogue_html(page)
    for match in re.finditer(r'<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>', catalogue, re.I | re.S):
        attrs, body = match.group('attrs'), match.group('body')
        href = _attribute(attrs, 'href')
        kind = _kind_from_href(href)
        if not kind:
            continue
        target = absolute(href, base or catalog_base())
        if target in seen:
            continue
        seen.add(target)
        title = _card_title(body, _attribute(attrs, 'title'))
        if not title:
            continue
        cards.append({'url': target, 'title': title, 'label2': _card_details(body), 'thumb': _cover_from_body(body), 'kind': kind})
    return cards


def _section(page, class_name, stop_classes=()):
    start_match = re.search(r'<div\b[^>]*\bclass=["\'][^"\']*\b{}\b[^"\']*["\'][^>]*>'.format(re.escape(class_name)), page, re.I | re.S)
    if not start_match:
        return ''
    start, end = start_match.start(), len(page)
    for stop_class in stop_classes:
        match = re.search(r'<div\b[^>]*\bclass=["\'][^"\']*\b{}\b[^"\']*["\'][^>]*>'.format(re.escape(stop_class)), page[start_match.end():], re.I | re.S)
        if match:
            end = min(end, start_match.end() + match.start())
    return page[start:end]


def _detail_links(page, section_name, expected_kind, stop_classes):
    links, seen = [], set()
    section = _section(page, section_name, stop_classes)
    for match in re.finditer(r'<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>', section, re.I | re.S):
        attrs, body = match.group('attrs'), match.group('body')
        href = _attribute(attrs, 'href')
        if _kind_from_href(href) != expected_kind:
            continue
        url = absolute(href)
        if url in seen:
            continue
        seen.add(url)
        button = _clean(body)
        title = _clean(_attribute(attrs, 'title')) or button
        links.append({'url': url, 'title': title, 'button': button, 'kind': expected_kind})
    return links


def pagination_links(page, base_url):
    """Return one clear next-page link for S365's numeric category pagination."""
    parsed_base = urlparse(base_url)
    base_path = parsed_base.path.rstrip('/')
    current_match = re.search(r'/(\d+)$', base_path)
    current_page = int(current_match.group(1)) if current_match else 1
    category_path = re.sub(r'/\d+$', '', base_path)
    category_pattern = re.compile(r'^{}\/(\d+)\/?$'.format(re.escape(category_path))) if category_path else None
    numbered_pages = {}
    fallback_next = ''

    for match in re.finditer(r'<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>', page, re.I | re.S):
        attrs, body = match.group('attrs'), match.group('body')
        classes = _attribute(attrs, 'class').lower()
        label = _clean(body)
        href = _attribute(attrs, 'href')
        if not href:
            continue
        target = absolute(href, base_url)
        target_path = urlparse(target).path
        category_match = category_pattern.match(target_path) if category_pattern else None
        if category_match:
            numbered_pages[int(category_match.group(1))] = target
            continue
        if label.casefold() in ('következő', 'kovetkezo', 'next', '»', '›', '>>') or 'next' in classes:
            fallback_next = target

    if numbered_pages:
        total_pages = max(numbered_pages)
        next_url = numbered_pages.get(current_page + 1)
        if next_url:
            return [{'url': next_url, 'label': 'Következő oldal · {} / {}'.format(current_page, total_pages)}]
        return []
    if fallback_next and fallback_next.rstrip('/') != base_url.rstrip('/'):
        return [{'url': fallback_next, 'label': 'Következő oldal'}]
    return []


def browse(url):
    page = fetch_html(url)
    return parse_cards(page), page_metadata(page), pagination_links(page, url)


def series_seasons(url):
    page = fetch_html(url)
    return _detail_links(page, 'seasons', 'season', ('episodes', 'flowbar')), page_metadata(page)


def season_episodes(url):
    page = fetch_html(url)
    return _detail_links(page, 'episodes', 'episode', ('flowbar',)), page_metadata(page)


def search(query):
    query = query.strip()
    if not query:
        return []
    page = fetch_html('/javascript/fastsearch.php?s={}'.format(quote(query)))
    results, seen = [], set()
    for match in re.finditer(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", page, re.I):
        slug, url = match.group(1), absolute(match.group(1))
        if url in seen:
            continue
        seen.add(url)
        title_match = re.search(r'>\s*([^<]{2,160})\s*</td>', page[match.end():], re.I | re.S)
        results.append({'url': url, 'title': _clean(title_match.group(1)) if title_match else url.rsplit('/', 1)[-1], 'label2': '', 'thumb': '', 'kind': _kind_from_href(slug) or 'series'})
    return results


def _episode_slug(url):
    path = urlparse(url).path
    match = re.search(r'/r/([^/]+)', path)
    return match.group(1) if match else path.rstrip('/').rsplit('/', 1)[-1]


def _resolver_response(episode_url):
    """Optionally resolve using the owner's purpose-built playback API first."""
    template = _setting('resolver_url')
    if not template:
        return None
    try:
        endpoint = template.format(slug=quote(_episode_slug(episode_url)), episode_url=quote(episode_url, safe=''))
    except (KeyError, ValueError):
        raise S365Error('A lejátszási API sablonja hibás. Csak a {slug} és {episode_url} helyőrző használható.')
    headers = {'Accept': 'application/json'}
    token = _setting('resolver_token')
    if token:
        headers['Authorization'] = 'Bearer {}'.format(token)
    raw, _ = fetch(endpoint, headers=headers)
    try:
        data = json.loads(raw)
    except ValueError:
        raise S365Error('A lejátszási API nem érvényes JSON-választ adott.')
    stream_url = data.get('url') or data.get('stream_url')
    if not stream_url:
        return None
    return [{'label': data.get('label') or 'S365 lejátszás', 'url': stream_url, 'headers': data.get('headers') or {}, 'direct': True, 'referer': episode_url}]


def _stream_index_url(episode_page):
    for pattern in (r"window\.open\(\s*['\"](https?://[^'\"]+)", r"(?:href|data-url)\s*=\s*['\"](https?://[^'\"]*streams\.php[^'\"]*)"):
        match = re.search(pattern, episode_page, re.I | re.S)
        if match:
            return html_module.unescape(match.group(1))
    return ''


def _direct_url(url):
    return bool(re.search(r'\.(?:m3u8|mp4|webm|mkv)(?:[?#].*)?$', url, re.I))


def _label_from_url(url):
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith('www.') else (host or 'S365 forrás')


def _source_tags(*values):
    """Return only technical tags explicitly present in the source response."""
    text = ' '.join(value for value in values if value).upper()
    tags = []
    resolution_patterns = (
        (r'\b(?:2160P|4K|UHD)\b', '4K'),
        (r'\b1080P\b', '1080p'),
        (r'\b720P\b', '720p'),
        (r'\b480P\b', '480p'),
        (r'\b360P\b', '360p'),
        (r'\bHD\b', 'HD'),
        (r'\bSD\b', 'SD'),
    )
    for pattern, tag in resolution_patterns:
        if re.search(pattern, text):
            tags.append(tag)
            break
    for pattern, tag in ((r'\bHDR(?:10|10\+)?\b', 'HDR'), (r'\bHEVC\b|\bH\.265\b', 'HEVC'), (r'FELIRAT(?:OS)?', 'FEL')):
        if re.search(pattern, text) and tag not in tags:
            tags.append(tag)
    return tags


def _extract_sources(source_page, page_url):
    """Extract every SRZT source-table row, including same-domain /embed.php links."""
    sources, seen = [], set()

    def add(url, label, direct=None, technical_text=''):
        resolved = absolute(html_module.unescape(url).strip(), page_url)
        if not resolved.startswith(('http://', 'https://')) or resolved in seen:
            return
        seen.add(resolved)
        clean_label = _clean(label) or _label_from_url(resolved)
        sources.append({
            'label': clean_label,
            'tags': _source_tags(clean_label, technical_text),
            'url': resolved,
            'headers': {},
            'direct': _direct_url(resolved) if direct is None else direct,
            'referer': page_url,
        })

    # SRZT's actual video buttons live in table rows. Each row contains
    # provider, audio/language and a same-domain /embed.php/... page.
    for row_match in re.finditer(r'<tr\b[^>]*>(?P<row>.*?)</tr>', source_page, re.I | re.S):
        row = row_match.group('row')
        cells = [_clean(value) for value in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.I | re.S)]
        link_match = re.search(r'<a\b(?P<attrs>[^>]*)>', row, re.I | re.S)
        if len(cells) < 2 or not link_match:
            continue
        href = _attribute(link_match.group('attrs'), 'href')
        if '/embed.php/' not in href:
            continue
        label = ' — '.join(value for value in cells[:2] if value and value.upper() != 'MEGNÉZ')
        add(href, label or _attribute(link_match.group('attrs'), 'title'), False, ' '.join(cells + [_attribute(link_match.group('attrs'), 'title')]))

    for match in re.finditer(r'https?://[^\s\'"<>]+?\.(?:m3u8|mp4|webm|mkv)(?:\?[^\s\'"<>]*)?', source_page, re.I):
        add(match.group(0), 'Közvetlen videóforrás', True, match.group(0))
    for match in re.finditer(r'<(?:iframe|source|video)\b(?P<attrs>[^>]*)>', source_page, re.I | re.S):
        attrs = match.group('attrs')
        url = _attribute(attrs, 'src') or _attribute(attrs, 'data-src')
        if url:
            add(url, _attribute(attrs, 'title') or 'Beágyazott forrás', technical_text=_attribute(attrs, 'title'))
    for match in re.finditer(r'<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a>', source_page, re.I | re.S):
        attrs, body = match.group('attrs'), match.group('body')
        href = _attribute(attrs, 'href')
        if not href:
            continue
        resolved = absolute(href, page_url)
        host = urlparse(resolved).netloc.lower()
        if '/embed.php/' in urlparse(resolved).path:
            add(resolved, _clean(body) or _attribute(attrs, 'title'), False, _attribute(attrs, 'title'))
        elif host and host not in (urlparse(page_url).netloc.lower(), urlparse(catalog_base()).netloc.lower()):
            add(resolved, _clean(body) or _attribute(attrs, 'title'), technical_text=_attribute(attrs, 'title'))
    return sources


def _decode_base64_url(value):
    """Decode a base64-encoded full URL used by SRZT's iframe endpoint."""
    try:
        encoded = unquote(value).strip()
        encoded += '=' * (-len(encoded) % 4)
        candidate = b64decode(encoded).decode('utf-8', errors='strict').strip()
    except (ValueError, UnicodeError):
        return ''
    return candidate if candidate.startswith(('http://', 'https://')) else ''


def _unwrap_srzt_embed(source_url):
    """Read the local embed page and return the external host URL shown in its iframe."""
    parsed = urlparse(source_url)
    if '/embed.php/' not in parsed.path:
        return source_url, ''
    page, final_url = fetch(source_url)
    match = re.search(r'/iframe\.php\?url=([^\'"&\s]+)', page, re.I | re.S)
    if not match:
        raise S365Error('Az SRZT beágyazó oldalán nem található feloldható videóforrás.')
    target = _decode_base64_url(match.group(1))
    if not target:
        raise S365Error('Az SRZT beágyazó oldal videó-URL-je nem olvasható.')
    return target, final_url


def _availability_cache():
    raw = _setting(AVAILABILITY_CACHE_SETTING)
    try:
        loaded = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        loaded = {}
    if not isinstance(loaded, dict):
        return {}
    now = int(time.time())
    cache = {}
    for url, value in loaded.items():
        if not isinstance(value, dict):
            continue
        checked_at = int(value.get('checked_at', 0) or 0)
        if now - checked_at < AVAILABILITY_CACHE_TTL:
            cache[url] = {'available': bool(value.get('available')), 'checked_at': checked_at}
    return cache


def _save_availability_cache(cache):
    recent = sorted(cache.items(), key=lambda item: int(item[1].get('checked_at', 0) or 0), reverse=True)[:AVAILABILITY_CACHE_LIMIT]
    ADDON.setSetting(AVAILABILITY_CACHE_SETTING, json.dumps(dict(recent), separators=(',', ':')))


def episode_is_available(episode_url, cache=None):
    """Return False only for confirmed pending or source-less episode pages.

    Temporary network failures remain visible so a service outage cannot empty a Kodi list.
    """
    owns_cache = cache is None
    cache = cache if cache is not None else _availability_cache()
    cached = cache.get(episode_url)
    if cached is not None:
        return cached['available']
    available = True
    try:
        api_sources = _resolver_response(episode_url)
        if api_sources is not None:
            available = bool(api_sources)
        else:
            episode_page = fetch_html(episode_url)
            source_index = _stream_index_url(episode_page)
            if not source_index:
                available = False
            else:
                source_page, source_page_url = fetch(source_index)
                available = not PENDING_SOURCE_PATTERN.search(source_page) and bool(_extract_sources(source_page, source_page_url))
    except S365Error:
        # Do not hide content due to a transient HTTP or connection failure.
        available = True
    cache[episode_url] = {'available': available, 'checked_at': int(time.time())}
    if owns_cache:
        _save_availability_cache(cache)
    return available


def filter_available_episodes(episodes, progress=None, cancelled=None):
    """Hide only confirmed unavailable/pending episode cards and cache the result."""
    cache, filtered = _availability_cache(), []
    total = len(episodes)
    for index, episode in enumerate(episodes, 1):
        if cancelled and cancelled():
            # Keep uninspected entries visible when the user cancels the check.
            filtered.extend(episodes[index - 1:])
            break
        if progress:
            progress(index, total, episode.get('title', 'Epizód'))
        if episode_is_available(episode['url'], cache):
            filtered.append(episode)
    _save_availability_cache(cache)
    return filtered


def season_is_available(season_url, progress=None, cancelled=None):
    """A season is visible only when it has at least one confirmed available episode."""
    try:
        episodes, _ = season_episodes(season_url)
    except S365Error:
        return True
    return bool(filter_available_episodes(episodes, progress=progress, cancelled=cancelled))


def filter_available_seasons(seasons, progress=None, cancelled=None):
    filtered = []
    total = len(seasons)
    for index, season in enumerate(seasons, 1):
        if cancelled and cancelled():
            filtered.extend(seasons[index - 1:])
            break
        if progress:
            progress(index, total, season.get('title', 'Évad'))
        if season_is_available(season['url'], cancelled=cancelled):
            filtered.append(season)
    return filtered


def sources_for_episode(episode_url):
    """List sources exposed after the episode's 'Linkek megtekintése' action."""
    api_sources = _resolver_response(episode_url)
    if api_sources:
        return api_sources, page_metadata(fetch_html(episode_url))
    episode_page = fetch_html(episode_url)
    metadata = page_metadata(episode_page)
    source_index = _stream_index_url(episode_page)
    if not source_index:
        return [], metadata
    source_page, source_page_url = fetch(source_index)
    if PENDING_SOURCE_PATTERN.search(source_page):
        raise S365Error('Az epizód forrása még szinkronizálás alatt van. Próbáld meg később.')
    return _extract_sources(source_page, source_page_url), metadata


def resolve_with_resolveurl(source_url, referer=''):
    """Resolve a source through the SRZT embed page and then ResolveURL."""
    target_url, embed_referer = _unwrap_srzt_embed(source_url)
    if _direct_url(target_url):
        return target_url
    try:
        import resolveurl
    except ImportError:
        raise S365Error('A ResolveURL függőség nincs telepítve vagy nem tölthető be.')
    resolver_referer = embed_referer or referer
    resolver_input = '{}$${}'.format(target_url, resolver_referer) if resolver_referer else target_url
    media_file = resolveurl.HostedMediaFile(resolver_input)
    if not media_file:
        raise S365Error('A ResolveURL nem támogatja ezt a forrást: {}.'.format(_label_from_url(target_url)))
    resolved = media_file.resolve()
    if isinstance(resolved, dict):
        resolved = resolved.get('url') or resolved.get('link')
    if not resolved:
        raise S365Error('A ResolveURL nem tudta feloldani a kiválasztott forrást.')
    return resolved


def _probe_cache():
    """Load recent source facts only; resolved URLs themselves are never cached."""
    raw = _setting(PROBE_CACHE_SETTING)
    try:
        loaded = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        loaded = {}
    if not isinstance(loaded, dict):
        return {}
    now = int(time.time())
    return {
        key: value for key, value in loaded.items()
        if isinstance(value, dict) and now - int(value.get('checked_at', 0) or 0) < PROBE_CACHE_TTL
    }


def _save_probe_cache(cache):
    recent = sorted(cache.items(), key=lambda item: int(item[1].get('checked_at', 0) or 0), reverse=True)[:PROBE_CACHE_LIMIT]
    ADDON.setSetting(PROBE_CACHE_SETTING, json.dumps(dict(recent), ensure_ascii=False, separators=(',', ':')))


def _probe_key(source):
    return source.get('url', '')


def _apply_probe_metadata(source, entry):
    result = dict(source)
    result['tags'] = list(dict.fromkeys(list(result.get('tags', [])) + list(entry.get('tags', []))))
    if entry.get('duration'):
        result['duration'] = entry['duration']
    if entry.get('bitrate'):
        result['bitrate'] = entry['bitrate']
    result['probed'] = bool(entry.get('checked_at'))
    return result


def apply_cached_probe_metadata(sources):
    cache = _probe_cache()
    return [_apply_probe_metadata(source, cache[_probe_key(source)]) if _probe_key(source) in cache else source for source in sources]


def _split_stream_url(stream_url):
    media_url, separator, header_part = stream_url.partition('|')
    headers = dict(parse_qsl(header_part, keep_blank_values=True)) if separator else {}
    return media_url, headers


def _hls_probe(playlist):
    """Read public HLS master/media playlist facts without downloading video segments."""
    metadata = {'tags': []}
    resolutions = []
    for width, height in re.findall(r'RESOLUTION=(\d+)x(\d+)', playlist, re.I):
        resolutions.append((int(width), int(height)))
    if resolutions:
        metadata['tags'].append('{}p'.format(max(resolutions, key=lambda item: item[1])[1]))
    bandwidths = [int(value) for value in re.findall(r'(?:AVERAGE-)?BANDWIDTH=(\d+)', playlist, re.I)]
    if bandwidths:
        metadata['bitrate'] = '{:.1f} Mb/s'.format(max(bandwidths) / 1000000.0)
    durations = [float(value) for value in re.findall(r'#EXTINF:([0-9.]+)', playlist, re.I)]
    if durations:
        total = int(round(sum(durations)))
        metadata['duration'] = '{}:{:02d}'.format(total // 60, total % 60) if total < 3600 else '{}:{:02d}:{:02d}'.format(total // 3600, (total % 3600) // 60, total % 60)
    return metadata


def _best_hls_variant(playlist, base_url):
    """Return the highest declared master-playlist variant URL, if present."""
    candidates = []
    lines = [line.strip() for line in playlist.splitlines()]
    for index, line in enumerate(lines[:-1]):
        if not line.upper().startswith('#EXT-X-STREAM-INF:'):
            continue
        next_line = lines[index + 1]
        if not next_line or next_line.startswith('#'):
            continue
        resolution = re.search(r'RESOLUTION=(\d+)x(\d+)', line, re.I)
        bandwidth = re.search(r'(?:AVERAGE-)?BANDWIDTH=(\d+)', line, re.I)
        score = int(resolution.group(2)) if resolution else int(bandwidth.group(1)) if bandwidth else 0
        candidates.append((score, urljoin(base_url, next_line)))
    return max(candidates, key=lambda item: item[0])[1] if candidates else ''


def probe_source(source):
    """Resolve one source and extract lightweight HLS properties, when available."""
    stream_url = source.get('url', '') if source.get('direct') else resolve_with_resolveurl(source.get('url', ''), source.get('referer', ''))
    media_url, media_headers = _split_stream_url(stream_url)
    metadata = {'tags': _source_tags(media_url)}
    if '.m3u8' in media_url.lower() or '/hls/' in media_url.lower() or '/playlist/' in media_url.lower():
        playlist, final_url = fetch(media_url, headers=media_headers)
        hls_metadata = _hls_probe(playlist)
        variant_url = _best_hls_variant(playlist, final_url)
        if variant_url and not hls_metadata.get('duration'):
            variant_playlist, _ = fetch(variant_url, headers=media_headers)
            variant_metadata = _hls_probe(variant_playlist)
            hls_metadata['tags'] = list(dict.fromkeys(hls_metadata.get('tags', []) + variant_metadata.get('tags', [])))
            for key in ('duration', 'bitrate'):
                if variant_metadata.get(key) and not hls_metadata.get(key):
                    hls_metadata[key] = variant_metadata[key]
        metadata['tags'] = list(dict.fromkeys(metadata['tags'] + hls_metadata.get('tags', [])))
        metadata.update({key: value for key, value in hls_metadata.items() if key != 'tags' and value})
    return metadata


def probe_sources(sources, progress=None, cancelled=None):
    """Resolve sources one-by-one and store non-sensitive metadata for six hours."""
    cache = _probe_cache()
    enriched = []
    total = len(sources)
    for index, source in enumerate(sources, start=1):
        if cancelled and cancelled():
            break
        if progress:
            progress(index, total, source.get('label', 'Forrás'))
        key = _probe_key(source)
        try:
            metadata = probe_source(source)
            metadata['checked_at'] = int(time.time())
            cache[key] = metadata
            enriched.append(_apply_probe_metadata(source, metadata))
        except S365Error:
            enriched.append(source)
        except Exception:
            enriched.append(source)
    _save_probe_cache(cache)
    return enriched
