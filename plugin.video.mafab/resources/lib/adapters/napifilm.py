# -*- coding: utf-8 -*-
"""Adapter for plugin.video.napifilm; playback remains delegated to that addon."""
from __future__ import absolute_import

import re
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse

from .base import Adapter
from ..net import get, text_only

BASE = 'https://napifilm.hu/'
PLUGIN = 'plugin://plugin.video.napifilm/'


class LinkParser(HTMLParser):
    def __init__(self):
        super(LinkParser, self).__init__(convert_charrefs=True)
        self.links = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a' and a.get('href'):
            self.current = {'href': a['href'], 'text': [], 'image': ''}
        elif tag == 'img' and self.current is not None:
            self.current['image'] = a.get('data-src') or a.get('src') or ''
        elif tag == 'iframe':
            src = a.get('src') or a.get('data-src') or a.get('data-url')
            if src:
                self.links.append({'embed': src})

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            self.current['text'] = ' '.join(' '.join(self.current['text']).split())
            self.links.append(self.current)
            self.current = None


def tidy_title(value):
    value = re.sub(r'\s*\(\d{4}\)\s*', ' ', text_only(value))
    value = re.sub(r'\s+(?:teljes\s+)?(?:online\s+)?(?:film|sorozat)(?:\s+online)?\s+magyarul\b.*$', '', value, flags=re.I)
    return ' '.join(value.split()).strip()


class NapifilmAdapter(Adapter):
    adapter_id = 'napifilm'
    name = 'NAPIFILM'

    def search(self, query):
        url = BASE + '?' + urlencode({'search': query})
        body, final = get(url)
        parser = LinkParser()
        parser.feed(body)
        results, seen = [], set()
        for link in parser.links:
            href = link.get('href', '')
            absolute = urljoin(final, href)
            parsed = urlparse(absolute)
            path = parsed.path.lower()
            raw_title = link.get('text', '')
            if not raw_title or '-teljes-film' not in path or absolute in seen:
                continue
            seen.add(absolute)
            year_match = re.search(r'\b((?:19|20)\d{2})\b', raw_title)
            results.append({
                'title': tidy_title(raw_title), 'year': year_match.group(1) if year_match else '',
                'url': absolute, 'poster': urljoin(final, link.get('image', '')) if link.get('image') else '',
                'plot': '', 'adapter_id': self.adapter_id, 'adapter_name': self.name
            })
        return results

    def sources(self, movie):
        body, final = get(movie['url'])
        parser = LinkParser()
        parser.feed(body)
        embeds = []
        for link in parser.links:
            if link.get('embed'):
                url = urljoin(final, link['embed'])
                if 'twitter.com' not in url.lower() and url not in embeds:
                    embeds.append(url)
        if not embeds:
            return []
        # Current NapiFilm detail route resolves its available iframes automatically.
        # One honest row is shown rather than listing multiple hosts that would all play the same first source.
        player = PLUGIN + '?' + urlencode({'action': 'play', 'value': movie['url']})
        if len(embeds) == 1:
            host = urlparse(embeds[0]).netloc.lower()
            if host.startswith('www.'):
                host = host[4:]
            label = host or 'forrás'
        else:
            label = 'automatikus tárhelyválasztás (%d forrás)' % len(embeds)
        source_url = embeds[0] if len(embeds) == 1 else ''
        return [{'host': label, 'quality': '', 'language': '', 'source_url': source_url, 'play_url': player, 'adapter_name': self.name}]


adapter = NapifilmAdapter()
