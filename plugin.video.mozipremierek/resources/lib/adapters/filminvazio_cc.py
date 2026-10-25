# -*- coding: utf-8 -*-
"""Adapter for the user-provided plugin.video.filminvaziocc addon."""
from __future__ import absolute_import

import json
import re
from html import unescape
from urllib.parse import urlencode, urljoin, urlparse

from .base import Adapter
from ..net import SourceUnavailable, get, get_json, post_json, text_only

BASE = 'https://filminvazio.cc/'
SUBMITTED_BASE = 'https://moziverzum.club/'
PLUGIN = 'plugin://plugin.video.filminvaziocc/'


class FilminvazioCcAdapter(Adapter):
    adapter_id = 'filminvazio_cc'
    name = 'FILMINVÁZIÓ.CC'

    def _search_config(self):
        body, _ = get(BASE)
        config = re.search(r'\bvar\s+dtGonza\s*=\s*\{(.*?)\};', body, re.I | re.S)
        if not config:
            raise SourceUnavailable('DooPlay search configuration missing')
        text = config.group(1)
        api = re.search(r'["\']api["\']\s*:\s*["\']([^"\']+)', text)
        nonce = re.search(r'["\']nonce["\']\s*:\s*["\']([^"\']+)', text)
        if not api or not nonce:
            raise SourceUnavailable('DooPlay API or nonce missing')
        api_url = urljoin(BASE, api.group(1))
        if urlparse(api_url).netloc.lower() != urlparse(BASE).netloc.lower():
            raise SourceUnavailable('Search API points outside the configured source domain')
        return api_url, nonce.group(1)

    def search(self, query):
        api, nonce = self._search_config()
        data, _ = get_json(api + '?' + urlencode({'keyword': query, 'nonce': nonce}), headers={'Referer': BASE})
        if isinstance(data, dict) and data.get('error'):
            return []
        entries = list(data.values()) if isinstance(data, dict) else data
        if not isinstance(entries, list):
            return []
        results = []
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get('title') or not entry.get('url'):
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

    def _submitted(self, slug, title):
        url = urljoin(SUBMITTED_BASE, 'film/%s/' % slug)
        try:
            body, _ = get(url, headers={'Referer': BASE})
        except SourceUnavailable:
            return []
        rows = []
        seen = set()
        for row in re.findall(r'<tr\b[^>]*>.*?</tr>', body, re.I | re.S):
            row = unescape(row)
            redirect = re.search(r'(?:window\.open\(["\']|href=["\'])(https?://moziverzum\.club/links/[^"\']+)', row, re.I)
            provider = re.search(r'<td[^>]*>.*?<a[^>]*>(.*?)</a>', row, re.I | re.S)
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.I | re.S)
            quality = re.search(r'class=["\'][^"\']*quality[^"\']*["\']>(.*?)</', row, re.I | re.S)
            if not redirect or not provider:
                continue
            host = text_only(provider.group(1)) or 'beküldött forrás'
            if redirect.group(1) in seen:
                continue
            seen.add(redirect.group(1))
            language = text_only(cells[2]) if len(cells) > 2 else ''
            level = text_only(quality.group(1)) if quality else ''
            rows.append({
                'host': host, 'quality': level, 'language': language,
                'play_url': PLUGIN + '?' + urlencode({'action': 'submitted', 'redirect': redirect.group(1), 'title': title}),
                'adapter_name': self.name, 'adapter_id': self.adapter_id,
                'submitted_redirect': redirect.group(1), 'parent_resolve_only': True
            })
        return rows

    def resolve_source_url(self, source):
        """Fetch the selected public DooPlay embed URL for parent-side resolution."""
        redirect = str(source.get('submitted_redirect') or '').strip()
        if redirect:
            parsed_redirect = urlparse(redirect)
            if (parsed_redirect.scheme != 'https'
                    or parsed_redirect.netloc.lower() not in ('moziverzum.club', 'www.moziverzum.club')
                    or not parsed_redirect.path.startswith('/links/')):
                raise SourceUnavailable('Submitted link is outside the configured public redirect path')
            _, final_url = get(redirect, headers={'Referer': SUBMITTED_BASE}, timeout=10)
            parsed_final = urlparse(final_url)
            if parsed_final.scheme not in ('http', 'https') or not parsed_final.netloc:
                return ''
            return final_url

        post = str(source.get('player_post') or '')
        nume = str(source.get('player_nume') or '')
        page = str(source.get('player_page') or '')
        if not post.isdigit() or not nume.isdigit() or not page:
            return ''
        api_url = urljoin(BASE, 'wp-admin/admin-ajax.php')
        if urlparse(api_url).netloc.lower() != urlparse(BASE).netloc.lower():
            raise SourceUnavailable('Player API points outside the configured source domain')
        data, _ = post_json(
            api_url,
            {'action': 'doo_player_ajax', 'post': post, 'nume': nume, 'type': 'movie'},
            headers={'Referer': page, 'Origin': BASE.rstrip('/')},
            timeout=10
        )
        embed = data.get('embed_url', '') if isinstance(data, dict) else ''
        if not isinstance(embed, str) or not embed.strip():
            return ''
        embed_url = urljoin(page, embed.strip())
        parsed = urlparse(embed_url)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            return ''
        return embed_url

    def sources(self, movie):
        body, _ = get(movie['url'])
        post = re.search(r'\bdata-post=["\'](\d+)', body, re.I)
        slug = urlparse(movie['url']).path.rstrip('/').split('/')[-1]
        title_match = re.search(r'<h1[^>]*>(.*?)</h1>', body, re.I | re.S)
        title = text_only(title_match.group(1)) if title_match else movie.get('title', '')
        rows = []
        seen = set()
        for match in re.finditer(r'<li\b[^>]*data-nume=["\'](\d+)[^>]*>(.*?)</li>', body, re.I | re.S):
            nume, block = match.group(1), match.group(2)
            host_match = re.search(r'class=["\'][^"\']*server[^"\']*["\'][^>]*>(.*?)</span>', block, re.I | re.S)
            host = text_only(host_match.group(1)) if host_match else 'ismeretlen host'
            quality_match = re.search(r'class=["\'][^"\']*quality[^"\']*["\'][^>]*>(.*?)</', block, re.I | re.S)
            quality = text_only(quality_match.group(1)) if quality_match else ''
            if (not post or nume in seen):
                continue
            seen.add(nume)
            play = PLUGIN + '?' + urlencode({
                'action': 'play', 'post': post.group(1), 'nume': nume,
                'page': movie['url'], 'title': title
            })
            rows.append({
                'host': host, 'quality': quality, 'language': '', 'play_url': play,
                'adapter_name': self.name, 'adapter_id': self.adapter_id,
                'player_post': post.group(1), 'player_nume': nume,
                'player_page': movie['url'], 'parent_resolve_only': True
            })
        rows.extend(self._submitted(slug, title))
        return rows


adapter = FilminvazioCcAdapter()
