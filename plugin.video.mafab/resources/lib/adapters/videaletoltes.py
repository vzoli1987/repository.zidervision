# -*- coding: utf-8 -*-
"""Adapter for videaletoltes.com: the WordPress site behind the filminvazio.pro mirror tables."""
from __future__ import absolute_import

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from urllib.parse import quote_plus, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from .base import Adapter, detect_quality, normalize_mirror
from .filminvazio_pro import FilminvazioProAdapter, Media, Rows, MIRROR
from ..net import SourceUnavailable, get, get_json

MOVIE_PATH = re.compile(r'^/videa-film/[^/]+/?$')


class VidealetoltesAdapter(FilminvazioProAdapter):
    adapter_id = 'videaletoltes'
    name = 'VIDEALETOLTES'

    @staticmethod
    def _slug(text):
        plain = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii').lower()
        return re.sub(r'[^a-z0-9]+', '-', plain).strip('-')

    def _record(self, title, url, year='', poster='', quality=''):
        return {'title': title, 'year': str(year or ''), 'url': url, 'poster': poster, 'plot': '',
                'adapter_id': self.adapter_id, 'adapter_name': self.name, 'quality': quality}

    def _search_articles(self, soup, final):
        """DooPlay result list: <article> with a poster link and <div class="title"><a>."""
        out, seen = [], set()
        for art in soup.find_all('article'):
            link = art.select_one('.title a[href]') or art.select_one('.details a[href]')
            if link is None:
                continue
            url = urljoin(final, link['href'].split('#')[0])
            if not MOVIE_PATH.match(urlparse(url).path) or url in seen:
                continue
            title = ' '.join(link.get_text(' ', strip=True).split())
            if not title:
                continue
            seen.add(url)
            img = art.find('img')
            src = (img.get('data-src') or img.get('data-lazy-src') or img.get('src') or '') if img is not None else ''
            meta = art.select_one('.meta')
            year = re.search(r'\b(?:19|20)\d{2}\b', meta.get_text(' ', strip=True) if meta else '')
            out.append(self._record(title, url, year.group(0) if year else '',
                                    '' if (not src or 'no_image' in src) else urljoin(final, src), detect_quality(art)))
        return out

    def _search_html(self, query):
        body, final = get('%s?s=%s' % (MIRROR, quote_plus(query)), headers={'Referer': MIRROR})
        soup = BeautifulSoup(body, 'html.parser')
        out, seen = self._search_articles(soup, final), set()
        if out:
            return out
        for link in soup.find_all('a', href=True):
            url = urljoin(final, link['href'].split('#')[0])
            parsed = urlparse(url)
            if parsed.netloc.lower().replace('www.', '') != 'videaletoltes.com' or not MOVIE_PATH.match(parsed.path):
                continue
            img = link.find('img')
            title = ' '.join(link.get_text(' ', strip=True).split()) or (link.get('title') or '').strip()
            heading = link.find_parent(['h1', 'h2', 'h3', 'h4'])
            if not title and img is not None:
                title = (img.get('alt') or '').strip()      # poster-only link: the alt text is the title
            if not title or url in seen:
                continue
            seen.add(url)
            card = (heading or link).find_parent(['article', 'li', 'div']) or link
            year = re.search(r'\b(?:19|20)\d{2}\b', card.get_text(' ', strip=True).replace(title, '', 1))
            card_img = card.find('img')
            src = (card_img.get('data-src') or card_img.get('src') or '') if card_img is not None else ''
            out.append(self._record(title, url, year.group(0) if year else '', urljoin(final, src) if src else '',
                                    detect_quality(card)))
        return out

    def _search_rest(self, query):
        """The site's own JSON search (WordPress core, then DooPlay): works when the result page is built by script."""
        out = []
        try:
            data, _ = get_json('%swp-json/wp/v2/search?%s' % (MIRROR, urlencode({'search': query, 'per_page': 20})), headers={'Referer': MIRROR})
            for entry in data if isinstance(data, list) else []:
                url = str(entry.get('url') or '')
                if MOVIE_PATH.match(urlparse(url).path):
                    title = re.sub(r'<[^>]+>', '', str(entry.get('title') or '')).strip()
                    out.append(self._record(unescape(title), url))
        except (SourceUnavailable, AttributeError):
            pass
        if out:
            return out
        try:
            body, _ = get(MIRROR, headers={'Referer': MIRROR})
            nonce = re.search(r'["\']nonce["\']\s*:\s*["\']([A-Za-z0-9]+)', body)
            data, _ = get_json('%swp-json/dooplay/search/?%s' % (MIRROR, urlencode({'keyword': query, 'nonce': nonce.group(1) if nonce else ''})),
                               headers={'Referer': MIRROR})
            for entry in data.values() if isinstance(data, dict) else []:
                if isinstance(entry, dict) and MOVIE_PATH.match(urlparse(str(entry.get('url') or '')).path):
                    extra = entry.get('extra') if isinstance(entry.get('extra'), dict) else {}
                    out.append(self._record(unescape(str(entry.get('title') or '')), str(entry['url']), extra.get('date') or '', str(entry.get('img') or '')))
        except (SourceUnavailable, AttributeError):
            pass
        return out

    def _search_slug(self, query):
        """Last resort: the film page whose address is the slugified title (e.g. /videa-film/bunyosok/)."""
        slug = self._slug(query)
        if not slug:
            return []
        url = '%svidea-film/%s/' % (MIRROR, slug)
        try:
            body, final = get(url, headers={'Referer': MIRROR})
        except SourceUnavailable:
            return []
        soup = BeautifulSoup(body, 'html.parser')
        heading = soup.find('h1')
        og = soup.find('meta', attrs={'property': 'og:title'})
        title = ' '.join(heading.get_text(' ', strip=True).split()) if heading else ''
        title = title or ((og.get('content') or '').split(' - ')[0].split(' | ')[0].strip() if og else '') or query
        if not (soup.find('table') or soup.find('iframe')):
            return []
        year = re.search(r'\b(?:19|20)\d{2}\b', soup.get_text(' ', strip=True)[:3000])
        return [self._record(title, final, year.group(0) if year else '', '', detect_quality(soup))]

    def search(self, query):
        for method in (self._search_html, self._search_rest, self._search_slug):
            try:
                found = method(query)
            except SourceUnavailable:
                found = []
            if found:
                return found
        return []

    def _final_url_for(self, url, expected_host=''):
        """/links/<code>/ shows a countdown and then `<a id="link" href=...>`; other anchors are ads."""
        try:
            body, final = get(url, headers={'Referer': MIRROR})
        except SourceUnavailable:
            return ''
        mirror_hosts = ('videaletoltes.com',)

        def outside(href):
            target = urljoin(final, unescape(href))
            host = urlparse(target).netloc.lower().replace('www.', '')
            return target if host and host not in mirror_hosts and not host.endswith('.videaletoltes.com') else ''
        for tag in re.findall(r'<a\b[^>]*>', body, re.I):
            if re.search(r'\bid=["\']link["\']', tag, re.I):
                href = re.search(r'href=["\']([^"\']+)', tag, re.I)
                if href and outside(href.group(1)):
                    return normalize_mirror(outside(href.group(1)))[0]
        expected = (expected_host or '').lower().replace('www.', '').strip()
        hrefs = re.findall(r'<a\b[^>]*href=["\']([^"\']+)', body, re.I)
        if re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', expected or ''):
            for href in hrefs:
                target = outside(href)
                host = urlparse(target).netloc.lower().replace('www.', '') if target else ''
                if host == expected or host.endswith('.' + expected):
                    return normalize_mirror(target)[0]
        for href in hrefs:
            if outside(href):
                return normalize_mirror(outside(href))[0]
        return ''

    def sources(self, movie):
        body, final = get(movie['url'], headers={'Referer': MIRROR})
        out, seen = [], set()
        table = Rows()
        table.feed(body)
        media = Media()
        media.feed(body)
        quality_default = movie.get('quality', '')
        raw = [(row['url'], row) for row in table.rows] + [(url, None) for url in media.urls]
        with ThreadPoolExecutor(max_workers=8) as pool:
            finals = list(pool.map(lambda pair: self._final_url_for(pair[0], pair[1]['host'] if pair[1] else ''), raw))
        for (_, row), target in zip(raw, finals):
            if not target or target in seen or 'youtube.com' in urlparse(target).netloc.lower():
                continue
            seen.add(target)
            host = urlparse(target).netloc.lower()
            host = host[4:] if host.startswith('www.') else host
            out.append({
                'host': host if (urlparse(target).netloc == 'voe.sx' or not row) else (row['host'] or host),
                'quality': (row['quality'] if row else '') or quality_default,
                'language': row['language'] if row else '', 'source_url': target,
                'play_url': self._play_url(target), 'adapter_name': self.name,
            })
        return out


adapter = VidealetoltesAdapter()
