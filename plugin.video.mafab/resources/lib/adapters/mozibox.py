# -*- coding: utf-8 -*-
"""Adapter for mozibox.hu (same routes as the user's plugin.video.mozibox)."""
from __future__ import absolute_import

import re
from urllib.parse import quote, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import Adapter, detect_quality
from ..net import SourceUnavailable, get

BASE = 'https://mozibox.hu'
PLUGIN = 'plugin://plugin.video.mozibox/'


class MoziBoxAdapter(Adapter):
    adapter_id = 'mozibox'
    name = 'MOZIBOX'

    def search(self, query):
        body, final = get('%s/index.php?q=%s' % (BASE, quote(query)), headers={'Referer': BASE + '/'})
        soup = BeautifulSoup(body, 'html.parser')
        out, seen = [], set()
        for card in soup.find_all('article', class_='movie-card'):
            title_el = card.find('h2', class_='movie-title')
            link = card.find('a', class_='btn-primary') or card.find('a', href=True)
            if title_el is None or link is None or not link.get('href'):
                continue
            url = urljoin(BASE + '/', link['href'])
            if url in seen:
                continue
            seen.add(url)
            year_el = card.find('div', class_='movie-year')
            found = re.search(r'\b(?:19|20)\d{2}\b', year_el.get_text()) if year_el else None
            img = card.find('img')
            out.append({
                'title': ' '.join(title_el.get_text(' ', strip=True).split()),
                'year': found.group(0) if found else '',
                'url': url,
                'poster': urljoin(BASE + '/', img['src']) if img is not None and img.get('src') else '',
                'plot': '', 'adapter_id': self.adapter_id, 'adapter_name': self.name,
                'quality': detect_quality(card),
            })
        return out

    def sources(self, movie):
        body, final = get(movie['url'], headers={'Referer': BASE + '/'})
        soup = BeautifulSoup(body, 'html.parser')
        frame = soup.find('div', class_='player-frame')
        iframes = (frame.find_all('iframe') if frame is not None else []) or soup.find_all('iframe')
        quality = detect_quality(soup) or movie.get('quality', '')
        out, seen = [], set()
        for iframe in iframes:
            src = iframe.get('src') or iframe.get('data-src') or ''
            if not src:
                continue
            embed = urljoin(final, src)
            if embed in seen or not embed.startswith(('http://', 'https://')):
                continue
            seen.add(embed)
            host = urlparse(embed).netloc.lower()
            host = host[4:] if host.startswith('www.') else host
            out.append({
                'host': host or 'mozibox', 'quality': quality, 'language': 'HU', 'source_url': embed,
                'play_url': PLUGIN + '?' + urlencode({'mode': 'play', 'url': movie['url'], 'title': movie.get('title', '')}),
                'adapter_name': self.name,
            })
        return out


adapter = MoziBoxAdapter()
