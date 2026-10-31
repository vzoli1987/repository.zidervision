# -*- coding: utf-8 -*-
"""Adapter for FilmDepo.hu using its public search and detail pages.

Search follows the supplied Kodi add-on flow (`/search.php?q=...`) and parses
movie cards linking to `details.php?id=...`. The public player embed is fetched
only when playback starts, so Kodi's host progress dialog remains active.
"""
from __future__ import absolute_import

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlparse

from .base import Adapter
from ..net import SourceUnavailable, get, text_only

BASE = 'https://filmdepo.hu/'
DETAIL_RE = re.compile(r'(?:^|/)details\.php\?[^#]*\bid=\d+', re.I)
MAX_RESULTS = 50
VOID_TAGS = frozenset(('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'))
TITLE_CLASSES = frozenset(('fw-semibold', 'top50-title', 'fd-title'))


class Node(object):
    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = []


def _classes(node):
    return set((node.attrs.get('class') or '').split())


def _walk(node):
    for child in node.children:
        if isinstance(child, Node):
            yield child
            for nested in _walk(child):
                yield nested


def _node_text(node):
    parts = []
    for child in node.children:
        if isinstance(child, Node):
            parts.append(_node_text(child))
        else:
            parts.append(child)
    return ' '.join(' '.join(' '.join(parts).split()).split())


class DocumentParser(HTMLParser):
    """Small stdlib-only DOM tree sufficient for FilmDepo's card selectors."""
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.root = Node('document')
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag.lower(), dict(attrs))
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag.lower(), dict(attrs)))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _valid_filmdepo_url(url):
    parsed = urlparse(url or '')
    host = (parsed.hostname or '').lower()
    return parsed.scheme in ('http', 'https') and (host == 'filmdepo.hu' or host.endswith('.filmdepo.hu'))


def _detail_url(href, base_url):
    absolute = urljoin(base_url, unescape(href or '').replace('\\/', '/'))
    parsed = urlparse(absolute)
    return absolute if _valid_filmdepo_url(absolute) and DETAIL_RE.search(parsed.path + ('?' + parsed.query if parsed.query else '')) else ''


def clean_title(value):
    value = text_only(value or '')
    value = re.sub(r'\s*\(\s*(?:19|20)\d{2}\s*\)\s*', ' ', value)
    value = re.sub(r'^\s*(?:Keresési találatok\s*:?|Filmek\s*:?|Keresés\s*:)\s*', '', value, flags=re.I)
    return ' '.join(value.split()).strip(' .-_/')


def _quality(value):
    match = re.search(r'\b(2160p|4k|1440p|2k|1080p|720p|480p|360p|hd|sd|dvd|cam|ts)\b', value or '', re.I)
    if not match:
        return ''
    quality = match.group(1).lower()
    if quality in ('2160p', '4k'):
        return '4K'
    if quality in ('1440p', '2k'):
        return '1440p'
    return quality if quality.endswith('p') else quality.upper()


def _player_entries(body, page_url):
    """Return all configured movie players, excluding trailer/preview entries."""
    decoded = unescape(body or '').replace('\\/', '/')
    config = re.search(r'(?:const|let|var)\s+FD_URLS\s*=\s*\{(.*?)\}\s*;', decoded, re.I | re.S)
    entries = []
    seen = set()
    if config:
        pairs = re.finditer(r'["\']?([A-Za-z][\w-]*)["\']?\s*:\s*["\']([^"\']*)["\']', config.group(1))
        for match in pairs:
            key = match.group(1).strip().lower()
            if any(marker in key for marker in ('trailer', 'preview', 'teaser', 'youtube', 'imdb')):
                continue
            url = _normalize_player_url(match.group(2), page_url)
            host = (urlparse(url).hostname or '').lower() if url else ''
            if host in ('youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'):
                continue
            if url and url not in seen:
                seen.add(url)
                entries.append((key, url))

    parser = DocumentParser()
    parser.feed(decoded)
    for node in _walk(parser.root):
        if node.tag != 'iframe':
            continue
        url = _normalize_player_url(node.attrs.get('src', ''), page_url)
        host = (urlparse(url).hostname or '').lower() if url else ''
        if url and host not in ('youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com') and url not in seen:
            seen.add(url)
            entries.append(('iframe', url))
    return entries


def _normalize_player_url(value, page_url):
    value = unescape((value or '').strip()).replace('\\/', '/')
    if not value:
        return ''
    if value.startswith('//'):
        value = 'https:' + value
    elif value.startswith('/'):
        value = urljoin(page_url, value)
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return ''
    return value


def _poster_from(card, page_url):
    for node in _walk(card):
        if node.tag == 'img':
            image = node.attrs.get('src') or node.attrs.get('data-src') or node.attrs.get('data-original') or ''
            if image:
                urls = list(re.finditer(r'https?://', image, re.I))
                if len(urls) > 1:
                    image = image[urls[-1].start():]
                return urljoin(page_url, image.replace('\\', ''))
    for node in [card] + list(_walk(card)):
        style = node.attrs.get('style', '')
        if 'background-image' in style.lower():
            match = re.search(r'url\([\'\"]?([^\'\")]+)', style, re.I)
            if match:
                return urljoin(page_url, match.group(1).replace('\\', ''))
    return ''


def _card_fields(card, page_url):
    descendants = list(_walk(card))
    link = next((node for node in descendants if node.tag == 'a' and _detail_url(node.attrs.get('href', ''), page_url)), None)
    if link is None and card.tag == 'a' and _detail_url(card.attrs.get('href', ''), page_url):
        link = card
    if link is None:
        return None
    href = _detail_url(link.attrs.get('href', ''), page_url)
    if not href:
        return None

    title_node = next((node for node in descendants if _classes(node) & TITLE_CLASSES), None)
    raw_title = _node_text(title_node) if title_node else _node_text(link)
    if not raw_title:
        raw_title = link.attrs.get('title', '') or link.attrs.get('aria-label', '')
    raw_title = text_only(raw_title)
    year_match = re.search(r'\b((?:19|20)\d{2})\b', raw_title)
    title = clean_title(raw_title)
    if not title or len(title) < 2:
        return None

    plot_node = next((node for node in descendants if 'line-height:1.25' in (node.attrs.get('style') or '').replace(' ', '').lower() or 'fd-plot' in _classes(node)), None)
    plot = _node_text(plot_node) if plot_node else ''
    return {
        'title': title,
        'year': year_match.group(1) if year_match else '',
        'quality': _quality(raw_title),
        'url': href,
        'poster': _poster_from(card, page_url),
        'plot': plot,
    }


class FilmDepoAdapter(Adapter):
    adapter_id = 'filmdepo'
    name = 'FILMDEPO'

    def search(self, query):
        query = ' '.join((query or '').split()).strip()
        if not query:
            return []
        search_url = urljoin(BASE, 'search.php?q=' + quote_plus(query))
        body, final_url = get(search_url, headers={'Referer': BASE}, timeout=15)
        parser = DocumentParser()
        parser.feed(body)

        nodes = list(_walk(parser.root))
        cards = [node for node in nodes if 'col' in _classes(node) or {'d-flex', 'gap-3'}.issubset(_classes(node))]
        if not cards:
            cards = [node for node in nodes if node.tag == 'a' and _detail_url(node.attrs.get('href', ''), final_url)]

        results, seen = [], set()
        for card in cards:
            item = _card_fields(card, final_url)
            if not item or item['url'] in seen:
                continue
            seen.add(item['url'])
            item.update({'adapter_id': self.adapter_id, 'adapter_name': self.name})
            results.append(item)
            if len(results) >= MAX_RESULTS:
                break
        return results

    def sources(self, movie):
        page_url = movie.get('url', '')
        if not _valid_filmdepo_url(page_url) or not DETAIL_RE.search(urlparse(page_url).path + ('?' + urlparse(page_url).query if urlparse(page_url).query else '')):
            return []
        body, final_url = get(page_url, headers={'Referer': BASE}, timeout=15)
        entries = _player_entries(body, final_url)
        if not entries:
            # Some FilmDepo pages still expose the player only through the legacy
            # `main:` pattern; defer extraction until the clicked row's progress bar.
            return [{
                'host': 'FilmDepo', 'quality': movie.get('quality', ''), 'language': 'HU',
                'source_page_url': page_url, 'parent_resolve_only': True,
                'allow_raw_source': True, 'adapter_id': self.adapter_id,
                'adapter_name': self.name, 'play_url': page_url,
            }]

        counts = {}
        sources = []
        for key, player_url in entries:
            host = (urlparse(player_url).hostname or 'FilmDepo').lower()
            if host.startswith('www.'):
                host = host[4:]
            counts[host] = counts.get(host, 0) + 1
            label = host if counts[host] == 1 else '%s #%d' % (host, counts[host])
            sources.append({
                'host': label, 'quality': movie.get('quality', ''), 'language': 'HU',
                'source_page_url': page_url, 'source_url': player_url,
                'source_key': key, 'parent_resolve_only': True,
                'allow_raw_source': True, 'adapter_id': self.adapter_id,
                'adapter_name': self.name, 'play_url': page_url,
            })
        return sources

    def resolve_source_url(self, source):
        page_url = source.get('source_page_url', '')
        if not _valid_filmdepo_url(page_url) or not DETAIL_RE.search(urlparse(page_url).path + ('?' + urlparse(page_url).query if urlparse(page_url).query else '')):
            raise SourceUnavailable('Érvénytelen FilmDepo-adatlap URL')

        body, final_url = get(page_url, headers={'Referer': BASE}, timeout=15)
        decoded = unescape(body).replace('\\/', '/')
        main_match = re.search(r'main\s*:\s*["\']([^"\']+)["\']', decoded, re.I)
        video_url = main_match.group(1).strip() if main_match else ''
        if not video_url:
            parser = DocumentParser()
            parser.feed(decoded)
            iframe = next((node for node in _walk(parser.root) if node.tag == 'iframe' and re.search(r'video|embed|player|stream', node.attrs.get('src', ''), re.I)), None)
            video_url = iframe.attrs.get('src', '').strip() if iframe else ''
        if not video_url:
            raise SourceUnavailable('A FilmDepo-adatlapon nem található nyilvános player URL')

        video_url = unescape(video_url).replace('\\/', '/')
        if video_url.startswith('//'):
            video_url = 'https:' + video_url
        elif video_url.startswith('/'):
            video_url = urljoin(final_url, video_url)
        parsed = urlparse(video_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            raise SourceUnavailable('A FilmDepo player URL nem érvényes HTTP/HTTPS link')
        return video_url


adapter = FilmDepoAdapter()
