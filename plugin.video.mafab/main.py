# -*- coding: utf-8 -*-
"""Mafab.hu - Kodi 21 (Omega) video plugin entry point."""
import sys
import traceback
from urllib.parse import parse_qsl, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

import re
from concurrent.futures import ThreadPoolExecutor

from resources.lib.perf import timed
from resources.lib.scraper import (Scraper, ScrapeError, split_year, PROVIDERS, PROVIDER_BY_SLUG,
                                   VOD_PAGE, guess_series, clean_channel, PEOPLE_ROLES, BIRTHDAYS_PAGE)

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_NAME = ADDON.getAddonInfo('name')
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]


def tr(string_id):
    return ADDON.getLocalizedString(string_id)


def log(msg, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, msg), level)


def build_url(**params):
    return '%s?%s' % (BASE_URL, urlencode(params))


def notify(message, icon=xbmcgui.NOTIFICATION_INFO):
    xbmcgui.Dialog().notification(ADDON_NAME, message, icon, 4000)


def make_scraper():
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    debug = ADDON.getSettingBool('debug')
    return Scraper(cache_dir=profile + 'cache',
                   ttl_hours=ADDON.getSettingInt('cache_hours'),
                   debug=debug,
                   log=lambda m: log(m, xbmc.LOGINFO if debug else xbmc.LOGDEBUG))


YELLOW = 'FFFFD700'
LABEL = 'FF72D5C9'


SERIES_COLOR = 'FF66CC88'
SERIES_TAG = '[COLOR %s][B]SOROZAT[/B][/COLOR]' % SERIES_COLOR


def with_year(title, year, series=False):
    """List/label text: title, the year in yellow and a green SOROZAT tag for series."""
    text = '%s [COLOR %s](%s)[/COLOR]' % (title, YELLOW, year) if year else title
    return '%s  %s' % (text, SERIES_TAG) if series else text


def fmt_runtime(seconds):
    minutes = int(seconds) // 60
    return '%d ó %02d p' % (minutes // 60, minutes % 60) if minutes >= 60 else '%d p' % minutes


def rich_plot(meta, plot, year):
    """Info-panel text: highlighted facts line, credits, then the plot."""
    facts = []
    if year:
        facts.append('[B][COLOR %s]%s[/COLOR][/B]' % (YELLOW, year))
    if meta.get('is_series'):
        facts.append(SERIES_TAG)
    if meta.get('duration'):
        facts.append(fmt_runtime(meta['duration']))
    if meta.get('rating') is not None:
        votes = ' (%s)' % meta['votes'] if meta.get('votes') else ''
        facts.append('[COLOR FFFFA500]\u2605 %.1f[/COLOR]%s' % (float(meta['rating']), votes))
    if meta.get('mpaa'):
        facts.append('[COLOR FFFF7777]%s[/COLOR]' % meta['mpaa'])
    if meta.get('countries'):
        facts.append(', '.join(meta['countries']))
    lines = [' | '.join(facts)] if facts else []
    if meta.get('premiered'):
        parts = str(meta['premiered']).split('-')
        shown = '%s. %s. %s.' % (parts[0], parts[1], parts[2]) if len(parts) == 3 else meta['premiered']
        lines.append('[COLOR FF8A93A0][I][UPPERCASE]Premier[/UPPERCASE][/I][/COLOR]\n'
                     '[COLOR FFB7C0CC][LIGHT]%s[/LIGHT][/COLOR]' % shown)

    def credit(label, values):
        if values:
            lines.append('[COLOR %s]%s:[/COLOR] %s' % (LABEL, label, ', '.join(values)))
    tags = ['[B][COLOR %s]%s[/COLOR][/B]' % (PROVIDER_BY_SLUG[p][1], PROVIDER_BY_SLUG[p][0])
            for p in (meta.get('providers') or []) if p in PROVIDER_BY_SLUG]
    if tags:
        lines.append('[COLOR %s]Streaming:[/COLOR] %s' % (LABEL, '  '.join(tags)))
    credit('Rendező', meta.get('directors'))
    credit('Író', meta.get('writers'))
    credit('Szereplők', (meta.get('cast') or [])[:8])
    credit('Stúdió', meta.get('studios'))
    if meta.get('originaltitle'):
        lines.append('[COLOR %s]Eredeti cím:[/COLOR] %s' % (LABEL, meta['originaltitle']))
    text = '\n'.join(lines)
    return '%s\n\n%s' % (text, plot) if text and plot else (text or plot or '')


def decorate(item, title, thumb='', plot='', year=None, meta=None, mediatype=None):
    """Title (year in yellow), rich plot, art and full metadata on a ListItem."""
    meta = meta or {}
    year = year or meta.get('year')
    tag = item.getVideoInfoTag()
    tag.setTitle(with_year(title, year, meta.get('is_series')))
    if mediatype or meta.get('is_series'):
        tag.setMediaType('tvshow' if meta.get('is_series') else mediatype)
    text = rich_plot(meta, meta.get('plot') or plot, year)
    if text:
        tag.setPlot(text)
    if year:
        tag.setYear(int(year))
    if meta.get('originaltitle'):
        tag.setOriginalTitle(meta['originaltitle'])
    if meta.get('genres'):
        tag.setGenres(meta['genres'])
    if meta.get('directors'):
        tag.setDirectors(meta['directors'])
    if meta.get('writers'):
        tag.setWriters(meta['writers'])
    if meta.get('countries'):
        tag.setCountries(meta['countries'])
    if meta.get('studios'):
        tag.setStudios(meta['studios'])
    if meta.get('premiered'):
        tag.setPremiered(meta['premiered'])
    if meta.get('cast'):
        tag.setCast([xbmc.Actor(name, '', idx, '') for idx, name in enumerate(meta['cast'])])
    if meta.get('rating') is not None:
        tag.setRating(float(meta['rating']), int(meta.get('votes') or 0), 'mafab', True)
    if meta.get('duration'):
        tag.setDuration(int(meta['duration']))
    if meta.get('mpaa'):
        tag.setMpaa(meta['mpaa'])
    poster = meta.get('poster') or thumb
    art = {}
    if poster or thumb:
        art.update({'thumb': poster or thumb, 'poster': poster or thumb, 'icon': poster or thumb})
    if meta.get('fanart'):
        art['fanart'] = meta['fanart']
    if art:
        item.setArt(art)


def add_folder(label, url, thumb='', plot='', year=None, meta=None, title=None):
    item = xbmcgui.ListItem(label=label)
    decorate(item, title or label, thumb, plot, year, meta)
    xbmcplugin.addDirectoryItem(HANDLE, url, item, True)


def add_playable(label, url, thumb='', plot='', year=None, meta=None, title=None):
    item = xbmcgui.ListItem(label=label)
    decorate(item, title or label, thumb, plot, year, meta, mediatype='video')
    item.setProperty('IsPlayable', 'true')
    xbmcplugin.addDirectoryItem(HANDLE, url, item, False)


def load_metas(urls):
    """{url: meta} for a page of items, fetched in parallel (cached for a week)."""
    if not urls or not ADDON.getSettingBool('fetch_meta'):
        return {}
    scraper = make_scraper()

    def one(url):
        try:
            return url, scraper.get_meta(url)
        except Exception as exc:  # noqa: BLE001 - one bad page must not break the list
            log('meta error %s: %s' % (url, exc), xbmc.LOGWARNING)
            return url, {}
    try:
        limit = int(ADDON.getSettingInt('meta_limit'))
    except (TypeError, ValueError):
        limit = 10
    if limit <= 0:
        return {}
    with timed('load_metas (%d items)' % min(limit, len(urls))):
        with ThreadPoolExecutor(max_workers=8) as pool:   # the rest of the list keeps the card's own data
            return dict(pool.map(one, urls[:limit]))


def end_dir(content='movies', cache=True):
    xbmcplugin.setContent(HANDLE, content)
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=cache)


# ------------------------------------------------------------------ routes --
def clear_cache():
    """Delete cached pages, details, host lists and search data (never settings.xml)."""
    import glob
    import os
    profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    removed = 0
    paths = glob.glob(os.path.join(profile, 'cache', '*'))
    for pattern in ('host_cache_*.json', 'source_queue_*.json', 'search_*.json', 'host_support.json'):
        paths += glob.glob(os.path.join(profile, pattern))
    for path in paths:
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
        except OSError as exc:
            log('cache delete failed %s: %s' % (path, exc), xbmc.LOGWARNING)
    notify(tr(30107) % removed)
    xbmc.executebuiltin('Container.Refresh')


def root():
    scraper = make_scraper()
    add_folder(tr(30000), build_url(action='home'))
    try:
        for label, url, kind in scraper.discover_menu():
            add_folder(label, build_url(action='list', url=url, kind=kind))
    except ScrapeError as exc:
        log('menu discovery failed: %s' % exc, xbmc.LOGWARNING)
        notify(tr(30008), xbmcgui.NOTIFICATION_WARNING)
    add_folder(tr(30012), build_url(action='people_menu'))
    add_folder(tr(30011), build_url(action='providers'))
    add_folder(tr(30010), build_url(action='tv_days'))
    add_folder(tr(30001), build_url(action='search'))
    add_folder(tr(30119), build_url(action='filter'))
    add_folder(tr(30106), build_url(action='clear_cache'))
    end_dir('files')


def is_series(url, title, meta, kind='', known=()):
    """Series if a series list / the detail page / an earlier visit says so, else a cautious text guess."""
    if kind == 'series' or url in known or meta.get('is_series') is True:
        return True
    if meta.get('is_series') is False:
        return False
    return guess_series(title, meta.get('plot'))


def merge_meta(it, detail):
    """Detail-page metadata, completed with what the list card itself already told us."""
    meta = dict(detail or {})
    for key in ('plot', 'genres', 'premiered', 'year'):
        if it.get(key) and not meta.get(key):
            meta[key] = it[key]
    if it.get('rating') is not None and not meta.get('rating'):
        meta['rating'] = it['rating']
    return meta


def show_items(items, kind, prov=''):
    metas = load_metas([it['url'] for it in items]) if kind != 'video' else {}
    scraper = make_scraper()
    index = scraper.provider_index() if kind != 'video' else {}
    series_known = scraper.series_index() if kind != 'video' else set()
    sure = []
    for it in items:
        meta = merge_meta(it, metas.get(it['url']))
        if kind != 'video':
            # the card's own platform badge is authoritative; the browsed provider is only a fallback
            card = list(it.get('providers') or [])
            fallback = [] if card else ([prov] if prov else [])
            known = list(dict.fromkeys(card + fallback + list(index.get(it['url'], [])) +
                                       list(meta.get('providers') or [])))
            if known:
                meta['providers'] = known
            series = True if it.get('is_series') else is_series(it['url'], it['title'], meta, kind, series_known)
            meta['is_series'] = series
            if series and (kind == 'series' or it.get('is_series') or (metas.get(it['url']) or {}).get('is_series') is True):
                sure.append(it['url'])      # certain (not just guessed): remember for other lists
        if kind == 'video':
            add_playable(with_year(it['title'], it.get('year')), build_url(action='play', url=it['url']),
                         it['thumb'], year=it.get('year'), title=it['title'])
        else:
            year = it.get('year') or meta.get('year')
            add_folder(with_year(it['title'], year, meta.get('is_series')),
                       build_url(action='film', url=it['url'], title=it['title'], year=year or '', prov=prov),
                       it['thumb'], year=year, meta=meta, title=it['title'])
    if sure:
        scraper.series_index_add(sure)


def home():
    items = make_scraper().home_items()
    if not items:
        notify(tr(30009))
    show_items(items, 'film')
    end_dir()


SECTIONS = [('streaming-premierek', 'Hamarosan streamingen'), ('korabbi-premierek', 'Korábbi megjelenések')]


def providers(section=''):
    """Streaming: first pick the list (upcoming / earlier), then the provider (or all)."""
    if section not in dict(SECTIONS):
        for slug, label in SECTIONS:
            add_folder(label, build_url(action='providers', section=slug), title=label)
        end_dir('files')
        return
    base = VOD_PAGE % section
    add_folder('[B]Összes[/B]', build_url(action='list', url=base, kind='film'), title='Összes')
    for slug, name, color in PROVIDERS:
        add_folder('[B][COLOR %s]%s[/COLOR][/B]' % (color, name),
                   build_url(action='list', url='%s/%s' % (base, slug), kind='film', prov=slug), title=name)
    end_dir('files')


def list_items(url, kind, prov=''):
    scraper = make_scraper()
    items, next_url = scraper.list_page(url)
    if not items:
        notify(tr(30009))
    by_slug = {}
    for it in items:
        for slug in (it.get('providers') or ([prov] if prov else [])):
            by_slug.setdefault(slug, []).append(it['url'])
    for slug, urls in by_slug.items():
        scraper.provider_index_add(slug, urls)
    show_items(items, kind, prov)
    if next_url and next_url != url:
        add_folder('[B]%s >>[/B]' % tr(30002),
                   build_url(action='list', url=next_url, kind=kind, prov=prov))
    end_dir()


def clean_title(value):
    """Title for source searches: no site suffix, no year ("A kaptár 2026" -> "A kaptár")."""
    value = re.sub(r'\s*[-|\u2013]\s*Mafab(\.hu)?.*$', '', value or '', flags=re.I)
    value = re.sub(r'\s*[\(\[]\s*(?:19|20)\d{2}\s*[\)\]]', ' ', value)
    return split_year(value)[0]


def film(url, title='', year='', prov=''):
    scraper = make_scraper()
    info = scraper.parse_detail(url)
    meta = scraper.get_meta(url) if ADDON.getSettingBool('fetch_meta') else {}
    index = scraper.provider_index()
    meta = dict(meta, providers=list(dict.fromkeys(([prov] if prov else []) + list(index.get(url, [])) +
                                                    list(meta.get('providers') or []))))
    thumb = meta.get('poster') or info['poster']
    plot = meta.get('plot') or info['plot']
    meta['is_series'] = is_series(url, clean_title(title or info['title']), dict(meta, plot=plot),
                                  known=scraper.series_index())
    title = clean_title(title or info['title']) or url
    year = int(year) if str(year).isdigit() else meta.get('year')
    shown = with_year(title, year, meta.get('is_series'))
    from resources.lib import hosts      # imported on demand: it pulls in the adapters and resolvers
    hosts.META = dict(meta, plot=plot, poster=thumb, year=year)
    for vid in info['youtube']:
        add_playable('%s - %s [YouTube %s]' % (tr(30004), shown, vid),
                     build_url(action='yt', id=vid), thumb, plot, year=year, meta=meta, title=title)
    if not info['youtube']:
        add_playable('%s - %s' % (tr(30004), shown), build_url(action='play', url=url),
                     thumb, plot, year=year, meta=meta, title=title)
    # Same title-based host search as plugin.video.mozipremierek (adapters).
    hosts.add_adapter_hosts(title, url)
    end_dir('videos', cache=False)


def tv_days():
    for label, value in make_scraper().tv_days():
        add_folder(label, build_url(action='tv', date=value, page=1))
    end_dir('files', cache=False)


def tv(date, page):
    page = int(page or 1)
    rows, pages = make_scraper().tv_program(date, page)
    if not rows:
        notify(tr(30009))
    metas = load_metas([r['url'] for r in rows])
    scraper = make_scraper()
    series_known = scraper.series_index()
    sure = []
    for r in rows:
        channel = clean_channel(r['channel'])           # never show the time twice
        label = ' '.join(x for x in ('[COLOR FFD9B15F]%s[/COLOR]' % r['time'] if r['time'] else '',
                                     '[COLOR FF72D5C9]%s[/COLOR]' % channel if channel else '',
                                     with_year(r['title'], r.get('year') or (metas.get(r['url']) or {}).get('year'))) if x)
        year = r.get('year') or (metas.get(r['url']) or {}).get('year')
        tvmeta = dict(metas.get(r['url']) or {})
        if r.get('is_series') is not None:          # the site's own film/series filter decided
            tvmeta['is_series'] = r['is_series']
        tvmeta['is_series'] = is_series(r['url'], r['title'], tvmeta, known=series_known)
        if r.get('is_series') is True:
            sure.append(r['url'])
        if tvmeta['is_series']:
            label += '  ' + SERIES_TAG
        add_folder(label, build_url(action='film', url=r['url'], title=r['title'],
                                    year=year or ''), r['thumb'], year=year,
                   meta=tvmeta, title=r['title'])
    if sure:
        scraper.series_index_add(sure)
    if page < pages:
        add_folder('[B]%s >>[/B]' % tr(30002), build_url(action='tv', date=date, page=page + 1))
    end_dir('movies', cache=False)


def people_menu():
    for genre, label in PEOPLE_ROLES:
        add_folder(label, build_url(action='people', genre=genre, page=1), title=label)
    add_folder('Születésnapok', build_url(action='people', url=BIRTHDAYS_PAGE, page=1), title='Születésnapok')
    end_dir('files')


def person_plot(p):
    """Info-panel text for a person: birth line, place, known films, bio."""
    lines = []
    if p.get('info'):
        born = p['info'].split('/', 1)[0].strip()
        lines.append('[B][COLOR %s]%s[/COLOR][/B]' % (YELLOW, born))
    if p.get('place'):
        lines.append('[COLOR %s]Hely:[/COLOR] %s' % (LABEL, p['place']))
    if p.get('films'):
        lines.append('[COLOR %s]Ismert filmek:[/COLOR] %s' % (LABEL, ', '.join(f['title'] for f in p['films'])))
    head = '\n'.join(lines)
    return '%s\n\n%s' % (head, p['bio']) if head and p.get('bio') else (head or p.get('bio') or '')


def people(genre='', page=1, url=''):
    page = int(page or 1)
    scraper = make_scraper()
    persons, has_next = scraper.people_page(page, genre, url or None)
    if not persons:
        notify(tr(30009))
    for p in persons:
        item = xbmcgui.ListItem(label=p['name'])
        tag = item.getVideoInfoTag()
        tag.setTitle(p['name'])
        tag.setPlot(person_plot(p))
        if p['thumb']:
            item.setArt({'thumb': p['thumb'], 'poster': p['thumb'], 'icon': p['thumb'], 'fanart': p['thumb']})
        xbmcplugin.addDirectoryItem(HANDLE, build_url(action='person', url=p['url'], name=p['name']), item, True)
    if has_next:
        add_folder('[B]%s >>[/B]' % tr(30002), build_url(action='people', genre=genre, page=page + 1))
    end_dir('files', cache=False)


def person(url, name=''):
    scraper = make_scraper()
    films, card = scraper.person_films(url)
    if not films:
        notify(tr(30009))
    show_items([{'url': f['url'], 'title': f['title'], 'thumb': '', 'year': f.get('year')} for f in films], 'film')
    end_dir('movies', cache=False)


def filter_search():
    """Mafab's advanced filters, picked step by step in a menu; "Keresés" opens the result list."""
    from resources.lib import filters
    dialog = xbmcgui.Dialog()
    state = filters.new_state()

    def names(pairs, chosen):
        return ', '.join(label for key, label in pairs if key in chosen) or tr(30114)

    def label_of(pairs, key):
        return next((label for k, label in pairs if k == key), tr(30114))

    while True:
        kinds = (tr(30120) if state['movies'] and state['series'] else tr(30121) if state['movies'] else tr(30122))
        rows = [
            '%s: %s' % (tr(30108), kinds),
            '%s: %s' % (tr(30109), names(filters.GENRES, state['genres'])),
            '%s: %s' % (tr(30110), label_of(filters.RATINGS, state['rating'])),
            '%s: %s' % (tr(30111), label_of(filters.AGES, state['age'])),
            '%s: %s' % (tr(30112), state['year_from'] or tr(30114)),
            '%s: %s' % (tr(30113), state['year_to'] or tr(30114)),
            '%s: %s' % (tr(30115), state['country'][1] if state['country'] else tr(30114)),
            '%s: %s' % (tr(30116), names(filters.PLATFORMS, state['platforms'])),
            '%s: %s' % (tr(30117), state['keyword'] or tr(30114)),
            '[B]%s[/B]' % tr(30118),
        ]
        pick = dialog.select(tr(30119), rows)
        if pick < 0:
            return
        if pick == 0:
            choice = dialog.select(tr(30108), [tr(30120), tr(30121), tr(30122)])
            if choice >= 0:
                state['movies'], state['series'] = (choice in (0, 1)), (choice in (0, 2))
        elif pick == 1:
            chosen = dialog.multiselect(tr(30109), [l for _, l in filters.GENRES],
                                        preselect=[i for i, (k, _) in enumerate(filters.GENRES) if k in state['genres']])
            if chosen is not None:
                state['genres'] = [filters.GENRES[i][0] for i in chosen]
        elif pick in (2, 3):
            key, pairs = ('rating', filters.RATINGS) if pick == 2 else ('age', filters.AGES)
            choice = dialog.select(tr(30110 if pick == 2 else 30111), [l for _, l in pairs])
            if choice >= 0:
                state[key] = pairs[choice][0]
        elif pick in (4, 5):
            key = 'year_from' if pick == 4 else 'year_to'
            value = dialog.numeric(0, tr(30112 if pick == 4 else 30113), str(state[key] or ''))
            if value is not None and str(value).strip().isdigit():
                state[key] = int(value) if 1900 <= int(value) <= 2029 else 0
        elif pick == 6:
            labels = [tr(30114)] + [l for _, l in filters.COUNTRIES]
            choice = dialog.select(tr(30115), labels)
            if choice >= 0:
                state['country'] = filters.COUNTRIES[choice - 1] if choice else None
        elif pick == 7:
            chosen = dialog.multiselect(tr(30116), [l for _, l in filters.PLATFORMS],
                                        preselect=[i for i, (k, _) in enumerate(filters.PLATFORMS) if k in state['platforms']])
            if chosen is not None:
                state['platforms'] = [filters.PLATFORMS[i][0] for i in chosen]
        elif pick == 8:
            state['keyword'] = dialog.input(tr(30117), state['keyword'], type=xbmcgui.INPUT_ALPHANUM) or ''
        elif pick == 9:
            try:
                with timed('filter request'):
                    url, count = filters.results_url(state)
            except Exception as exc:  # noqa: BLE001
                log('filter search failed: %s' % exc, xbmc.LOGWARNING)
                notify(tr(30008), xbmcgui.NOTIFICATION_WARNING)
                continue
            if count == 0:
                notify(tr(30009))
                continue
            xbmc.executebuiltin('Container.Update(%s)' % build_url(action='list', url=url, kind='film'))
            return


def search():
    query = xbmcgui.Dialog().input(tr(30003), type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        return
    xbmc.executebuiltin('Container.Update(%s)' % build_url(action='results', q=query))


SEARCH_PAGE = 20    # hits per screen: only these get detail fetches, the rest waits for "next"


def results(query, url=None, page=1):
    page = max(int(page or 1), 1)
    scraper = make_scraper()
    if url:
        items, next_url = scraper.list_page(url, exclude_sidebar=True)
    else:
        items, next_url = scraper.search(query)
    persons = [] if (url or page > 1) else list(getattr(scraper, 'last_search_people', []) or [])
    total = len(items)
    if not url:     # the site sends every hit at once: show them in slices
        items = items[(page - 1) * SEARCH_PAGE:page * SEARCH_PAGE]
    if not items and not persons:
        notify(tr(30009))
    for p in persons:       # matching celebrities first
        item = xbmcgui.ListItem(label='[COLOR %s]%s[/COLOR]' % (LABEL, p['name']))
        item.getVideoInfoTag().setTitle(p['name'])
        item.getVideoInfoTag().setPlot(person_plot(p))
        if p['thumb']:
            item.setArt({'thumb': p['thumb'], 'poster': p['thumb'], 'icon': p['thumb']})
        xbmcplugin.addDirectoryItem(HANDLE, build_url(action='person', url=p['url'], name=p['name']), item, True)
    show_items(items, 'film')
    if not url and page * SEARCH_PAGE < total:
        add_folder('[B]%s >> (%d/%d)[/B]' % (tr(30002), page * SEARCH_PAGE, total),
                   build_url(action='results', q=query, page=page + 1))
    elif next_url and next_url != url:
        add_folder('[B]%s >>[/B]' % tr(30002), build_url(action='results', q=query, url=next_url))
    end_dir(cache=False)


def play_yt(video_id):
    if not xbmc.getCondVisibility('System.AddonIsEnabled(plugin.video.youtube)'):
        notify(tr(30007), xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    path = 'plugin://plugin.video.youtube/play/?video_id=%s' % video_id
    xbmcplugin.setResolvedUrl(HANDLE, True, xbmcgui.ListItem(path=path))


def play(url):
    options = make_scraper().resolve(url)
    if not options:
        notify(tr(30006), xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    index = 0
    if len(options) > 1:
        index = xbmcgui.Dialog().select(tr(30005), [label for label, _ in options])
        if index < 0:
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
    path = options[index][1]
    if path.startswith('plugin://plugin.video.youtube') and not xbmc.getCondVisibility(
            'System.AddonIsEnabled(plugin.video.youtube)'):
        notify(tr(30007), xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    xbmcplugin.setResolvedUrl(HANDLE, True, xbmcgui.ListItem(path=path))


def router(paramstring):
    params = dict(parse_qsl(paramstring))
    action = params.get('action')
    with timed('SCREEN %s' % (action or 'root')):
        _route(params, action)


def _route(params, action):
    if action is None:
        root()
    elif action == 'home':
        home()
    elif action == 'list':
        list_items(params['url'], params.get('kind', 'film'), params.get('prov', ''))
    elif action == 'film':
        film(params['url'], params.get('title', ''), params.get('year', ''), params.get('prov', ''))
    elif action == 'play_sources':
        from resources.lib import hosts
        hosts.play_sources(params.get('token', ''), params.get('index', '0'))
    elif action == 'filter':
        filter_search()
    elif action == 'clear_cache':
        clear_cache()
    elif action == 'noop':
        pass
    elif action == 'people_menu':
        people_menu()
    elif action == 'people':
        people(params.get('genre', ''), params.get('page'), params.get('url', ''))
    elif action == 'person':
        person(params['url'], params.get('name', ''))
    elif action == 'providers':
        providers(params.get('section', ''))
    elif action == 'tv_days':
        tv_days()
    elif action == 'tv':
        tv(params.get('date'), params.get('page'))
    elif action == 'search':
        search()
    elif action == 'results':
        results(params.get('q', ''), params.get('url'), params.get('page', 1))
    elif action == 'yt':
        play_yt(params['id'])
    elif action == 'play':
        play(params['url'])


if __name__ == '__main__':
    try:
        router(sys.argv[2][1:])
    except ScrapeError as exc:
        log('scrape error: %s' % exc, xbmc.LOGERROR)
        notify(tr(30008), xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
    except Exception:  # noqa: BLE001 - show anything unexpected in the log
        log(traceback.format_exc(), xbmc.LOGERROR)
        notify('Error - see kodi.log', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
