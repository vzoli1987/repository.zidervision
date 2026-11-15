# -*- coding: utf-8 -*-
"""Public catalog and player adapter for the user-provided MoziBox addon."""
from __future__ import absolute_import

from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse

from .base import Adapter
from ..net import SourceUnavailable, get, text_only

BASE = 'https://mozibox.hu/'
ALLOWED_SITE_HOSTS = ('mozibox.hu', 'www.mozibox.hu')


def _is_mozibox_url(url):
    parsed = urlparse(url or '')
    return parsed.scheme == 'https' and parsed.netloc.lower() in ALLOWED_SITE_HOSTS


def _clean_iframe_url(value, page_url):
    value = str(value or '').strip()
    # The supplied addon page has occasionally emitted an encoded quote at
    # the end of the iframe src attribute. HTMLParser already decodes entities.
    value = value.rstrip(' \t\r\n\"\'')
    if not value:
        return ''
    result = urljoin(page_url, value)
    parsed = urlparse(result)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return ''
    return result


class _MovieCardParser(HTMLParser):
    """Extract the user-provided addon’s article.movie-card records."""
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.movies = []
        self.current = None
        self.capture = ''
        self.capture_depth = 0
        self.capture_text = []

    @staticmethod
    def _classes(attrs):
        return set((attrs.get('class') or '').split())

    def handle_starttag(self, tag, raw_attrs):
        attrs = dict(raw_attrs)
        classes = self._classes(attrs)
        if tag == 'article' and 'movie-card' in classes:
            self.current = {'title': [], 'year': [], 'genre': [], 'poster': '', 'url': ''}
        elif self.current is not None:
            if self.capture:
                self.capture_depth += 1
            if tag == 'img' and not self.current['poster']:
                self.current['poster'] = attrs.get('src') or attrs.get('data-src') or ''
            if tag == 'a' and 'btn-primary' in classes and attrs.get('href'):
                self.current['url'] = attrs['href']
            field = ''
            if tag == 'h2' and 'movie-title' in classes:
                field = 'title'
            elif tag == 'div' and 'movie-year' in classes:
                field = 'year'
            elif tag == 'div' and 'movie-meta' in classes:
                field = 'genre'
            if field:
                self.capture = field
                self.capture_depth = 1
                self.capture_text = []

    def handle_endtag(self, tag):
        if self.capture:
            self.capture_depth -= 1
            if self.capture_depth <= 0:
                self.current[self.capture] = text_only(''.join(self.capture_text))
                self.capture = ''
                self.capture_depth = 0
                self.capture_text = []
        if tag == 'article' and self.current is not None:
            record = self.current
            self.current = None
            if record.get('title') and record.get('url'):
                self.movies.append(record)

    def handle_data(self, data):
        if self.capture:
            self.capture_text.append(data)


class _IframeParser(HTMLParser):
    """Prefer iframe sources inside .player-frame, as the supplied addon does."""
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.player_depth = 0
        self.iframes = []

    def handle_starttag(self, tag, raw_attrs):
        attrs = dict(raw_attrs)
        classes = set((attrs.get('class') or '').split())
        if tag == 'div':
            if self.player_depth:
                self.player_depth += 1
            elif 'player-frame' in classes:
                self.player_depth = 1
        elif tag == 'iframe' and attrs.get('src'):
            self.iframes.append((self.player_depth > 0, attrs['src']))

    def handle_endtag(self, tag):
        if tag == 'div' and self.player_depth:
            self.player_depth -= 1


class MoziBoxAdapter(Adapter):
    adapter_id = 'mozibox'
    name = 'MOZIBOX'

    def search(self, query):
        url = BASE + 'index.php?' + urlencode({'q': query})
        body, final_url = get(url, timeout=15)
        if not _is_mozibox_url(final_url):
            raise SourceUnavailable('MoziBox keresés külső domainre irányított')
        parser = _MovieCardParser()
        parser.feed(body)
        results = []
        seen = set()
        for item in parser.movies:
            movie_url = urljoin(final_url, item['url'])
            if not _is_mozibox_url(movie_url) or movie_url in seen:
                continue
            seen.add(movie_url)
            poster = urljoin(final_url, item['poster']) if item.get('poster') else ''
            results.append({
                'title': item['title'],
                'year': item.get('year', ''),
                'url': movie_url,
                'poster': poster,
                'plot': item.get('genre', ''),
                'adapter_id': self.adapter_id,
                'adapter_name': self.name
            })
        return results

    def sources(self, movie):
        movie_url = str(movie.get('url') or '')
        if not _is_mozibox_url(movie_url):
            raise SourceUnavailable('A MoziBox adatlap URL-je nem megbízható domainen található')
        body, final_url = get(movie_url, timeout=15)
        if not _is_mozibox_url(final_url):
            raise SourceUnavailable('A MoziBox adatlap külső domainre irányított')
        parser = _IframeParser()
        parser.feed(body)
        iframes = sorted(parser.iframes, key=lambda value: not value[0])
        if not iframes:
            return []
        embed_url = _clean_iframe_url(iframes[0][1], final_url)
        if not embed_url:
            return []
        host = urlparse(embed_url).netloc.lower()
        return [{
            'host': host or 'MoziBox lejátszó',
            'quality': '',
            'language': '',
            'play_url': '',
            'source_url': embed_url,
            'parent_resolve_only': True,
            'resolveurl_required': True,
            'adapter_id': self.adapter_id,
            'adapter_name': self.name
        }]


adapter = MoziBoxAdapter()
