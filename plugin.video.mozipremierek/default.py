# -*- coding: utf-8 -*-
"""Mozipremierek.hu catalog and trailer browser for Kodi 21+."""
from __future__ import absolute_import

import concurrent.futures
import datetime
from difflib import SequenceMatcher
import hashlib
import html
import json
import os
import re
import sys
import time
import uuid
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, quote_plus, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib.adapters import ADAPTERS
from resources.lib.aggregator import group_movies, normalize_title

try:
    import resolveurl
except ImportError:
    resolveurl = None

try:
    import zidervisionurlresolver
except ImportError:
    zidervisionurlresolver = None


ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
BASE = 'https://mozipremierek.hu'
HANDLE = int(sys.argv[1])
PLUGIN_BASE = sys.argv[0]
HOST_CACHE_SCHEMA = 2


class SiteParser(HTMLParser):
    """Extract catalog cards, genres, synopsis and YouTube trailer references."""
    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.movies = []
        self.trailers = []
        self.links = []
        self.genres = []
        self.anchor = None
        self.option = None
        self.active_youtube_id = None
        self._anchor_title_depth = 0
        self._anchor_subtitle_depth = 0
        self.page_title = []
        self.in_h1 = False
        self.description = ''
        self.plot_parts = []
        self.in_plot = False
        self.plot_div_depth = 0
        self.in_plot_paragraph = False
        self.fanart = ''
        self.in_movie_meta = False
        self.movie_meta_depth = 0
        self.movie_meta_parts = []
        self.meta_summary = ''
        self.age_limit = ''
        self.runtime_minutes = 0
        self.country = ''
        self.in_movie_cast = False
        self.movie_cast_depth = 0
        self.movie_cast_parts = []
        self.original_title = ''
        self.year = 0
        self.directors = []
        self.cast = []
        self.cast_role = ''
        self.capture_cast_label = False
        self.cast_label_parts = []
        self.capture_cast_person = False
        self.cast_person_parts = []
        self.distributor = ''
        self.release_date = ''
        self.studios = []
        self.in_press_notice = False
        self.press_notice_parts = []
        self.imdb_id = ''
        self._anchor_distributor_depth = 0

    @property
    def plot(self):
        return ' '.join(' '.join(self.plot_parts).split())

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get('class', '').split()
        if tag == 'meta' and attrs.get('name', '').lower() == 'description':
            self.description = html.unescape(attrs.get('content', '')).strip()
        if tag == 'li' and attrs.get('data-youtube-id'):
            self.active_youtube_id = attrs.get('data-youtube-id')
        if tag == 'option' and attrs.get('value', '').startswith(('/filmek/', '/streaming/')):
            self.option = {'href': attrs.get('value', ''), 'text': []}
        if tag == 'div':
            if 'movie-plot' in classes:
                self.in_plot = True
                self.plot_div_depth = 0
            elif self.in_plot:
                self.plot_div_depth += 1
            if 'movie-meta' in classes:
                self.in_movie_meta = True
                self.movie_meta_depth = 1
                self.movie_meta_parts = []
            elif self.in_movie_meta:
                self.movie_meta_depth += 1
            if 'movie-v2-cast' in classes:
                self.in_movie_cast = True
                self.movie_cast_depth = 1
                self.movie_cast_parts = []
            elif self.in_movie_cast:
                self.movie_cast_depth += 1
        if tag == 'small' and 'movie-press-notice' in classes:
            self.in_press_notice = True
            self.press_notice_parts = []
        if tag == 'strong' and self.in_movie_cast:
            self.capture_cast_label = True
            self.cast_label_parts = []
        if tag == 'li' and self.in_movie_cast:
            self.capture_cast_person = True
            self.cast_person_parts = []
        if tag == 'p' and self.in_plot:
            self.in_plot_paragraph = True
        if tag == 'h1' and 'movie-title' in classes:
            self.in_h1 = True
        if tag == 'a':
            self.anchor = {
                'href': attrs.get('href', ''),
                'class': classes,
                'text': [],
                'title': [],
                'subtitle': [],
                'image': '',
                'youtube_id': self.active_youtube_id or '',
                'distributor': []
            }
            self._anchor_title_depth = 0
            self._anchor_distributor_depth = 0
        elif self.anchor is not None and tag == 'img':
            src = attrs.get('src', '')
            srcset = attrs.get('srcset', '')
            if not src and srcset:
                src = srcset.split(',')[0].strip().split(' ')[0]
            if src and not self.anchor['image']:
                self.anchor['image'] = src
            if 'Jelenetkép' in attrs.get('alt', '') and not self.fanart:
                self.fanart = self.anchor.get('href') or src
        elif self.anchor is not None and tag == 'span' and 'distributor' in classes:
            self._anchor_distributor_depth = 1
        if self.anchor is not None and tag in ('strong', 'span') and any(c in classes for c in ('item-title', 'movie-title')):
            self._anchor_title_depth += 1
        if self.anchor is not None and tag == 'span' and 'item-subtitle' in classes:
            self._anchor_subtitle_depth = 1

    def handle_endtag(self, tag):
        if tag == 'strong' and self.capture_cast_label:
            label = ' '.join(' '.join(self.cast_label_parts).split()).casefold()
            if 'rendező' in label:
                self.cast_role = 'directors'
            elif 'főszereplők' in label:
                self.cast_role = 'cast'
            self.capture_cast_label = False
        if tag == 'li' and self.capture_cast_person:
            person = ' '.join(' '.join(self.cast_person_parts).split())
            if person and self.cast_role == 'directors' and person not in self.directors:
                self.directors.append(person)
            elif person and self.cast_role == 'cast' and person not in self.cast:
                self.cast.append(person)
            self.capture_cast_person = False
        if tag == 'small' and self.in_press_notice:
            self.in_press_notice = False
            notice = ' '.join(' '.join(self.press_notice_parts).split())
            match = re.search(r'gyártó\(k\):\s*([^;.]*)', notice, re.I)
            if match:
                self.studios = [part.strip() for part in re.split(r',|\s+és\s+', match.group(1)) if part.strip()]
        if tag == 'div' and self.in_movie_meta:
            self.movie_meta_depth -= 1
            if self.movie_meta_depth <= 0:
                self.in_movie_meta = False
                meta = ' '.join(' '.join(self.movie_meta_parts).split())
                age_match = re.search(r'\(([^)]+)\)', meta)
                runtime_match = re.search(r'(\d{1,4})\s*perc', meta, re.I)
                self.age_limit = age_match.group(1).strip() if age_match else ''
                self.runtime_minutes = int(runtime_match.group(1)) if runtime_match else 0
                self.meta_summary = re.sub(r'\([^)]*\)|\d{1,4}\s*perc', ' ', meta, flags=re.I)
                self.meta_summary = ' '.join(self.meta_summary.split()).strip(' -|')
        if tag == 'div' and self.in_movie_cast:
            self.movie_cast_depth -= 1
            if self.movie_cast_depth <= 0:
                self.in_movie_cast = False
                details = ' '.join(' '.join(self.movie_cast_parts).split())
                original = re.search(r'Eredeti cím:\s*(.*?)\s+Gyártás éve:', details, re.I)
                year = re.search(r'Gyártás éve:\s*(\d{4})', details, re.I)
                self.original_title = original.group(1).strip() if original else ''
                self.year = int(year.group(1)) if year else 0
        if tag in ('strong', 'span') and self.anchor is not None and self._anchor_title_depth:
            self._anchor_title_depth -= 1
        if tag == 'span' and self.anchor is not None and self._anchor_subtitle_depth:
            self._anchor_subtitle_depth = 0
        if tag == 'span' and self.anchor is not None and self._anchor_distributor_depth:
            self._anchor_distributor_depth = 0
        if tag == 'p' and self.in_plot_paragraph:
            self.in_plot_paragraph = False
        if tag == 'h1' and self.in_h1:
            self.in_h1 = False
        if tag == 'option' and self.option is not None:
            self.option['text'] = ' '.join(' '.join(self.option['text']).split())
            self.links.append(self.option)
            self.option = None
        if tag == 'div' and self.in_plot:
            if self.plot_div_depth:
                self.plot_div_depth -= 1
            else:
                self.in_plot = False
        if tag == 'a' and self.anchor is not None:
            entry = self.anchor
            entry['text'] = ' '.join(' '.join(entry['text']).split())
            entry['title'] = ' '.join(' '.join(entry['title']).split())
            entry['subtitle'] = ' '.join(' '.join(entry['subtitle']).split())
            entry['distributor'] = ' '.join(' '.join(entry['distributor']).split())
            entry['href'] = html.unescape(entry['href'])
            if 'premier-date' in entry['class']:
                self.distributor = entry['distributor']
                self.release_date = entry['text'].replace(self.distributor, '').strip() if self.distributor else entry['text']
            imdb_match = re.search(r'imdb\.com/title/(tt\d+)', entry['href'], re.I)
            if imdb_match:
                self.imdb_id = imdb_match.group(1)
            if 'movie' in entry['class'] and entry['href'].startswith('/movie/'):
                entry['title'] = entry['title'] or entry['text'] or 'Film'
                self.movies.append(entry)
            if 'movie-category' in entry['class'] and entry['href'].startswith(('/filmek/', '/streaming/')):
                self.genres.append({'label': entry['text'], 'href': entry['href']})
            if '/trailer/' in entry['href'] or entry['youtube_id']:
                if entry['youtube_id']:
                    entry['title'] = entry['title'] or entry['text'] or 'Előzetes'
                    self.trailers.append(entry)
            if entry['href']:
                self.links.append(entry)
            self.anchor = None
            self._anchor_title_depth = 0
            self._anchor_subtitle_depth = 0
        if tag == 'li' and self.active_youtube_id:
            self.active_youtube_id = None

    def handle_data(self, data):
        if self.in_movie_meta:
            self.movie_meta_parts.append(data)
        if self.in_movie_cast:
            self.movie_cast_parts.append(data)
        if self.capture_cast_label:
            self.cast_label_parts.append(data)
        if self.capture_cast_person:
            self.cast_person_parts.append(data)
        if self.in_press_notice:
            self.press_notice_parts.append(data)
        if self.anchor is not None:
            self.anchor['text'].append(data)
            if self._anchor_distributor_depth:
                self.anchor['distributor'].append(data)
            if self._anchor_title_depth:
                self.anchor['title'].append(data)
            if getattr(self, '_anchor_subtitle_depth', 0):
                self.anchor['subtitle'].append(data)
        if self.option is not None:
            self.option['text'].append(data)
        if self.in_h1:
            self.page_title.append(data)
        if self.in_plot_paragraph:
            self.plot_parts.append(data)


def fetch_page(path):
    url = urljoin(BASE + '/', path.lstrip('/'))
    # Kodi's Python HTTP client needs percent-encoded non-ASCII genre slugs.
    url = quote(url, safe=":/?&=%#[]@!$'()*+,;")
    request = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Kodi; plugin.video.mozipremierek/1.2.0) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml'
    })
    try:
        with urlopen(request, timeout=20) as response:
            status = response.getcode()
            body = response.read()
        text = body.decode('utf-8', 'replace')
        if status in (403, 429, 503) or 'cf-chl-' in text or 'Just a moment...' in text:
            raise RuntimeError('A weboldal Cloudflare-ellenőrzést vagy forgalomkorlátozást adott vissza.')
        return text
    except HTTPError as exc:
        if exc.code in (403, 429, 503):
            raise RuntimeError('A weboldal jelenleg blokkolja a kiegészítő kérését (HTTP %s / Cloudflare).' % exc.code)
        raise RuntimeError('A weboldal hibát adott vissza (HTTP %s).' % exc.code)
    except URLError as exc:
        raise RuntimeError('Nem sikerült csatlakozni a Mozipremierek.hu oldalhoz: %s' % exc.reason)
    except TimeoutError:
        raise RuntimeError('Időtúllépés a Mozipremierek.hu elérésekor.')


def parse_page(path):
    parser = SiteParser()
    parser.feed(fetch_page(path))
    parser.page_title = ' '.join(' '.join(parser.page_title).split())
    return parser


def plugin_url(action, **params):
    query = {'action': action}
    query.update(params)
    return PLUGIN_BASE + '?' + urlencode(query)


def metadata_cache_path():
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    if not profile:
        return ''
    xbmcvfs.mkdirs(profile)
    return os.path.join(profile, 'movie_metadata.json')


def read_metadata_cache():
    path = metadata_cache_path()
    try:
        with open(path, 'r', encoding='utf-8') as source:
            return json.load(source)
    except Exception:
        return {}


def write_metadata_cache(cache):
    path = metadata_cache_path()
    if not path:
        return
    temporary = path + '.tmp'
    try:
        with open(temporary, 'w', encoding='utf-8') as target:
            json.dump(cache, target, ensure_ascii=False)
        os.replace(temporary, path)
    except Exception as exc:
        xbmc.log('%s cache write failed: %s' % (ADDON_ID, exc), xbmc.LOGWARNING)


def fetch_movie_metadata(path):
    parser = parse_page(path)
    parts = parser.description.split(' - ', 4)
    summary = parts[4].strip() if len(parts) > 4 else parser.description
    genres = list(dict.fromkeys(g['label'].strip() for g in parser.genres if g.get('label')))
    country = parser.meta_summary
    for genre in sorted(genres, key=len, reverse=True):
        country = re.sub(r'(?i)(?<!\w)' + re.escape(genre) + r'(?!\w)', ' ', country)
    country = ' '.join(country.split()).strip(' ,-|')
    premiered = ''
    date_match = re.search(r'(\d{4})\.\s*([\wáéíóöőúüű]+)\s+(\d{1,2})\.', parser.release_date, re.I)
    months = {
        'január': 1, 'február': 2, 'március': 3, 'április': 4, 'május': 5, 'június': 6,
        'július': 7, 'augusztus': 8, 'szeptember': 9, 'október': 10, 'november': 11, 'december': 12
    }
    if date_match and date_match.group(2).casefold() in months:
        try:
            premiered = '%04d-%02d-%02d' % (
                int(date_match.group(1)), months[date_match.group(2).casefold()], int(date_match.group(3))
            )
        except ValueError:
            pass
    return {
        'schema': 2,
        'plot': parser.plot or summary,
        'summary': summary,
        'genres': genres,
        'original_title': parser.original_title,
        'year': parser.year,
        'directors': parser.directors,
        'cast': parser.cast,
        'country': country,
        'age_limit': parser.age_limit,
        'runtime_minutes': parser.runtime_minutes,
        'distributor': parser.distributor,
        'studios': parser.studios,
        'imdb_id': parser.imdb_id,
        'premiered': premiered,
        'fanart': parser.fanart,
        'fetched_at': int(time.time())
    }


def enrich_movies(entries):
    cache = read_metadata_cache()
    now = int(time.time())
    missing = []
    for entry in entries:
        path = entry.get('href', '')
        info = cache.get(path, {})
        if not info or info.get('schema') != 2 or now - int(info.get('fetched_at', 0)) > 30 * 24 * 60 * 60:
            if path and path not in missing:
                missing.append(path)
    if missing:
        # A small worker pool keeps the first Fanart view useful without flooding the site.
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {executor.submit(fetch_movie_metadata, path): path for path in missing}
            for future, path in ((future, futures[future]) for future in futures):
                try:
                    cache[path] = future.result()
                except Exception as exc:
                    xbmc.log('%s metadata unavailable for %s: %s' % (ADDON_ID, path, exc), xbmc.LOGWARNING)
        write_metadata_cache(cache)
    return {entry.get('href', ''): cache.get(entry.get('href', ''), {}) for entry in entries}


def add_folder(label, action, **params):
    item = xbmcgui.ListItem(label=label)
    item.setProperty('IsPlayable', 'false')
    xbmcplugin.addDirectoryItem(HANDLE, plugin_url(action, **params), item, True)


def set_video_info(item, info):
    """Set Kodi video metadata through InfoTagVideo, with a legacy fallback."""
    try:
        tag = item.getVideoInfoTag()
        if not tag:
            raise AttributeError('Kodi InfoTagVideo unavailable')
        setters = {
            'title': 'setTitle', 'originaltitle': 'setOriginalTitle', 'mediatype': 'setMediaType',
            'plot': 'setPlot', 'year': 'setYear', 'duration': 'setDuration', 'mpaa': 'setMpaa',
            'imdbnumber': 'setIMDBNumber', 'premiered': 'setPremiered'
        }
        for key, setter_name in setters.items():
            if key in info and hasattr(tag, setter_name):
                getattr(tag, setter_name)(info[key])
        list_setters = {
            'genre': 'setGenres', 'director': 'setDirectors', 'cast': 'setCast',
            'country': 'setCountries', 'studio': 'setStudios'
        }
        for key, setter_name in list_setters.items():
            if key in info and hasattr(tag, setter_name):
                value = info[key]
                if not isinstance(value, list):
                    value = [x.strip() for x in str(value).split(',') if x.strip()]
                getattr(tag, setter_name)(value)
    except (AttributeError, TypeError):
        item.setInfo('video', info)


def add_movie(entry, metadata=None):
    metadata = metadata or {}
    title = entry.get('title') or entry.get('text') or 'Film'
    path = entry.get('href', '')
    subtitle = entry.get('subtitle', '')
    genres = metadata.get('genres', [])
    plot = metadata.get('plot') or subtitle or entry.get('text', '')
    info = {'title': title, 'mediatype': 'movie', 'plot': plot}
    if genres:
        info['genre'] = genres
    if metadata.get('original_title'):
        info['originaltitle'] = metadata['original_title']
    if metadata.get('directors'):
        info['director'] = metadata['directors']
    if metadata.get('cast'):
        info['cast'] = metadata['cast']
    if metadata.get('country'):
        info['country'] = [metadata['country']]
    if metadata.get('studios'):
        info['studio'] = metadata['studios']
    if metadata.get('imdb_id'):
        info['imdbnumber'] = metadata['imdb_id']
    if metadata.get('premiered'):
        info['premiered'] = metadata['premiered']
    if metadata.get('age_limit'):
        info['mpaa'] = metadata['age_limit']
    if metadata.get('runtime_minutes'):
        info['duration'] = int(metadata['runtime_minutes']) * 60
    year_match = re.search(r'\b(?:19|20)\d{2}\b', metadata.get('summary', '') or subtitle)
    year_value = metadata.get('year') or (int(year_match.group(0)) if year_match else 0)
    if year_value:
        info['year'] = int(year_value)

    # Put the most useful site-only facts into the plot as well, so skins that
    # do not show every InfoTagVideo field still expose them in the Fanart view.
    facts = []
    if metadata.get('original_title') and metadata['original_title'].casefold() != title.casefold():
        facts.append('Eredeti cím: ' + metadata['original_title'])
    if year_value:
        facts.append('Gyártás éve: %s' % year_value)
    if metadata.get('age_limit'):
        facts.append('Korhatár: ' + metadata['age_limit'])
    if metadata.get('runtime_minutes'):
        facts.append('Játékidő: %s perc' % metadata['runtime_minutes'])
    if metadata.get('directors'):
        facts.append('Rendező: ' + ', '.join(metadata['directors']))
    if metadata.get('cast'):
        facts.append('Főszereplők: ' + ', '.join(metadata['cast'][:8]))
    if metadata.get('distributor'):
        facts.append('Forgalmazó: ' + metadata['distributor'])
    if metadata.get('premiered'):
        facts.append('Premier: ' + metadata['premiered'])
    if facts:
        info['plot'] = (plot + '\n\n' if plot else '') + '  •  '.join(facts)
    item = xbmcgui.ListItem(
        label='[COLOR FFD9B15F]%s[/COLOR]' % title,
        label2='[COLOR FF7DC8D2]%s[/COLOR]' % subtitle if subtitle else ''
    )
    set_video_info(item, info)
    poster = entry.get('image')
    art = {}
    if poster:
        poster = urljoin(BASE, poster)
        art.update({'thumb': poster, 'poster': poster, 'icon': poster})
    fanart = metadata.get('fanart')
    if fanart:
        fanart = urljoin(BASE, fanart)
        art['fanart'] = fanart
        item.setProperty('Fanart_Image', fanart)
    if art:
        item.setArt(art)
    item.setProperty('IsPlayable', 'false')
    context = [
        ('Keresés az stb.hu-n', 'RunPlugin(%s)' % plugin_url('search_stb', title=title))
    ]
    item.addContextMenuItems(context)
    xbmcplugin.addDirectoryItem(HANDLE, plugin_url('movie', path=path), item, True)


def add_trailer(entry):
    title = entry.get('title') or entry.get('text') or 'Előzetes'
    video_id = entry.get('youtube_id')
    if not video_id:
        return
    label = '[COLOR FFD9B15F]>> [/COLOR]  [COLOR FF7DC8D2]%s[/COLOR]' % title
    item = xbmcgui.ListItem(label=label)
    set_video_info(item, {'title': title, 'mediatype': 'video'})
    thumb = 'https://i.ytimg.com/vi/%s/hqdefault.jpg' % video_id
    item.setArt({'thumb': thumb, 'icon': thumb})
    item.setProperty('IsPlayable', 'true')
    xbmcplugin.addDirectoryItem(HANDLE, plugin_url('play', video_id=video_id), item, False)


def finish(content='videos'):
    xbmcplugin.setContent(HANDLE, content)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=True)


def show_root():
    year = datetime.date.today().year
    add_folder('Mozis premierfilmek (%d)' % year, 'list', path='/filmek/%d/' % year)
    add_folder('Mozis műfajok (%d)' % year, 'genres', mode='filmek', year=year)
    add_folder('Online nézhető filmek (%d)' % year, 'list', path='/streaming/%d/' % year)
    add_folder('Streaming műfajok (%d)' % year, 'genres', mode='streaming', year=year)
    add_folder('Streaming szolgáltatók', 'providers', year=year)
    add_folder('Friss előzetesek', 'latest')
    add_folder('Premier- és streamingévek', 'years')
    finish('files')


def show_years():
    year = datetime.date.today().year
    for y in range(year, year - 12, -1):
        add_folder('Mozis premierek – %d' % y, 'list', path='/filmek/%d/' % y)
        add_folder('Mozis műfajok – %d' % y, 'genres', mode='filmek', year=y)
        add_folder('Online nézhető – %d' % y, 'list', path='/streaming/%d/' % y)
        add_folder('Streaming műfajok – %d' % y, 'genres', mode='streaming', year=y)
    finish('files')


def show_genres(mode, year):
    if mode not in ('filmek', 'streaming') or not re.match(r'^20\d{2}$', year):
        raise RuntimeError('Érvénytelen műfajszűrő.')
    parser = parse_page('/')
    prefix = '/%s/%s/' % (mode, year)
    found = {}
    for entry in parser.links:
        if 'mega-menu-promo-card' in entry.get('class', []):
            continue
        href = entry.get('href', '')
        match = re.match(r'^' + re.escape(prefix) + r'([^/?#]+)/?$', href)
        if not match:
            continue
        slug = match.group(1)
        label = re.sub(r'\s*\(%s\)\s*$' % re.escape(year), '', entry.get('text', '')).strip()
        if not label:
            label = slug.replace('-', ' ').title()
        found[slug] = label
    if not found:
        raise RuntimeError('Nem sikerült műfajokat találni a weboldal menüjében.')
    for slug, label in sorted(found.items(), key=lambda pair: pair[1].casefold()):
        add_folder(label, 'list', path=prefix + slug)
    finish('files')


def show_providers(year):
    providers = [
        ('Netflix', 'netflix'), ('HBO Max', 'max'), ('Disney+', 'disneyplus'),
        ('SkyShowtime', 'skyshowtime'), ('Apple TV', 'apple-all'), ('Prime Video', 'amazon-all')
    ]
    for label, code in providers:
        add_folder(label, 'list', path='/streaming/%s/' % year, provider=code)
    finish('files')


def show_list(path, provider='', page=1):
    if not path.startswith(('/filmek/', '/streaming/')):
        raise RuntimeError('Érvénytelen katalógusútvonal.')
    if provider:
        path += ('&' if '?' in path else '?') + 'provider=' + provider
    parser = parse_page(path)
    seen = set()
    entries = []
    for entry in parser.movies:
        if entry['href'] in seen:
            continue
        seen.add(entry['href'])
        entries.append(entry)
    if not seen:
        add_folder('A katalógus most üres vagy megváltozott.', 'latest')
        finish('movies')
        return
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    page_size = 8
    pages = (len(entries) + page_size - 1) // page_size
    start = (page - 1) * page_size
    page_entries = entries[start:start + page_size]
    metadata = enrich_movies(page_entries)
    for entry in page_entries:
        add_movie(entry, metadata.get(entry.get('href', ''), {}))
    if page < pages:
        add_folder('Következő oldal /// (%d/%d)' % (page + 1, pages), 'list', path=path.split('?')[0], provider=provider, page=page + 1)
    finish('movies')


def show_latest():
    parser = parse_page('/')
    seen = set()
    for entry in parser.trailers:
        vid = entry.get('youtube_id')
        if vid and vid not in seen:
            seen.add(vid)
            add_trailer(entry)
    if not seen:
        add_folder('Nem találhatók előzetesek ezen az oldalon.', 'root')
    finish('videos')


def show_movie(path):
    if not path.startswith('/movie/'):
        raise RuntimeError('Érvénytelen film-adatlap.')
    parser = parse_page(path)
    title = parser.page_title or path.rstrip('/').split('/')[-1].replace('-', ' ').title()
    xbmcplugin.setPluginCategory(HANDLE, title)
    seen = set()
    for entry in parser.trailers:
        vid = entry.get('youtube_id')
        if vid and vid not in seen:
            seen.add(vid)
            add_trailer(entry)
    add_adapter_hosts(title, path)
    for entry in parser.movies:
        if entry.get('href') != path:
            add_movie(entry)
    finish('videos')


def quality_counts():
    return {'4K': 0, '1080p': 0, '720p': 0, 'HD': 0, 'SD': 0, 'DVD': 0, 'CAM': 0, 'Egyéb': 0, 'Összesen': 0}


def add_quality_counts(counts, sources):
    for source in sources:
        quality = str(source.get('quality', '')).upper()
        if '2160' in quality or '4K' in quality:
            category = '4K'
        elif '1080' in quality:
            category = '1080p'
        elif '720' in quality:
            category = '720p'
        elif 'DVD' in quality:
            category = 'DVD'
        elif 'CAM' in quality or 'TS' == quality.strip():
            category = 'CAM'
        elif '480' in quality or '360' in quality or 'SD' in quality:
            category = 'SD'
        elif 'HD' in quality:
            category = 'HD'
        else:
            category = 'Egyéb'
        counts[category] += 1
        counts['Összesen'] += 1


def update_source_progress(progress, percent, page_name, remaining, counts):
    line1 = '[COLOR FFD9B15F]4K:[/COLOR] [COLOR FF55C7C2]%d[/COLOR]  |  [COLOR FFD9B15F]1080p:[/COLOR] [COLOR FF55C7C2]%d[/COLOR]  |  [COLOR FFD9B15F]720p:[/COLOR] [COLOR FF55C7C2]%d[/COLOR]  |  [COLOR FFD9B15F]HD:[/COLOR] [COLOR FF55C7C2]%d[/COLOR]' % (
        counts['4K'], counts['1080p'], counts['720p'], counts['HD']
    )
    line2 = '[COLOR FFD9B15F]SD:[/COLOR] [COLOR FF55C7C2]%d[/COLOR]  |  [COLOR FFD9B15F]DVD:[/COLOR] [COLOR FF55C7C2]%d[/COLOR]  |  [COLOR FFD9B15F]CAM:[/COLOR] [COLOR FF55C7C2]%d[/COLOR]  |  [COLOR FFD9B15F]Egyéb:[/COLOR] [COLOR FF55C7C2]%d[/COLOR]  |  [COLOR FFD9B15F]Összesen:[/COLOR] [COLOR FFFF9E64]%d[/COLOR]' % (
        counts['SD'], counts['DVD'], counts['CAM'], counts['Egyéb'], counts['Összesen']
    )
    line3 = '[COLOR FFE6ECF2]Források eddig:[/COLOR] [COLOR FFFF9E64]%d[/COLOR]  |  [COLOR FF72D5C9]Oldal:[/COLOR] %s  |  [COLOR FF72D5C9]Hátralévő adapterek:[/COLOR] %d' % (
        counts['Összesen'], page_name, max(0, remaining)
    )
    # Kodi 21's Python DialogProgress.update accepts percent plus one message.
    progress.update(max(0, min(100, int(percent))), '\n'.join((line1, line2, line3)))


def save_source_queue(title, sources):
    token = uuid.uuid4().hex
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    xbmcvfs.mkdirs(profile)
    with open(os.path.join(profile, 'source_queue_%s.json' % token), 'w', encoding='utf-8') as target:
        json.dump({'title': title, 'sources': sources}, target, ensure_ascii=False)
    return token


def load_source_queue(token):
    if not re.match(r'^[a-f0-9]{32}$', token or ''):
        return None
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    path = os.path.join(profile, 'source_queue_%s.json' % token)
    try:
        with open(path, 'r', encoding='utf-8') as source:
            data = json.load(source)
        return data if isinstance(data.get('sources'), list) else None
    except (OSError, ValueError, TypeError):
        return None


def source_cache_path(title, movie_path):
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    xbmcvfs.mkdirs(profile)
    cache_key = hashlib.sha256((movie_path + '|' + normalize_title(title)).encode('utf-8')).hexdigest()
    return os.path.join(profile, 'host_cache_%s.json' % cache_key)


def load_host_cache(title, movie_path):
    try:
        with open(source_cache_path(title, movie_path), 'r', encoding='utf-8') as cache_file:
            cached = json.load(cache_file)
        if cached.get('schema') != HOST_CACHE_SCHEMA:
            return None
        sources = cached.get('sources')
        if not isinstance(sources, list):
            return None
        age = time.time() - float(cached.get('fetched_at', 0))
        ttl = 3600 if sources else 120
        return sources if 0 <= age < ttl else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def save_host_cache(title, movie_path, sources):
    path = source_cache_path(title, movie_path)
    temp_path = path + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as cache_file:
        json.dump({'schema': HOST_CACHE_SCHEMA, 'fetched_at': time.time(), 'sources': sources}, cache_file, ensure_ascii=False)
    os.replace(temp_path, path)


def add_adapter_hosts(title, path):
    """Automatically search providers on movie open, showing live progress and host rows."""
    cached_sources = load_host_cache(title, path)
    if cached_sources is not None:
        return render_host_rows(title, cached_sources)

    records = []
    errors = []
    counts = quality_counts()
    progress = xbmcgui.DialogProgress()
    progress.create('Hostok betöltése – %s' % title, 'Adapterek keresése indul...')
    cancelled = False
    total_adapters = len(ADAPTERS)
    try:
        for index, adapter in enumerate(ADAPTERS):
            if progress.iscanceled():
                cancelled = True
                break
            update_source_progress(
                progress, int(25 * index / max(1, total_adapters)),
                adapter.name, total_adapters - index, counts
            )
            try:
                records.extend(adapter.search(title) or [])
            except Exception as exc:
                errors.append('%s: %s' % (adapter.name, exc))
                xbmc.log('%s adapter search failed: %s' % (ADDON_ID, exc), xbmc.LOGWARNING)
            update_source_progress(
                progress, int(25 * (index + 1) / max(1, total_adapters)),
                adapter.name, total_adapters - index - 1, counts
            )
    except Exception as exc:
        errors.append('Adapter keresés: %s' % exc)
        xbmc.log('%s progress/search error: %s' % (ADDON_ID, exc), xbmc.LOGWARNING)

    wanted = normalize_title(title)
    groups = group_movies(records)
    matches = [group for group in groups if normalize_title(group.get('title', '')) == wanted]
    if not matches and not cancelled and wanted:
        stopwords = {'a', 'az', 'the', 'and', 'of', 'at', 'to', 'in', 'on', 'for'}
        wanted_tokens = set(wanted.split()) - stopwords
        ranked = []
        for group in groups:
            candidate = normalize_title(group.get('title', ''))
            candidate_tokens = set(candidate.split()) - stopwords
            shared = wanted_tokens & candidate_tokens
            overlap = len(shared) / float(max(1, len(wanted_tokens)))
            similarity = SequenceMatcher(None, wanted, candidate).ratio()
            if similarity >= 0.72 or (shared and similarity >= 0.40 and overlap >= 0.30):
                ranked.append((max(similarity, overlap), group))
        ranked.sort(key=lambda entry: entry[0], reverse=True)
        candidates = [group for _, group in ranked[:6]]
        if len(candidates) == 1:
            candidate_title = candidates[0].get('title', 'Ismeretlen cím')
            if xbmcgui.Dialog().yesno(
                'Nem pontos címegyezés', 'A forrás ezt találta: %s' % candidate_title,
                'Ez a keresett film: %s?' % title
            ):
                matches = candidates
        elif candidates:
            choice = xbmcgui.Dialog().select('Lehetséges címek', [g.get('title', 'Film') for g in candidates])
            if choice >= 0:
                matches = [candidates[choice]]

    sources = []
    if matches and not cancelled:
        group = matches[0]
        by_id = {adapter.adapter_id: adapter for adapter in ADAPTERS}
        tasks = [(movie, by_id.get(movie.get('adapter_id'))) for movie in group.get('movies', [])]
        tasks = [(movie, adapter) for movie, adapter in tasks if adapter]
        seen = set()
        try:
            for index, (movie, adapter) in enumerate(tasks):
                if progress.iscanceled():
                    cancelled = True
                    break
                update_source_progress(
                    progress, 25 + int(75 * index / max(1, len(tasks))), adapter.name,
                    len(tasks) - index, counts
                )
                try:
                    found = adapter.sources(movie) or []
                    accepted = []
                    for source in found:
                        source['adapter_name'] = source.get('adapter_name') or adapter.name
                        key = (
                            source['adapter_name'], str(source.get('host', '')).casefold(),
                            str(source.get('quality', '')).casefold(), str(source.get('language', '')).casefold()
                        )
                        if key not in seen:
                            seen.add(key)
                            sources.append(source)
                            accepted.append(source)
                    add_quality_counts(counts, accepted)
                except Exception as exc:
                    errors.append('%s: %s' % (adapter.name, exc))
                    xbmc.log('%s source listing failed: %s' % (ADDON_ID, exc), xbmc.LOGWARNING)
                update_source_progress(
                    progress, 25 + int(75 * (index + 1) / max(1, len(tasks))), adapter.name,
                    len(tasks) - index - 1, counts
                )
        except Exception as exc:
            errors.append('Forráslista: %s' % exc)
            xbmc.log('%s progress/source error: %s' % (ADDON_ID, exc), xbmc.LOGWARNING)
    progress.close()

    if not cancelled:
        try:
            save_host_cache(title, path, sources)
        except (OSError, TypeError, ValueError) as exc:
            xbmc.log('%s host cache save failed: %s' % (ADDON_ID, exc), xbmc.LOGWARNING)
    return render_host_rows(title, sources, cancelled, errors)


def render_host_rows(title, sources, cancelled=False, errors=None):
    errors = errors or []
    header = xbmcgui.ListItem(label='[COLOR FF65758B]          %s · FILMHOSTOK          [/COLOR]' % title)
    header.setProperty('IsPlayable', 'false')
    xbmcplugin.addDirectoryItem(HANDLE, plugin_url('noop'), header, False)
    if not sources:
        message = 'Nem találtam elérhető hostot ehhez a filmhez.'
        if cancelled:
            message = 'A hostkeresést megszakítottad.'
        elif errors:
            message += ' Egyes adapterek nem válaszoltak.'
        item = xbmcgui.ListItem(label='[COLOR FF9AA6B2]%s[/COLOR]' % message)
        item.setProperty('IsPlayable', 'false')
        xbmcplugin.addDirectoryItem(HANDLE, plugin_url('noop'), item, False)
        return

    token = save_source_queue(title, sources)
    for index, source in enumerate(sources):
        host = re.sub(r'\[/?COLOR[^\]]*\]', '', str(source.get('host', 'ismeretlen host')), flags=re.I)
        provider = re.sub(r'\[/?COLOR[^\]]*\]', '', str(source.get('adapter_name', 'FORRÁS')), flags=re.I)
        quality = re.sub(r'\[/?COLOR[^\]]*\]', '', str(source.get('quality', '') or '—'), flags=re.I)
        language = re.sub(r'\[/?COLOR[^\]]*\]', '', str(source.get('language', '') or '—'), flags=re.I)
        label = (
            '[COLOR FF55C7C2]%02d[/COLOR]  |  [COLOR FFD9B15F]%s[/COLOR]  |  '
            '[COLOR FFE6ECF2]%s[/COLOR]  |  [COLOR FF72D5C9]%s[/COLOR]  |  [COLOR FFBCA8E8]%s[/COLOR]'
        ) % (index + 1, provider, host, quality, language)
        item = xbmcgui.ListItem(label=label)
        set_video_info(item, {'title': title, 'mediatype': 'movie'})
        item.setProperty('IsPlayable', 'true')
        xbmcplugin.addDirectoryItem(HANDLE, plugin_url('play_sources', token=token, index=index), item, False)


def resolved_stream_url(result):
    if isinstance(result, dict):
        result = result.get('url') or result.get('stream_url') or ''
    elif isinstance(result, (tuple, list)):
        result = result[0] if result else ''
    if isinstance(result, str) and result.startswith(('http://', 'https://')):
        return result
    return ''


def play_sources(token, start_index):
    """Start with the clicked row, then move to later rows only on a resolve failure."""
    queue = load_source_queue(token)
    if not queue:
        xbmcgui.Dialog().notification('Mozipremierek.hu', 'A forráslista lejárt; nyisd meg újra a filmet.', xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    title = queue.get('title', 'Film')
    sources = queue['sources']
    try:
        start_index = max(0, int(start_index))
    except (TypeError, ValueError):
        start_index = 0
    if start_index >= len(sources):
        xbmcgui.Dialog().notification('Mozipremierek.hu', 'A kiválasztott forrássor már nem érhető el.', xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    progress = xbmcgui.DialogProgress()
    progress.create('Forrás ellenőrzése – %s' % title, 'Lejátszható host keresése indul...')
    remaining = len(sources) - start_index
    cancelled = False
    try:
        for offset, index in enumerate(range(start_index, len(sources))):
            if progress.iscanceled():
                cancelled = True
                break
            source = sources[index]
            host = str(source.get('host', 'ismeretlen host'))
            adapter_name = str(source.get('adapter_name', 'forrás'))
            source_url = source.get('source_url', '')
            percent = int(offset * 100 / max(1, remaining))
            progress.update(
                percent,
                '[COLOR FFE6ECF2]Host-próba:[/COLOR] [COLOR FFFF9E64]%d/%d[/COLOR]\n'
                '[COLOR FF72D5C9]%s[/COLOR]  |  [COLOR FFD9B15F]%s[/COLOR]\n'
                '[COLOR FFE6ECF2]Embed betöltése, feloldás és elérhetőség ellenőrzése...[/COLOR]' % (
                    offset + 1, remaining, adapter_name, host
                )
            )
            xbmc.log('%s trying row %d/%d (%s / %s)' % (ADDON_ID, index + 1, len(sources), adapter_name, host), xbmc.LOGINFO)
            if not source_url:
                adapter_id = source.get('adapter_id', '')
                adapter = next((item for item in ADAPTERS if item.adapter_id == adapter_id), None)
                source_resolver = getattr(adapter, 'resolve_source_url', None) if adapter else None
                if source_resolver:
                    try:
                        source_url = source_resolver(source) or ''
                    except Exception as exc:
                        error_text = str(exc)
                        xbmc.log('%s embed extraction failed at row %d (%s / %s): %s' % (ADDON_ID, index + 1, adapter_name, host, exc), xbmc.LOGWARNING)
                        lowered_error = error_text.lower()
                        if any(marker in lowered_error for marker in ('cloudflare', 'verification', 'captcha')):
                            status = 'Cloudflare/ellenőrző oldal — nem kerüljük meg; következő forrás...'
                        elif '404' in lowered_error:
                            status = 'A beküldött link 404-es; következő host...'
                        else:
                            status = 'A link lekérése nem sikerült; következő host...'
                        progress.update(
                            percent,
                            '[COLOR FFE6ECF2]Host-próba:[/COLOR] [COLOR FFFF9E64]%d/%d[/COLOR]\n'
                            '[COLOR FF72D5C9]%s[/COLOR]  |  [COLOR FFD9B15F]%s[/COLOR]\n'
                            '[COLOR FFFF7777]%s[/COLOR]' % (offset + 1, remaining, adapter_name, host, status)
                        )
                        if source.get('parent_resolve_only'):
                            continue
                    if source_url:
                        embed_host = urlparse(source_url).netloc
                        progress.update(
                            percent,
                            '[COLOR FFE6ECF2]Host-próba:[/COLOR] [COLOR FFFF9E64]%d/%d[/COLOR]\n'
                            '[COLOR FF72D5C9]%s[/COLOR]  |  [COLOR FFD9B15F]%s → %s[/COLOR]\n'
                            '[COLOR FFE6ECF2]Feloldás és elérhetőség ellenőrzése...[/COLOR]' % (
                                offset + 1, remaining, adapter_name, host, embed_host
                            )
                        )
                        xbmc.log('%s extracted embed at row %d: %s' % (ADDON_ID, index + 1, embed_host), xbmc.LOGINFO)
                    elif source.get('parent_resolve_only'):
                        progress.update(
                            percent,
                            '[COLOR FFE6ECF2]Host-próba:[/COLOR] [COLOR FFFF9E64]%d/%d[/COLOR]\n'
                            '[COLOR FF72D5C9]%s[/COLOR]  |  [COLOR FFD9B15F]%s[/COLOR]\n'
                            '[COLOR FFFF7777]Nem érkezett használható embed URL; következő host...[/COLOR]' % (
                                offset + 1, remaining, adapter_name, host
                            )
                        )
                        continue
            if source_url and (zidervisionurlresolver or resolveurl):
                stream = ''
                if zidervisionurlresolver:
                    try:
                        stream = resolved_stream_url(zidervisionurlresolver.resolve(source_url))
                    except Exception as exc:
                        xbmc.log('%s ZiderVision resolver failed at row %d (%s / %s): %s' % (ADDON_ID, index + 1, adapter_name, host, exc), xbmc.LOGWARNING)
                if not stream and resolveurl:
                    try:
                        media = resolveurl.HostedMediaFile(source_url)
                        stream = resolved_stream_url(media.resolve()) if media and media.valid_url() else ''
                    except Exception as exc:
                        xbmc.log('%s ResolveURL failed at row %d (%s / %s): %s' % (ADDON_ID, index + 1, adapter_name, host, exc), xbmc.LOGWARNING)
                        stream = ''
                if stream and stream_is_available(stream):
                    xbmc.log('%s resolved row %d (%s / %s)' % (ADDON_ID, index + 1, adapter_name, host), xbmc.LOGINFO)
                    progress.update(100, '[COLOR FF55C7C2]Forrás használható — lejátszás indítása:[/COLOR] [COLOR FFD9B15F]%s[/COLOR]' % host)
                    item = xbmcgui.ListItem(label=title, path=stream)
                    item.setProperty('IsPlayable', 'true')
                    set_video_info(item, {'title': title, 'mediatype': 'movie'})
                    xbmcplugin.setResolvedUrl(HANDLE, True, item)
                    return
                xbmc.log('%s resolved stream unavailable at row %d (%s / %s); continuing' % (ADDON_ID, index + 1, adapter_name, host), xbmc.LOGINFO)
            if source_url:
                xbmc.log('%s direct source unavailable at row %d (%s / %s); continuing' % (ADDON_ID, index + 1, adapter_name, host), xbmc.LOGINFO)
                if source.get('parent_resolve_only') and (zidervisionurlresolver or resolveurl):
                    continue

            # Preserve row identity: delegate only to this row's own player route.
            fallback = source.get('play_url', '')
            if not fallback.startswith('plugin://'):
                continue
            addon_id = fallback[len('plugin://'):].split('/', 1)[0]
            if addon_id and not xbmc.getCondVisibility('System.HasAddon(%s)' % addon_id):
                xbmc.log('%s skipped row %d (%s / %s): required addon %s is not installed' % (ADDON_ID, index + 1, adapter_name, host, addon_id), xbmc.LOGWARNING)
                continue
            xbmc.log('%s handing off clicked/fallback row %d (%s / %s) to %s' % (ADDON_ID, index + 1, adapter_name, host, addon_id), xbmc.LOGINFO)
            progress.update(100, '[COLOR FF55C7C2]Host átadása a lejátszónak:[/COLOR] [COLOR FFD9B15F]%s[/COLOR]' % host)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            xbmc.executebuiltin('PlayMedia(%s)' % fallback)
            return
        if cancelled:
            xbmcgui.Dialog().notification('Mozipremierek.hu', 'A hostpróbát megszakítottad.', xbmcgui.NOTIFICATION_INFO)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        else:
            xbmcgui.Dialog().notification('Mozipremierek.hu', 'Egyik hostot sem sikerült feloldani.', xbmcgui.NOTIFICATION_ERROR, 4500)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
    finally:
        progress.close()


def stream_is_available(url):
    """Lightweight availability check so a dead resolved link is skipped before playback."""
    target = url
    headers = {'User-Agent': 'Mozilla/5.0 (Kodi; plugin.video.mozipremierek/1.6.2)', 'Range': 'bytes=0-0'}
    if '|' in url:
        target, raw_headers = url.split('|', 1)
        for key, values in parse_qs(raw_headers, keep_blank_values=True).items():
            if values:
                headers[key] = values[-1]
        headers['Range'] = 'bytes=0-0'
    request = Request(target, headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            content_type = response.headers.get('Content-Type', '').lower()
            if response.getcode() >= 400 or 'text/html' in content_type:
                return False
            response.read(1)
            return True
    except HTTPError as exc:
        return exc.code == 416
    except (URLError, TimeoutError, OSError, ValueError):
        return False


def show_info(path):
    if not path.startswith('/movie/'):
        raise RuntimeError('Érvénytelen film-adatlap.')
    parser = parse_page(path)
    title = parser.page_title or 'Film adatlap'
    description = parser.description
    # The site's meta description begins with year/rating/genre/runtime metadata.
    parts = description.split(' - ', 4)
    short_description = parts[4].strip() if len(parts) > 4 else description
    plot = parser.plot or short_description
    genres = ', '.join(dict.fromkeys(g['label'] for g in parser.genres if g.get('label')))
    content = []
    if short_description:
        content.append('Rövid leírás\n' + short_description)
    if plot:
        content.append('Részletes leírás\n' + plot)
    if genres:
        content.append('Műfajok\n' + genres)
    if not content:
        content.append('Ehhez a filmhez nem található leírás a weboldalon.')
    xbmcgui.Dialog().textviewer(title, '\n\n'.join(content))
    xbmcplugin.endOfDirectory(HANDLE, succeeded=True)


def show_webpage(path):
    url = urljoin(BASE, path or '/')
    xbmcgui.Dialog().textviewer('Mozipremierek.hu adatlap', url)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=True)


def search_stb(title):
    query = (title or '').strip()
    if not query:
        keyboard = xbmc.Keyboard('', 'Keresési kifejezés:')
        keyboard.doModal()
        if keyboard.isConfirmed():
            query = keyboard.getText().strip()
        else:
            return
    if not query:
        xbmcgui.Dialog().notification(
            'Mozipremierek.hu', 'Nincs megadva keresési kifejezés', xbmcgui.NOTIFICATION_WARNING
        )
        return
    if not xbmc.getCondVisibility('System.HasAddon(plugin.video.stb_hu)'):
        xbmcgui.Dialog().notification(
            'Mozipremierek.hu', 'A kereséshez telepítsd a plugin.video.stb_hu kiegészítőt.',
            xbmcgui.NOTIFICATION_WARNING
        )
        return
    stb_path = 'plugin://plugin.video.stb_hu/?action=get_search_items&search_text=%s' % quote_plus(query)
    xbmc.executebuiltin('Container.Update(%s)' % stb_path)


def play_trailer(video_id):
    if not re.match(r'^[A-Za-z0-9_-]{6,20}$', video_id or ''):
        raise RuntimeError('Érvénytelen YouTube-azonosító.')
    if not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
        xbmcgui.Dialog().ok('Hiányzó kiegészítő', 'Az előzetes lejátszásához telepítsd a Kodi YouTube kiegészítőjét (plugin.video.youtube).')
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    item = xbmcgui.ListItem(path='plugin://plugin.video.youtube/play/?video_id=' + video_id)
    item.setProperty('IsPlayable', 'true')
    xbmcplugin.setResolvedUrl(HANDLE, True, item)


def main():
    params = parse_qs(sys.argv[2][1:]) if len(sys.argv) > 2 and sys.argv[2] else {}
    action = params.get('action', ['root'])[0]
    path = params.get('path', [''])[0]
    provider = params.get('provider', [''])[0]
    year = params.get('year', [str(datetime.date.today().year)])[0]
    mode = params.get('mode', [''])[0]
    page = params.get('page', ['1'])[0]
    title = params.get('title', [''])[0]
    try:
        if action == 'root':
            show_root()
        elif action == 'years':
            show_years()
        elif action == 'genres':
            show_genres(mode, year)
        elif action == 'providers':
            show_providers(year)
        elif action == 'list':
            show_list(path, provider, page)
        elif action == 'latest':
            show_latest()
        elif action == 'movie':
            show_movie(path)
        elif action == 'info':
            show_info(path)
        elif action == 'webpage':
            show_webpage(path)
        elif action == 'search_stb':
            search_stb(title)
        elif action == 'play_sources':
            play_sources(params.get('token', [''])[0], params.get('index', ['0'])[0])
        elif action == 'noop':
            xbmcplugin.endOfDirectory(HANDLE, succeeded=True)
        elif action == 'play':
            play_trailer(params.get('video_id', [''])[0])
        else:
            show_root()
    except Exception as exc:
        xbmc.log('%s error: %s' % (ADDON_ID, exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok('Mozipremierek.hu', str(exc))
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


if __name__ == '__main__':
    main()
