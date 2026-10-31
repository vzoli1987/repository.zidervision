# -*- coding: utf-8 -*-
"""Mafab.hu scraper. No Kodi imports here so it can be tested standalone.

The site layout is discovered at runtime (menu links, search form, next-page
link) instead of hard-coding URLs, so small site changes do not break it.
If the site changes a lot, adjust the constants in the CONFIG block.
"""
import datetime
import hashlib
import json
import os
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# ----------------------------------------------------------------- CONFIG --
BASE = 'https://www.mafab.hu/'

HEADERS = {
    'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'hu-HU,hu;q=0.9,en;q=0.5',
}

# Main-menu labels looked up on the home page: (label, kind)
# kind "video"  -> items are played directly
# kind "film"   -> items open a detail folder (info + trailers)
MENU_LABELS = [
    ('Előzetesek', 'video'),
    ('Kulisszák mögött', 'video'),
    ('Filmklip', 'video'),
    ('Interjú', 'video'),
    ('Legjobb Filmek', 'film'),
    ('Új filmadatlapok', 'film'),
    ('Legjobb Sorozatok', 'series'),
    ('Sorozatok', 'series'),
]

# Menu links seen in the site's own navigation (paths are relative to BASE).
STATIC_MENU = [
    ('Jelenleg a mozikban', 'cinema/premier/jelenleg-a-mozikban', 'film'),
    ('Hamarosan a mozikban', 'cinema/premier/hamarosan-a-mozikban', 'film'),
    ('Korábbi premierek', 'cinema/premier/korabbi-premierek', 'film'),
    ('Streaming premierek', 'vod/streaming-premierek', 'film'),
    ('Netflix: megjelenések', 'netflix/megjelenesek/filmek-es-sorozatok/', 'film'),
    ('Netflix: népszerű filmek', 'netflix/nepszeru-filmek', 'film'),
    ('Netflix: népszerű sorozatok', 'netflix/nepszeru-sorozatok', 'series'),
]

PAIR_LABELS = {
    'rendező': 'directors', 'rendezo': 'directors',
    'író': 'writers', 'iro': 'writers', 'forgatókönyv': 'writers', 'forgatókönyvíró': 'writers',
    'szereplők': 'cast', 'szereplo': 'cast', 'színészek': 'cast', 'főszereplők': 'cast',
    'műfaj': 'genres', 'műfajok': 'genres',
    'ország': 'countries', 'országok': 'countries', 'gyártó ország': 'countries',
    'gyártási ország': 'countries', 'származási ország': 'countries',
    'játékidő': 'runtime', 'hossz': 'runtime', 'játékidő (perc)': 'runtime',
    'bemutató': 'premiered', 'magyarországi bemutató': 'premiered', 'bemutató dátuma': 'premiered',
    'premier': 'premiered', 'magyarországi premier': 'premiered', 'premier dátuma': 'premiered',
    'hazai bemutató': 'premiered', 'hazai premier': 'premiered', 'mozis bemutató': 'premiered',
    'gyártási év': 'year', 'megjelenés éve': 'year',
    'korhatár': 'mpaa', 'besorolás': 'mpaa',
    'forgalmazó': 'studios', 'gyártó': 'studios', 'stúdió': 'studios', 'gyártó cég': 'studios',
    'eredeti cím': 'originaltitle', 'angol cím': 'originaltitle',
}
LIST_FIELDS = {'directors', 'writers', 'cast', 'genres', 'countries', 'studios'}

# Streaming providers: (slug in /vod/korabbi-premierek/<slug>, name, colour)
PROVIDERS = [
    ('netflix', 'Netflix', 'FFE50914'),
    ('hbo', 'HBO Max', 'FFB26BFF'),
    ('tvgo', 'Telekom FilmPremier', 'FFE20074'),
    ('appletv', 'Apple TV', 'FFD1D5DB'),
    ('amazon', 'Amazon Prime Video', 'FF00A8E1'),
    ('disney', 'Disney+', 'FF4F7CFF'),
    ('skyshowtime', 'SkyShowtime', 'FFFF8C42'),
]
PROVIDER_BY_SLUG = {slug: (name, color) for slug, name, color in PROVIDERS}
# How a platform badge on a list card is recognised: tooltip text, click-event name, logo file
PROVIDER_PATTERNS = [
    ('netflix', re.compile(r'netflix', re.I)),
    ('hbo', re.compile(r'hbo|\bmax\b', re.I)),
    ('tvgo', re.compile(r'telekom|tv\s?go|tvgo|filmpremier', re.I)),
    ('appletv', re.compile(r'apple', re.I)),
    ('amazon', re.compile(r'amazon|prime', re.I)),
    ('disney', re.compile(r'disney', re.I)),
    ('skyshowtime', re.compile(r'sky\s?showtime', re.I)),
]
PROVIDER_LOGOS = {'24': 'netflix', '25': 'hbo', '31': 'appletv', '32': 'amazon', '45': 'skyshowtime'}
VOD_PAGE = BASE + 'vod/%s'   # % 'streaming-premierek' (upcoming) or 'korabbi-premierek' (earlier)
# page areas that hold site-wide navigation, never a film's own streaming info
NAV_CLASS_RE = re.compile(r'rsubmenu|page-header|main-category|navbar|footer|mfb_nav|submenu', re.I)

TV_PAGE = BASE + 'tv/tv_kinalat'
TV_AJAX = BASE + 'tv/index.php'
TIME_RE = re.compile(r'(?<!\d)([01]?\d|2[0-3])[:.]([0-5]\d)(?!\d)')

# People (celebrities) list: /stars/szemelyisegek/<page>/?yrf=&yrt=&genre=<role>&cat=undefined
PEOPLE_BASE = BASE + 'stars/szemelyisegek/'
PEOPLE_ROLES = [('', 'Legnépszerűbb személyiségek'), ('41', 'Színészek'), ('5', 'Rendezők'),
                ('17', 'Írók'), ('19', 'Zeneszerzők'), ('6', 'Operatőrök')]
BIRTHDAYS_PAGE = BASE + 'stars/szuletesnapok/'
PERSON_RE = re.compile(r'/people/[^/]*-(\d+)\.html?$')
BIRTH_RE = re.compile(r'szül\.\s*((?:1[6-9]|20)\d{2})\.\s*(\d{1,2})\.\s*(\d{1,2})')
SIDEBAR_RE = re.compile(r'rightside|sidebox|most-read|most_visited|submenu|rsubmenu|footer|page-header|navbar', re.I)

# Detail/item pages end with "-<id>.html"
ITEM_RE = re.compile(r'-(\d+)\.html?$')
# First path segments that are never movies/series
SKIP_SEGMENTS = {'user', 'users', 'stars', 'star', 'hirek', 'news', 'magazin',
                 'people', 'celebs', 'kozosseg', 'community', 'profil'}

YT_RE = re.compile(
    r'(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|v/)|youtu\.be/|'
    r'i\.ytimg\.com/vi/|img\.youtube\.com/vi/)([A-Za-z0-9_-]{11})')
YT_KEY_RE = re.compile(
    r'["\'](?:youtubeId|youtube_id|videoId|ytid|yt_id)["\']\s*[:=]\s*["\']([A-Za-z0-9_-]{11})["\']')
DIRECT_RE = re.compile(r'https?:[^\s"\'<>\\]+?\.(?:m3u8|mp4)(?:\?[^\s"\'<>\\]*)?')
# Trailing year, with or without brackets: "A kaptár (2026)", "A kaptár 2026".
# Only plausible release years, so "Blade Runner 2049" keeps its title.
YEAR_RE = re.compile(r'\s*[\(\[]?\b((?:19\d{2}|20[0-2]\d|2030))\b[\)\]]?\s*$')
NEXT_TEXTS = {'következő', 'tovább', '›', '»', '>', 'next', 'következő oldal'}


HU_MONTHS = {'január': 1, 'február': 2, 'március': 3, 'április': 4, 'május': 5, 'június': 6,
             'július': 7, 'augusztus': 8, 'szeptember': 9, 'október': 10, 'november': 11,
             'december': 12, 'jan': 1, 'feb': 2, 'márc': 3, 'ápr': 4, 'máj': 5, 'jún': 6,
             'júl': 7, 'aug': 8, 'szept': 9, 'okt': 10, 'nov': 11, 'dec': 12}


def parse_date(value):
    """'2026. 10. 29.', '2026-10-29' or '2026. október 29.' -> '2026-10-29' ('' if no full date)."""
    text = (value or '').lower()
    num = re.search(r'((?:19|20)\d{2})\D{1,3}(\d{1,2})\D{1,3}(\d{1,2})(?!\d)', text)
    if num and 1 <= int(num.group(2)) <= 12 and 1 <= int(num.group(3)) <= 31:
        return '%s-%02d-%02d' % (num.group(1), int(num.group(2)), int(num.group(3)))
    named = re.search(r'((?:19|20)\d{2})\.?\s*([a-záéíóöőúüű]+)\.?\s*(\d{1,2})', text)
    if named and named.group(2) in HU_MONTHS and 1 <= int(named.group(3)) <= 31:
        return '%s-%02d-%02d' % (named.group(1), HU_MONTHS[named.group(2)], int(named.group(3)))
    return ''


# Series cues. "sorozatgyilkos" or "események sorozata" must NOT count, so only precise phrases do.
_L = r'a-záéíóöőúüű'
SERIES_TITLE_RE = re.compile(r'(?<![%s])(?:\d+\.\s*évad|évad|season\s*\d+|sorozat|series)(?![%s])' % (_L, _L), re.I)
SERIES_PLOT_RE = re.compile(
    r'(?<![%s])(?:'
    r'\d+\.\s*évad\w*|évad(?:ban|ában|ot|jában|zár\w*|nyit\w*)?|epizód\w*|season\s*\d+'
    r'|miniszéria|minisorozat\w*|(?:tv|tévé|web|anime|streaming|televíziós)-?sorozat\w*'
    r'|(?:dráma|krimi|vígjáték|komédia|thriller|horror|sci-?fi|animációs|rajzfilm|valóság|dokumentum|romantikus'
    r'|akció|kaland|fantasy|szatíra|antológia|szkeccskomédia|szappan|családi|háborús|történelmi)sorozat\w*'
    r'|(?:a|az|ez|az új|a nagy sikerű|a népszerű)\s+sorozat(?:ban|ot|ból|nak|hoz)?'
    r')(?![%s])' % (_L, _L), re.I)


def clean_channel(value):
    """'21:00 STORY4' / 'STORY4 - 21:00-22:30' -> 'STORY4'."""
    value = re.sub(r'(?<!\d)(?:[01]?\d|2[0-3])[:.][0-5]\d(?!\d)', ' ', value or '')
    value = re.sub(r'\s+', ' ', value).strip(' \t-\u2013\u2014|\u2022:,')
    return value


def guess_series(title, plot=''):
    """True when the title or plot clearly refers to a TV series. A hint, not a certainty."""
    return bool(SERIES_TITLE_RE.search(title or '') or SERIES_PLOT_RE.search(plot or ''))


class ScrapeError(Exception):
    pass


def split_year(value):
    """'A kaptár 2026' -> ('A kaptár', 2026). Leaves titles that are only a year alone."""
    value = ' '.join((value or '').split())
    match = YEAR_RE.search(value)
    if match and value[:match.start()].strip():
        return value[:match.start()].strip(), int(match.group(1))
    return value, None


def decode_body(resp):
    """Decode a response: UTF-8 first (never trust charset guessing), then the
    declared charset, then Latin-2 which is the usual Hungarian legacy encoding."""
    raw = resp.content
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    declared = re.search(br'charset=["\']?([A-Za-z0-9_-]+)', raw[:4096])
    for enc in (declared.group(1).decode('ascii') if declared else None,
                'iso-8859-2', 'cp1250'):
        if enc:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
    return raw.decode('utf-8', 'replace')


class Scraper(object):
    def __init__(self, cache_dir=None, ttl_hours=6, debug=False, log=None):
        self.cache_dir = cache_dir
        self.last_search_people = []
        self.ttl = int(ttl_hours) * 3600
        self.debug = debug
        self.log = log or (lambda msg: None)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if cache_dir and not os.path.isdir(cache_dir):
            os.makedirs(cache_dir, exist_ok=True)

    # ------------------------------------------------------------- fetch --
    def _cache_path(self, url):
        return os.path.join(self.cache_dir,
                            hashlib.md5(url.encode('utf-8')).hexdigest() + '.html')

    def get_html(self, url):
        path = self._cache_path(url) if self.cache_dir else None
        if path and self.ttl > 0 and os.path.exists(path):
            if time.time() - os.path.getmtime(path) < self.ttl:
                with open(path, 'r', encoding='utf-8') as fh:
                    return fh.read()
        self.log('GET %s' % url)
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ScrapeError(str(exc))
        html = decode_body(resp)
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as fh:
                    fh.write(html)
                if self.debug:
                    with open(os.path.join(self.cache_dir, 'last.html'), 'w',
                              encoding='utf-8') as fh:
                        fh.write('<!-- %s -->\n%s' % (url, html))
            except OSError:
                pass
        return html

    def get_soup(self, url):
        return BeautifulSoup(self.get_html(url), 'html.parser')

    # -------------------------------------------------------------- menu --
    def discover_menu(self):
        """Return [(label, url, kind)] for known menu labels found on the home page."""
        soup = self.get_soup(BASE)
        wanted = {label.lower(): kind for label, kind in MENU_LABELS}
        found = {}
        for a in soup.find_all('a', href=True):
            text = a.get_text(' ', strip=True).lower()
            if text in wanted and text not in found:
                href = urljoin(BASE, a['href'])
                if href.rstrip('/') != BASE.rstrip('/') and not href.endswith('#'):
                    found[text] = (a.get_text(' ', strip=True), href, wanted[text])
        # keep the order defined in MENU_LABELS, then the fixed links
        menu = [found[label.lower()] for label, _ in MENU_LABELS
                if label.lower() in found]
        known = set(url.rstrip('/') for _, url, _ in menu)
        for label, path, kind in STATIC_MENU:
            url = urljoin(BASE, path)
            if url.rstrip('/') not in known:
                menu.append((label, url, kind))
        return menu

    # ------------------------------------------------------------- lists --
    @staticmethod
    def _img_url(img, base_url):
        if img is None:
            return ''
        for attr in ('data-src', 'data-original', 'data-lazy-src', 'src'):
            val = img.get(attr)
            if val and not val.startswith('data:'):
                return urljoin(base_url, val)
        return ''

    @staticmethod
    def provider_from_badge(a):
        """Provider slug for a '.premiere-data--platform a' badge, or ''."""
        img = a.find('img')
        clicked = re.search(r"'([^']+?)\s+click'", a.get('onclick') or '')
        hay = ' '.join([a.get('title') or '', clicked.group(1) if clicked else '',
                        (img.get('alt') or '') if img else ''])
        for slug, pattern in PROVIDER_PATTERNS:
            if pattern.search(hay):
                return slug
        logo = re.search(r'/logo/(\d+)\.', (img.get('src') or '') if img else '')
        return PROVIDER_LOGOS.get(logo.group(1), '') if logo else ''

    def parse_cards(self, cards, base_url):
        """mafab's movie listing cards: title, year, art, plot, genres, premiere, platform."""
        out, seen = [], set()
        for card in cards:
            link = None
            for a in card.find_all('a', href=True):
                if ITEM_RE.search(urlparse(a['href'].split('#')[0]).path):
                    link = a
                    break
            if link is None:
                continue
            href = urljoin(base_url, link['href'].split('#')[0])
            if href in seen:
                continue
            seen.add(href)
            title_el = card.select_one('.movie-title')
            title = ' '.join((title_el.get_text(' ', strip=True) if title_el else
                              (link.get('title') or '')).split())
            if not title:
                continue
            clean, year_in_title = split_year(title)
            year_el = card.select_one('.movie-year')
            year = None
            if year_el is not None:
                found = re.search(r'(?:19|20)\d{2}', year_el.get_text())
                year = int(found.group(0)) if found else None
            thumb = ''
            holder = card.select_one('.image--grid[data-src]') or card.select_one('[data-src]')
            if holder is not None:
                thumb = urljoin(base_url, holder['data-src'])
            elif card.find('img'):
                thumb = self._img_url(card.find('img'), base_url)
            rating = None
            badge = card.select_one('.movie-rating')
            if badge is not None:
                found = re.search(r'\bcp(\d{1,3})\b', ' '.join(badge.get('class') or []))
                if found and int(found.group(1)) > 0:
                    rating = round(int(found.group(1)) / 10.0, 1)
            desc = card.select_one('.movie-desc')
            date_el = card.select_one('.premiere-data--date')
            providers = []
            for a in card.select('.premiere-data--platform a'):
                slug = self.provider_from_badge(a)
                if slug and slug not in providers:
                    providers.append(slug)
            out.append({
                'url': href, 'title': title if not year_in_title and year else clean,
                'thumb': thumb, 'year': year or year_in_title, 'rating': rating,
                'plot': ' '.join(desc.get_text(' ', strip=True).split()) if desc else '',
                'genres': [g.get_text(strip=True) for g in card.select('.genres-list a')],
                'premiered': parse_date(date_el.get_text(' ', strip=True)) if date_el else '',
                'providers': providers,
            })
        return out

    def parse_search_items(self, rows, base_url):
        """Search result rows (.search-item-movie): title, year, rating, thumb, genres, credits, series flag."""
        out, seen = [], set()
        for row in rows:
            link = row.select_one('h4 a[href]') or row.find('a', href=ITEM_RE)
            if link is None:
                continue
            href = urljoin(base_url, link['href'].split('#')[0])
            if href in seen:
                continue
            seen.add(href)
            t = row.select_one('.movie_title')
            title = ' '.join((t.get_text(' ', strip=True) if t else (link.get('title') or '')).split())
            if not title:
                continue
            clean, year = split_year(link.get('title') or '')
            if not year:
                small = row.select_one('small.pull-left')
                found = re.search(r'(?:19|20)\d{2}', small.get_text()) if small else None
                year = int(found.group(0)) if found else None
            rating = None
            rate = row.select_one('.movie_rate')
            if rate is not None:
                found = re.search(r'\bcp(\d{1,3})\b', ' '.join(rate.get('class') or []))
                if found and int(found.group(1)) > 0:
                    rating = round(int(found.group(1)) / 10.0, 1)
            img = row.find('img')
            kind_link = row.select_one('small a[href*="/sorozatok/"]')
            original = ''
            for sm in row.find_all('small'):
                if sm.find('a', href=re.compile('/(sorozatok|filmek)/[a-z-]+/$')) and '(' in sm.get_text():
                    original = sm.get_text(' ', strip=True).split('(', 1)[1].rstrip(') ')
                    break
            credits = []
            for cls, label in (('staff', 'Rendező'), ('actors', 'Szereplők')):
                p = row.select_one('p.' + cls)
                if p is not None:
                    names = [a.get_text(strip=True) for a in p.find_all('a')]
                    if names:
                        credits.append((label, names))
            item = {
                'url': href, 'title': title, 'thumb': self._img_url(img, base_url) if img else '',
                'year': year, 'rating': rating, 'plot': '',
                'genres': [g.get_text(strip=True) for g in row.select('small a[href*="genre="]')],
                'premiered': '', 'providers': [],
                'directors': next((n for l, n in credits if l == 'Rendező'), []),
                'cast': next((n for l, n in credits if l == 'Szereplők'), []),
                'original_title': original,
            }
            if kind_link is not None:
                item['is_series'] = True
            out.append(item)
        return out

    def parse_search_people(self, soup, base_url):
        """The 'Hírességek' block of a search page (empty when it only says 'Nincs találat')."""
        head = next((h for h in soup.find_all('h3') if 'hírességek' in h.get_text().lower()), None)
        if head is None:
            return []
        parts = []
        for sib in head.next_siblings:
            if getattr(sib, 'name', None) in ('h2', 'h3'):
                break
            parts.append(str(sib))
        mini = BeautifulSoup(''.join(parts), 'html.parser')
        return self.parse_people(mini, base_url)

    def parse_items(self, soup, base_url, exclude_sidebar=False):
        """Collect movie/series/video links with title and thumbnail."""
        rows = soup.select('.search-item-movie')
        if rows:    # search page
            return self.parse_search_items(rows, base_url)
        cards = soup.select('.mfb-movie-listing-item')
        if cards:   # a real listing: ignore sidebar/trending films around it
            return self.parse_cards(cards, base_url)
        items = {}
        for a in soup.find_all('a', href=True):
            href = urljoin(base_url, a['href'].split('#')[0])
            parsed = urlparse(href)
            if 'mafab.hu' not in parsed.netloc or not ITEM_RE.search(parsed.path):
                continue
            if exclude_sidebar and any(
                    SIDEBAR_RE.search(' '.join(p.get('class') or []) + ' ' + (p.get('id') or ''))
                    or p.name in ('nav', 'header', 'footer')
                    for p in a.parents if getattr(p, 'name', None)):
                continue
            segs = [s for s in parsed.path.split('/') if s]
            if segs and segs[0].lower() in SKIP_SEGMENTS:
                continue
            img = a.find('img')
            title = (a.get('title') or (img.get('alt') if img else '') or
                     a.get_text(' ', strip=True) or '').strip()
            entry = items.setdefault(href, {'url': href, 'title': '', 'thumb': '', 'year_hint': None, 'rating': None})
            if not entry['year_hint']:
                holder = a.find_next_sibling('span', class_='year') or (
                    a.parent.find('span', class_='year') if a.parent is not None else None)
                if holder is not None:
                    found = re.search(r'(?:19|20)\d{2}', holder.get_text())
                    entry['year_hint'] = int(found.group(0)) if found else None
            if title and (not entry['title'] or len(title) < len(entry['title'])
                          and len(title) > 2):
                entry['title'] = title
            if not entry['thumb']:
                entry['thumb'] = self._img_url(img, base_url)
            if entry.get('rating') is None:
                badge = a.find('span', class_=re.compile(r'movie_rate'))
                if badge is not None:
                    found = re.search(r'\bcp(\d{1,3})\b', ' '.join(badge.get('class') or []))
                    if found and int(found.group(1)) > 0:
                        entry['rating'] = round(int(found.group(1)) / 10.0, 1)
        result = []
        for entry in items.values():
            if not entry['title']:
                continue
            entry['title'], entry['year'] = split_year(entry['title'])
            entry['year'] = entry['year'] or entry.pop('year_hint', None)
            entry.pop('year_hint', None)
            result.append(entry)
        return result

    @staticmethod
    def find_next(soup, base_url):
        """URL of the next page: rel=next, the '.pagination' active item's neighbour, or a 'Tovább »' link."""
        link = soup.find('a', rel=lambda v: v and 'next' in v, href=True)
        if link is None:
            pager = soup.select_one('ul.pagination')
            if pager is not None:
                active = pager.select_one('li.active')
                sibling = active.find_next_sibling('li') if active is not None else None
                anchor = sibling.find('a', href=True) if sibling is not None else None
                if anchor is not None:
                    link = anchor
        if link is None:
            for a in soup.find_all('a', href=True):
                text = a.get_text(' ', strip=True).lower().strip()
                if text in NEXT_TEXTS or text.startswith(('tovább', 'következő', 'next')) or text.endswith(('»', '›')):
                    link = a
                    break
        if link is None:
            link = soup.select_one('li.next a[href]')
        return urljoin(base_url, link['href']) if link else None

    def list_page(self, url, exclude_sidebar=False):
        soup = self._last_soup = self.get_soup(url)
        return self.parse_items(soup, url, exclude_sidebar), self.find_next(soup, url)

    def home_items(self):
        return self.list_page(BASE)[0]

    # ------------------------------------------------------------ search --
    def search_url(self, query):
        soup = self.get_soup(BASE)
        for form in soup.find_all('form'):
            field = form.find('input', attrs={'type': lambda v: v in (None, 'text', 'search')})
            if field is None or not field.get('name'):
                continue
            action = urljoin(BASE, form.get('action') or BASE)
            if (form.get('method') or 'get').lower() != 'get':
                continue
            params = {field['name']: query}
            for hidden in form.find_all('input', attrs={'type': 'hidden'}):
                if hidden.get('name'):
                    params.setdefault(hidden['name'], hidden.get('value', ''))
            req = requests.Request('GET', action, params=params).prepare()
            return req.url
        raise ScrapeError('search form not found on the home page')

    def search_urls(self, query):
        """Candidate result URLs, lazily: the site's own /search/ pattern first, the home-page form last."""
        seen = set()
        for url in (BASE + 'search/&search=' + quote_plus(query), BASE + 'search/?search=' + quote_plus(query)):
            seen.add(url)
            yield url
        try:
            url = self.search_url(query)
        except ScrapeError:
            return
        if url not in seen:
            yield url

    def search(self, query):
        """First candidate URL that really yields films (sidebar films do not count)."""
        last = None
        for url in self.search_urls(query):
            try:
                items, nxt = self.list_page(url, exclude_sidebar=True)
            except ScrapeError as exc:
                last = exc
                continue
            if items:
                self.last_search_people = self.parse_search_people(self._last_soup, url)
                return items, nxt
        if last is not None:
            raise last
        return [], None

    # ------------------------------------------------------------ detail --
    @staticmethod
    def _meta(soup, *names):
        for name in names:
            tag = (soup.find('meta', attrs={'property': name}) or
                   soup.find('meta', attrs={'name': name}))
            if tag and tag.get('content'):
                return tag['content'].strip()
        return ''

    @staticmethod
    def youtube_ids(html):
        ids = []
        for rx in (YT_RE, YT_KEY_RE):
            for vid in rx.findall(html):
                if vid not in ids:
                    ids.append(vid)
        return ids

    def parse_detail(self, url):
        html = self.get_html(url)
        soup = BeautifulSoup(html, 'html.parser')
        title = self._meta(soup, 'og:title') or (soup.title.get_text(strip=True) if soup.title else '')
        return {
            'title': title,
            'plot': self._meta(soup, 'og:description', 'description'),
            'poster': self._meta(soup, 'og:image'),
            'youtube': self.youtube_ids(html),
        }

    def resolve(self, url):
        """Return [(label, playable_url)] for a page. YouTube ids use the YouTube add-on."""
        html = self.get_html(url)
        soup = BeautifulSoup(html, 'html.parser')
        base = self._meta(soup, 'og:title') or 'Video'
        out = []
        for vid in self.youtube_ids(html):
            out.append(('%s [YouTube %s]' % (base, vid),
                        'plugin://plugin.video.youtube/play/?video_id=%s' % vid))
        direct = []
        og_video = self._meta(soup, 'og:video', 'og:video:url', 'og:video:secure_url')
        if og_video:
            direct.append(og_video)
        for src in soup.select('video source[src], video[src]'):
            direct.append(src.get('src'))
        direct.extend(DIRECT_RE.findall(html.replace('\\/', '/')))
        seen = set()
        for link in direct:
            link = urljoin(url, link)
            if link in seen or '.m3u8' not in link and '.mp4' not in link:
                continue
            seen.add(link)
            out.append((os.path.basename(urlparse(link).path) or link,
                        '%s|Referer=%s&User-Agent=%s' % (link, BASE, HEADERS['User-Agent'])))
        return out


    # ---------------------------------------------------------------- TV --
    @staticmethod
    def _field(soup, field_id, default=''):
        el = soup.find(id=field_id)
        if el is None:
            return default
        if el.name == 'select':
            opt = el.find('option', selected=True) or el.find('option')
            return opt.get('value', default) if opt else default
        if (el.get('type') or '').lower() == 'checkbox':
            return 1 if el.has_attr('checked') else 0
        return el.get('value', default)

    def tv_form(self):
        """Read the TV filter form defaults from the page, as the site's tv.js does."""
        soup = self.get_soup(TV_PAGE)
        today = datetime.date.today().strftime('%Y-%m-%d')
        form = {
            'date': self._field(soup, 'tv_date', today) or today,
            'type_movies': self._field(soup, 'type_movies', 1),
            'type_series': self._field(soup, 'type_series', 1),
            'type_other': self._field(soup, 'type_other', 0),
            'rating_range': self._field(soup, 'rating_range', '0,100') or '0,100',
            'years_range': self._field(soup, 'years_range', '') or '',
            'fulltext': '',
            'order': self._field(soup, 'tv_order', '') or '',
            'set_favorites': self._field(soup, 'set_favorites', ''),
            'page_type': self._field(soup, 'tv_page_type', ''),
            'page_subtype': self._field(soup, 'tv_page_type', ''),
        }
        days = []
        select = soup.find('select', id='tv_date')
        if select is not None:
            for opt in select.find_all('option'):
                if opt.get('value'):
                    days.append((opt.get_text(' ', strip=True) or opt['value'], opt['value']))
        return form, days

    def tv_days(self):
        form, days = self.tv_form()
        return days or [(form['date'], form['date'])]

    @staticmethod
    def parse_tv_html(html, base_url=BASE):
        """Extract (date, time, channel, title, year, url, thumb) rows from the AJAX fragment."""
        soup = BeautifulSoup(html or '', 'html.parser')
        rows, seen, current_date = [], set(), ''

        def is_movie(tag):
            return (tag.name == 'a' and tag.get('href') and
                    ITEM_RE.search(urlparse(tag['href'].split('#')[0]).path) is not None)

        for el in soup.find_all(True):
            classes = el.get('class') or []
            if 'tv-listing-title' in classes:
                current_date = (el.get('data-title') or el.get_text(' ', strip=True)).strip()
                continue
            if not is_movie(el):
                continue
            href = urljoin(base_url, el['href'].split('#')[0])
            node = el
            for _ in range(6):
                parent = node.parent
                if parent is None or parent.name in ('body', '[document]'):
                    break
                if any(is_movie(x) and urljoin(base_url, x['href'].split('#')[0]) != href
                       for x in parent.find_all('a', href=True)):
                    break
                node = parent
            text = node.get_text(' ', strip=True)
            match = TIME_RE.search(text)
            when = '%s:%s' % (match.group(1).zfill(2), match.group(2)) if match else ''
            channel = ''
            # the channel element often repeats the start time ("21:00 STORY4"): keep the name only
            for chan_el in node.find_all(attrs={'class': re.compile('channel|csatorna', re.I)}):
                img = chan_el if chan_el.name == 'img' else chan_el.find('img')
                raw = ((img.get('alt') or img.get('title') or '') if img is not None else '') \
                    or chan_el.get_text(' ', strip=True)
                channel = clean_channel(raw)
                if channel:
                    break
            if not channel:
                for img in node.find_all('img'):
                    if re.search(r'channel|csatorn|logo', ' '.join([img.get('src') or '', img.get('class') and ' '.join(img['class']) or '']), re.I):
                        channel = clean_channel(img.get('alt') or img.get('title') or '')
                        if channel:
                            break
            img = el.find('img')
            title = (el.get('title') or (img.get('alt') if img else '') or
                     el.get_text(' ', strip=True) or '').strip()
            if not title:
                continue
            key = (href, when, current_date)
            if key in seen:
                continue
            seen.add(key)
            clean, year = split_year(title)
            rows.append({'date': current_date, 'time': when, 'channel': channel.strip(),
                         'title': clean, 'year': year, 'url': href,
                         'thumb': Scraper._img_url(img, base_url) if img else ''})
        return rows

    def _tv_post(self, date=None, page=1, **overrides):
        """POST the same request tv.js sends. Returns (rows, total_pages)."""
        form, _ = self.tv_form()
        data = dict(form)
        if date:
            data['date'] = date
        data['page'] = int(page)
        data.update(overrides)
        headers = {'X-Requested-With': 'XMLHttpRequest', 'Referer': TV_PAGE,
                   'Origin': BASE.rstrip('/'), 'Accept': 'application/json, text/javascript, */*; q=0.01'}
        self.log('POST %s %s' % (TV_AJAX, data))
        try:
            resp = self.session.post(TV_AJAX, data=data, headers=headers, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise ScrapeError(str(exc))
        body = decode_body(resp)
        if self.debug and self.cache_dir and not overrides:
            try:
                with open(os.path.join(self.cache_dir, 'last_tv.json'), 'w', encoding='utf-8') as fh:
                    fh.write(body)
            except OSError:
                pass
        try:
            payload = json.loads(body)
        except ValueError:
            raise ScrapeError('TV response is not JSON')
        rows = self.parse_tv_html(payload.get('html', ''), TV_PAGE)
        try:
            pages = int(payload.get('pages') or 1)
        except (TypeError, ValueError):
            pages = 1
        return rows, pages

    def tv_series_urls(self, date=None, max_pages=10):
        """URLs of everything the site itself files under 'sorozatok' that day (filter: series only).
        Cached for an hour per day. Raises ScrapeError if the site cannot be asked."""
        path = None
        if self.cache_dir:
            path = os.path.join(self.cache_dir, 'tvseries_%s.json' % re.sub(r'\W', '', str(date or 'today')))
            try:
                if time.time() - os.path.getmtime(path) < 3600:
                    with open(path, 'r', encoding='utf-8') as fh:
                        return set(json.load(fh))
            except (OSError, ValueError, TypeError):
                pass
        urls, page, pages = set(), 1, 1
        while page <= pages and page <= max_pages:
            rows, pages = self._tv_post(date, page, type_movies=0, type_series=1, type_other=0)
            urls.update(r['url'] for r in rows)
            page += 1
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as fh:
                    json.dump(sorted(urls), fh)
            except OSError:
                pass
        return urls

    def tv_program(self, date=None, page=1):
        """One page of the schedule. Each row gets 'is_series' True/False when the site's own
        series filter could be asked, else None. Returns (rows, total_pages)."""
        rows, pages = self._tv_post(date, page)
        try:
            series = self.tv_series_urls(date)
        except ScrapeError as exc:
            self.log('series filter unavailable: %s' % exc)
            series = None
        for row in rows:
            row['is_series'] = None if series is None else row['url'] in series
        return rows, pages

    # ---------------------------------------------------------- metadata --
    @staticmethod
    def _ld_nodes(data):
        if isinstance(data, list):
            for entry in data:
                for node in Scraper._ld_nodes(entry):
                    yield node
        elif isinstance(data, dict):
            yield data
            for node in Scraper._ld_nodes(data.get('@graph')):
                yield node

    @staticmethod
    def _names(value):
        if value is None:
            return []
        if isinstance(value, (str, int, float)):
            return [str(value).strip()] if str(value).strip() else []
        if isinstance(value, dict):
            return Scraper._names(value.get('name'))
        out = []
        for entry in value:
            out.extend(Scraper._names(entry))
        return out

    @staticmethod
    def _image_urls(value, base_url):
        if not value:
            return []
        if isinstance(value, str):
            return [urljoin(base_url, value)]
        if isinstance(value, dict):
            return Scraper._image_urls(value.get('url') or value.get('contentUrl'), base_url)
        out = []
        for entry in value:
            out.extend(Scraper._image_urls(entry, base_url))
        return out

    @staticmethod
    def _iso_duration(value):
        match = re.match(r'^P(?:T)?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$', str(value or '').replace('PT', 'P'))
        if not match or not any(match.groups()):
            return None
        h, m, sec = (int(x or 0) for x in match.groups())
        return h * 3600 + m * 60 + sec

    def parse_meta(self, html, url=BASE):
        """Collect plot, art, genres, people, rating... from a movie/series detail page."""
        soup = BeautifulSoup(html, 'html.parser')
        meta = {'plot': '', 'poster': '', 'fanart': '', 'genres': [], 'directors': [],
                'cast': [], 'rating': None, 'votes': None, 'duration': None,
                'year': None, 'originaltitle': '', 'mpaa': '',
                'writers': [], 'countries': [], 'studios': [], 'premiered': ''}
        images = []
        for tag in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(tag.string or tag.get_text() or '')
            except ValueError:
                continue
            for node in self._ld_nodes(data):
                kinds = node.get('@type')
                kinds = [kinds] if isinstance(kinds, str) else (kinds or [])
                if not any(k in ('Movie', 'TVSeries', 'TVSeason', 'TVEpisode') for k in kinds):
                    continue
                meta['plot'] = meta['plot'] or str(node.get('description') or '').strip()
                meta['originaltitle'] = meta['originaltitle'] or (self._names(node.get('alternateName')) or [''])[0]
                meta['genres'] = meta['genres'] or self._names(node.get('genre'))
                meta['directors'] = meta['directors'] or self._names(node.get('director'))
                meta['cast'] = meta['cast'] or self._names(node.get('actor'))
                meta['mpaa'] = meta['mpaa'] or (self._names(node.get('contentRating')) or [''])[0]
                images.extend(self._image_urls(node.get('image'), url))
                if meta['duration'] is None:
                    meta['duration'] = self._iso_duration(node.get('duration'))
                meta['premiered'] = meta['premiered'] or parse_date(str(node.get('datePublished') or ''))
                year = re.search(r'(19|20)\d{2}', str(node.get('datePublished') or node.get('dateCreated') or ''))
                if year and not meta['year']:
                    meta['year'] = int(year.group(0))
                rating = node.get('aggregateRating')
                if isinstance(rating, dict) and meta['rating'] is None:
                    try:
                        best = float(rating.get('bestRating') or 10)
                        meta['rating'] = round(float(rating.get('ratingValue')) / best * 10, 1)
                        meta['votes'] = int(rating.get('ratingCount') or rating.get('reviewCount') or 0) or None
                    except (TypeError, ValueError):
                        pass
        og_image = self._meta(soup, 'og:image')
        if og_image:
            images.append(urljoin(url, og_image))
        for cand in images:
            if cand not in (meta['poster'], meta['fanart']):
                if not meta['poster']:
                    meta['poster'] = cand
                elif not meta['fanart']:
                    meta['fanart'] = cand
        meta['fanart'] = meta['fanart'] or meta['poster']
        if not meta['plot']:
            el = soup.find(attrs={'itemprop': 'description'})
            meta['plot'] = (el.get('content') or el.get_text(' ', strip=True)) if el else ''
        meta['plot'] = ' '.join((meta['plot'] or self._meta(soup, 'og:description', 'description')).split())
        if not meta['genres']:
            meta['genres'] = [g.get_text(strip=True) for g in soup.find_all(attrs={'itemprop': 'genre'})]
        if not meta['year']:
            meta['year'] = self._year_from(soup)
        self._apply_pairs(meta, self._pairs(soup))
        meta['providers'] = self._providers_from(soup)
        meta['is_series'] = self._series_signal(soup)
        return meta

    @staticmethod
    def _series_signal(soup):
        """True/False when the detail page states the type itself, None when it does not."""
        og_type = (Scraper._meta(soup, 'og:type') or '').lower()
        if 'tv_show' in og_type or 'tv_episode' in og_type:
            return True
        if og_type == 'video.movie':
            return False
        for tag in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(tag.string or tag.get_text() or '')
            except ValueError:
                continue
            for node in Scraper._ld_nodes(data):
                kinds = node.get('@type')
                kinds = [kinds] if isinstance(kinds, str) else (kinds or [])
                if any(k in ('TVSeries', 'TVSeason', 'TVEpisode') for k in kinds):
                    return True
        return None

    @staticmethod
    def _providers_from(soup):
        """Providers a film page links to itself, ignoring site navigation.
        If nearly every provider shows up it is the site menu, not this film."""
        found = []
        for a in soup.find_all('a', href=True):
            path = urlparse(a['href']).path.rstrip('/')
            slug = path.rsplit('/', 1)[-1].lower()
            if slug not in PROVIDER_BY_SLUG or '/vod/' not in path + '/':
                continue
            if any(NAV_CLASS_RE.search(' '.join(p.get('class') or []) + ' ' + (p.get('id') or ''))
                   or p.name in ('nav', 'header', 'footer') or p.has_attr('data-submenu')
                   for p in a.parents if getattr(p, 'name', None)):
                continue
            if slug not in found:
                found.append(slug)
        return found if len(found) < 5 else []

    # ----------------------------------------------------- series index --
    def series_index(self):
        path = os.path.join(self.cache_dir, 'series.json') if self.cache_dir else None
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            return set(data) if isinstance(data, list) else set()
        except (OSError, ValueError, TypeError):
            return set()

    def series_index_add(self, urls):
        if not self.cache_dir:
            return
        known = self.series_index()
        if set(urls) <= known:
            return
        try:
            with open(os.path.join(self.cache_dir, 'series.json'), 'w', encoding='utf-8') as fh:
                json.dump(sorted(known | set(urls)), fh)
        except OSError:
            pass

    # --------------------------------------------------- provider index --
    def _index_path(self):
        return os.path.join(self.cache_dir, 'providers.json') if self.cache_dir else None

    def provider_index(self):
        path = self._index_path()
        try:
            with open(path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def provider_index_add(self, slug, urls):
        """Remember which film pages were listed under a provider (grows as you browse)."""
        path = self._index_path()
        if not path or slug not in PROVIDER_BY_SLUG:
            return
        data = self.provider_index()
        for url in urls:
            slugs = data.setdefault(url, [])
            if slug not in slugs:
                slugs.append(slug)
        try:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            pass

    @staticmethod
    def _pairs(soup):
        """Label/value facts from definition lists, tables and 'Label: value' lines."""
        found = []
        for dt in soup.find_all('dt'):
            dd = dt.find_next_sibling('dd')
            if dd is not None:
                found.append((dt.get_text(' ', strip=True), dd.get_text(', ', strip=True)))
        for row in soup.find_all('tr'):
            cells = row.find_all(['th', 'td'])
            if len(cells) == 2:
                found.append((cells[0].get_text(' ', strip=True), cells[1].get_text(', ', strip=True)))
        for el in soup.find_all(['strong', 'b', 'span', 'label']):
            label = el.get_text(' ', strip=True)
            if not label.endswith(':') or len(label) > 40:
                continue
            tail = []
            for sib in el.next_siblings:
                if getattr(sib, 'name', None) in ('br', 'strong', 'b', 'label'):
                    break
                tail.append(sib.get_text(', ', strip=True) if hasattr(sib, 'get_text') else str(sib).strip())
            value = ', '.join(x for x in tail if x)
            if value:
                found.append((label, value))
        return found

    @staticmethod
    def _apply_pairs(meta, pairs):
        for label, value in pairs:
            key = PAIR_LABELS.get(label.strip().rstrip(':').strip().lower())
            value = ' '.join((value or '').split())
            if not key or not value or len(value) > 400:
                continue
            if key in LIST_FIELDS:
                values = [v.strip() for v in re.split(r'\s*[,;|]\s*', value) if v.strip()]
                meta.setdefault(key, [])
                if not meta[key]:
                    meta[key] = values
            elif key == 'runtime':
                num = re.search(r'\d+', value)
                if num and meta.get('duration') is None and 10 <= int(num.group(0)) <= 600:
                    meta['duration'] = int(num.group(0)) * 60
            elif key == 'premiered':
                full = parse_date(value)
                if full and not meta.get('premiered'):
                    meta['premiered'] = full
                year = re.search(r'(?:19|20)\d{2}', value)
                if year and not meta.get('year'):
                    meta['year'] = int(year.group(0))
            elif key == 'year':
                year = re.search(r'(?:19|20)\d{2}', value)
                if year and not meta.get('year'):
                    meta['year'] = int(year.group(0))
            elif not meta.get(key):
                meta[key] = value

    @staticmethod
    def _year_from(soup):
        year_rx = re.compile(r'(?<!\d)((?:19\d{2}|20[0-2]\d|2030))(?!\d)')
        for name in ('datePublished', 'dateCreated', 'releaseDate', 'copyrightYear'):
            el = soup.find(attrs={'itemprop': name})
            if el is not None:
                found = year_rx.search(el.get('content') or el.get_text(' ', strip=True))
                if found:
                    return int(found.group(1))
        tag = soup.find('meta', attrs={'property': 'video:release_date'})
        if tag and year_rx.search(tag.get('content', '')):
            return int(year_rx.search(tag['content']).group(1))
        for el in soup.find_all(class_=re.compile(r'(^|\s)year(\s|$)')):
            found = year_rx.search(el.get_text(' ', strip=True))
            if found:
                return int(found.group(1))
        titles = [Scraper._meta(soup, 'og:title'), soup.title.get_text(' ', strip=True) if soup.title else '']
        titles += [h.get_text(' ', strip=True) for h in soup.find_all('h1')]
        for text in titles:
            found = re.search(r'\(((?:19\d{2}|20[0-2]\d|2030))\)', text or '')
            if found:
                return int(found.group(1))
        return None

    def get_meta(self, url):
        """Parsed metadata with a long-lived JSON cache; {} on failure."""
        path = None
        if self.cache_dir:
            path = os.path.join(self.cache_dir, 'meta7_%s.json' % hashlib.md5(url.encode('utf-8')).hexdigest())
            try:
                if time.time() - os.path.getmtime(path) < 7 * 86400:
                    with open(path, 'r', encoding='utf-8') as fh:
                        return json.load(fh)
            except (OSError, ValueError):
                pass
        try:
            meta = self.parse_meta(self.get_html(url), url)
        except ScrapeError as exc:
            self.log('meta failed for %s: %s' % (url, exc))
            return {}
        if path:
            try:
                with open(path, 'w', encoding='utf-8') as fh:
                    json.dump(meta, fh, ensure_ascii=False)
            except OSError:
                pass
        return meta


    # ------------------------------------------------------------ people --
    def people_url(self, page=1, genre=''):
        return '%s%d/?yrf=&yrt=&genre=%s&cat=undefined' % (PEOPLE_BASE, max(1, int(page)), genre or '')

    def parse_people(self, soup, base_url):
        """Person cards: name, photo, birth info, bio snippet and the films listed on the card."""
        cards = soup.select('#listoftiles .item[itemprop=itemListElement]')
        if not cards:
            cards = [c for c in soup.select('.item') if c.find('a', href=PERSON_RE)]
        out, seen = [], set()
        for card in cards:
            link = card.find('a', href=PERSON_RE)
            if link is None:
                continue
            href = urljoin(base_url, link['href'].split('#')[0])
            if href in seen:
                continue
            seen.add(href)
            h4 = card.find('h4')
            name = ' '.join(((h4.get_text(' ', strip=True) if h4 else '') or link.get('title') or '').split())
            if not name:
                continue
            img = card.find('img')
            thumb = ''
            if img is not None:
                src = img.get('data-src') or img.get('data-original') or ''
                thumb = urljoin(base_url, src) if src else ''
            year_el = card.select_one('p .year') or card.select_one('.year')
            info = ' '.join(year_el.get_text(' ', strip=True).split()) if year_el else ''
            birth = BIRTH_RE.search(info)
            place = info.split('/', 1)[1].strip() if '/' in info else ''
            desc = card.select_one('p.desc')
            bio = ''
            if desc is not None:
                for more in desc.find_all('a'):
                    more.decompose()
                bio = ' '.join(desc.get_text(' ', strip=True).split())
            films, fseen = [], set()
            for a in card.select('p.actors a[href]'):
                furl = urljoin(base_url, a['href'].split('#')[0])
                if ITEM_RE.search(urlparse(furl).path) and furl not in fseen:
                    fseen.add(furl)
                    films.append({'url': furl, 'title': ' '.join(a.get_text(' ', strip=True).split())})
            out.append({
                'url': href, 'name': name, 'thumb': thumb, 'info': info, 'place': place, 'bio': bio,
                'birth': '%s-%02d-%02d' % (birth.group(1), int(birth.group(2)), int(birth.group(3))) if birth else '',
                'films': films,
            })
        return out

    def people_page(self, page=1, genre='', url=None):
        """One page of the people list. Returns (people, has_next)."""
        url = url or self.people_url(page, genre)
        people = self.parse_people(self.get_soup(url), url)
        self.person_cache_add(people)
        return people, bool(people) and not url.startswith(BIRTHDAYS_PAGE)

    def _persons_path(self):
        return os.path.join(self.cache_dir, 'persons.json') if self.cache_dir else None

    def person_cache(self):
        try:
            with open(self._persons_path(), 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def person_cache_add(self, people):
        path = self._persons_path()
        if not path or not people:
            return
        data = self.person_cache()
        for p in people:
            data[p['url']] = p
        if len(data) > 3000:                      # keep the file small
            data = dict(list(data.items())[-2000:])
        try:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(data, fh, ensure_ascii=False)
        except OSError:
            pass

    def parse_person_page(self, html, url):
        """Best effort on a person's own page: bio, photo and the films linked in its main column."""
        soup = BeautifulSoup(html, 'html.parser')
        films, seen = [], set()
        for a in soup.find_all('a', href=True):
            href = urljoin(url, a['href'].split('#')[0])
            path = urlparse(href).path
            if not path.startswith('/movies/') or not ITEM_RE.search(path) or href in seen:
                continue
            if any(SIDEBAR_RE.search(' '.join(p.get('class') or []) + ' ' + (p.get('id') or ''))
                   or p.name in ('nav', 'header', 'footer') for p in a.parents if getattr(p, 'name', None)):
                continue
            title = (a.get('title') or a.get_text(' ', strip=True) or '').strip()
            if not title:
                continue
            seen.add(href)
            clean, year = split_year(' '.join(title.split()))
            films.append({'url': href, 'title': clean, 'year': year})
        return {'name': self._meta(soup, 'og:title') or '', 'photo': self._meta(soup, 'og:image'),
                'bio': self._meta(soup, 'og:description', 'description'), 'films': films}

    def person_films(self, url):
        """Films for a person: the ones on the list card first, then whatever the person page adds."""
        cached = self.person_cache().get(url) or {}
        films = [dict(f) for f in cached.get('films') or []]
        seen = {f['url'] for f in films}
        try:
            page = self.parse_person_page(self.get_html(url), url)
        except ScrapeError:
            page = {'films': []}
        for f in page['films']:
            if f['url'] not in seen:
                seen.add(f['url'])
                films.append(f)
        return films, cached
