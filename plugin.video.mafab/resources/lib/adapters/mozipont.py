# -*- coding: utf-8 -*-
"""Adapter for mozipont.com (same routes as the user's plugin.video.mozipont.catalog)."""
from __future__ import absolute_import

import re
from html import unescape
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import Adapter, detect_quality
from ..net import SourceUnavailable, get

BASE = 'https://mozipont.com'
PLUGIN = 'plugin://plugin.video.mozipont.catalog/'
CARD_PATH = re.compile(r'^/film/(\d+)/?$')          # series are listed by the add-on, not matched by title here
UNAVAILABLE = 'Ez a tartalom egyelőre még nem jött ki, vagy nincs hozzá megbízható forrás.'


class MoziPontAdapter(Adapter):
    adapter_id = 'mozipont'
    name = 'MOZIPONT'

    def search(self, query):
        body, final = get('%s/kereses?%s' % (BASE, urlencode({'q': query[:120]})), headers={'Referer': BASE + '/'})
        soup = BeautifulSoup(body, 'html.parser')
        out, seen = [], set()
        for card in soup.find_all('a', class_='media-card', href=True):
            match = CARD_PATH.match(urlparse(card['href']).path)
            title_el = card.find('strong')
            if not match or title_el is None or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            small = card.find('small')
            found = re.search(r'\b(?:19|20)\d{2}\b', small.get_text()) if small is not None else None
            img = card.find('img')
            src = (img.get('src') or img.get('data-src') or '') if img is not None else ''
            out.append({
                'title': ' '.join(title_el.get_text(' ', strip=True).split()),
                'year': found.group(0) if found else '',
                'url': '%s/nezes/%s' % (BASE, match.group(1)),      # the player page
                'poster': urljoin(BASE + '/', src) if src else '',
                'plot': '', 'adapter_id': self.adapter_id, 'adapter_name': self.name,
                'quality': detect_quality(card),
            })
        return out

    def sources(self, movie):
        url = movie['url']
        if not url.startswith(BASE + '/nezes/'):
            return []
        body, final = get(url, headers={'Referer': BASE + '/'})
        if UNAVAILABLE in body:
            return []
        iframe = re.search(r'<iframe\b([^>]*)>', body, re.I | re.S)
        if not iframe:
            return []
        embed = ''
        for name in ('src', 'data-t', 'data-src'):          # the page keeps the public player URL here
            found = re.search(r'\b' + name + r'\s*=\s*["\']([^"\']+)["\']', iframe.group(1), re.I)
            if found and unescape(found.group(1)).strip():
                embed = urljoin(BASE + '/', unescape(found.group(1)).strip())
                break
        if not embed.startswith(('http://', 'https://')):
            return []
        host = (urlparse(embed).hostname or '').lower()
        host = host[4:] if host.startswith('www.') else host
        content_id = url.rstrip('/').rsplit('/', 1)[-1]
        quality = detect_quality(BeautifulSoup(body, 'html.parser')) or movie.get('quality', '')
        return [{
            'host': host or 'mozipont', 'quality': quality, 'language': 'HU', 'source_url': embed,
            'play_url': PLUGIN + '?' + urlencode({'action': 'play_movie', 'id': content_id, 'title': movie.get('title', '')}),
            'adapter_name': self.name,
        }]


adapter = MoziPontAdapter()
