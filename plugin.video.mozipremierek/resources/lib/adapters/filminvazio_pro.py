# -*- coding: utf-8 -*-
"""Adapter for the user-provided plugin.video.filminvazio public routes."""
from __future__ import absolute_import

import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse

from .base import Adapter
from ..net import SourceUnavailable, get, get_json, text_only

BASE = 'https://filminvazio.pro/'
MIRROR = 'https://videaletoltes.com/'
PLUGIN = 'plugin://plugin.video.filminvazio/'
SEARCH_NONCE_FALLBACK = 'f620484b8f'


class Rows(HTMLParser):
    def __init__(self):
        super(Rows, self).__init__(convert_charrefs=True)
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cells = []
        self.cell_text = []
        self.href = ''
        self.rows = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'table':
            self.in_table = True
        elif self.in_table and tag == 'tr':
            self.in_row, self.cells, self.href = True, [], ''
        elif self.in_row and tag in ('td', 'th'):
            self.in_cell, self.cell_text = True, []
        elif self.in_row and tag == 'a' and a.get('href'):
            self.href = urljoin(MIRROR, a['href'])

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text.append(data)

    def handle_endtag(self, tag):
        if self.in_row and self.in_cell and tag in ('td', 'th'):
            self.cells.append(' '.join(' '.join(self.cell_text).split()))
            self.in_cell = False
        elif self.in_table and tag == 'tr':
            if len(self.cells) >= 3 and self.href and self.cells[0].lower() not in ('watch', 'watch online'):
                self.rows.append({'host': self.cells[0], 'quality': self.cells[1], 'language': self.cells[2], 'url': self.href})
            self.in_row = False
        elif tag == 'table':
            self.in_table = False


class Media(HTMLParser):
    def __init__(self):
        super(Media, self).__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('iframe', 'video', 'source'):
            value = a.get('src') or a.get('data-src') or a.get('data-url')
            if value:
                self.urls.append(urljoin(BASE, value))


class FilminvazioProAdapter(Adapter):
    adapter_id = 'filminvazio_pro'
    name = 'FILMINVÁZIÓ.PRO'

    def _nonce(self):
        body, _ = get(BASE)
        match = re.search(r'["\']nonce["\']\s*:\s*["\']([A-Za-z0-9]+)', body)
        if not match:
            match = re.search(r'\bnonce\s*[:=]\s*["\']([A-Za-z0-9]+)', body)
        return match.group(1) if match else SEARCH_NONCE_FALLBACK

    def search(self, query):
        api = urljoin(BASE, 'wp-json/dooplay/search/')
        data, _ = get_json(api + '?' + urlencode({'keyword': query, 'nonce': self._nonce()}), headers={'Referer': BASE})
        if not isinstance(data, dict) or 'error' in data:
            return []
        results = []
        for entry in data.values():
            if not isinstance(entry, dict) or not entry.get('url') or not entry.get('title'):
                continue
            url = urljoin(BASE, str(entry['url']))
            if urlparse(url).netloc.lower() != urlparse(BASE).netloc.lower():
                continue
            extra = entry.get('extra') if isinstance(entry.get('extra'), dict) else {}
            poster = urljoin(BASE, str(entry.get('img') or '')) if entry.get('img') else ''
            results.append({
                'title': text_only(str(entry['title'])), 'year': str(extra.get('date') or ''),
                'url': url, 'poster': poster, 'plot': '', 'adapter_id': self.adapter_id,
                'adapter_name': self.name
            })
        return results

    def _play_url(self, url):
        return PLUGIN + '?' + urlencode({'mode': 'play', 'url': url})

    def _final_url(self, url):
        try:
            body, final = get(url, headers={'Referer': MIRROR})
        except SourceUnavailable:
            return ''
        for href in re.findall(r'<a\b[^>]*href=["\']([^"\']+)', body, re.I):
            target = urljoin(final, unescape(href))
            host = urlparse(target).netloc.lower()
            if host and not (host == 'videaletoltes.com' or host.endswith('.videaletoltes.com')):
                return target
        host = urlparse(final).netloc.lower()
        if host and not (host == 'videaletoltes.com' or host.endswith('.videaletoltes.com')):
            return final
        return ''

    def sources(self, movie):
        body, _ = get(movie['url'])
        slug = urlparse(movie['url']).path.rstrip('/').split('/')[-1]
        out = []
        seen = set()
        mirror_url = urljoin(MIRROR, 'videa-film/%s/' % slug)
        try:
            table_html, _ = get(mirror_url, headers={'Referer': BASE})
            table = Rows()
            table.feed(table_html)
            for row in table.rows:
                target = self._final_url(row['url'])
                if not target or target in seen:
                    continue
                seen.add(target)
                out.append({
                    'host': row['host'], 'quality': row['quality'], 'language': row['language'],
                    'source_url': target, 'play_url': self._play_url(target), 'adapter_name': self.name
                })
        except SourceUnavailable:
            pass
        media = Media()
        media.feed(body)
        for raw in media.urls:
            target = self._final_url(raw)
            if not target or target in seen or 'youtube.com' in urlparse(target).netloc.lower():
                continue
            seen.add(target)
            host = urlparse(target).netloc.lower()
            if host.startswith('www.'):
                host = host[4:]
            out.append({'host': host, 'quality': '', 'language': '', 'source_url': target, 'play_url': self._play_url(target), 'adapter_name': self.name})
        return out


adapter = FilminvazioProAdapter()
