# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

import json
import sys
from urllib.parse import parse_qs, urlencode, urlparse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

from . import s365

ADDON = xbmcaddon.Addon()
ADDON_HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]
HISTORY_SETTING = 'search_history'
RECENT_SETTING = 'recent_episodes'
HISTORY_LIMIT = 12
RECENT_LIMIT = 24
COLOR_CYAN = 'FF4FC3F7'
COLOR_ORANGE = 'FFFFB74D'
COLOR_GREEN = 'FF81C784'
COLOR_PURPLE = 'FFBA68C8'
COLOR_MUTED = 'FFB0BEC5'
PAGED_CATALOG_SECTIONS = frozenset(('friss-epizodok', 'friss-evadok', 'uj-sorozatok'))


def _log(message):
    """Write concise navigation diagnostics to Kodi's standard log."""
    xbmc.log('S365: {}'.format(message), getattr(xbmc, 'LOGINFO', 1))


def tr(message):
    return message


def notify(message, heading='S365'):
    xbmcgui.Dialog().notification(heading, message, xbmcgui.NOTIFICATION_INFO, 6000)


def plugin_url(**params):
    return '{}?{}'.format(BASE_URL, urlencode(params))


def colorize(label, color, bold=True):
    formatted = '[COLOR {}]{}[/COLOR]'.format(color, label)
    return '[B]{}[/B]'.format(formatted) if bold else formatted


def menu_item(label, color, action, **params):
    add_item(colorize(label, color), action, title=label, **params)


def _search_history():
    raw = ADDON.getSetting(HISTORY_SETTING)
    try:
        entries = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        entries = []
    return [entry.strip() for entry in entries if isinstance(entry, str) and entry.strip()]


def _save_search_history(entries):
    ADDON.setSetting(HISTORY_SETTING, json.dumps(entries[:HISTORY_LIMIT], ensure_ascii=False))


def remember_search(query):
    normalized = query.strip()
    if not normalized:
        return
    existing = [entry for entry in _search_history() if entry.casefold() != normalized.casefold()]
    _save_search_history([normalized] + existing)


def _load_records(setting):
    raw = ADDON.getSetting(setting)
    try:
        entries = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        entries = []
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict) and entry.get('url') and entry.get('title')]


def _save_records(setting, entries, limit):
    ADDON.setSetting(setting, json.dumps(entries[:limit], ensure_ascii=False, separators=(',', ':')))


def _recent_episodes():
    return _load_records(RECENT_SETTING)


def _save_recent_episodes(entries):
    _save_records(RECENT_SETTING, entries, RECENT_LIMIT)


def remember_recent_episode(episode_url, title, plot='', thumb=''):
    normalized_title = title.strip() or 'Epizód'
    entries = [entry for entry in _recent_episodes() if entry['url'] != episode_url]
    entries.insert(0, {'url': episode_url, 'title': normalized_title, 'plot': plot, 'thumb': thumb})
    _save_recent_episodes(entries)


def add_item(label, action, folder=True, title=None, plot='', thumb='', label2='', **params):
    url = plugin_url(action=action, **params)
    item = xbmcgui.ListItem(label=label)
    item.setInfo('video', {'title': title or label, 'plot': plot})
    if label2:
        # Label2 is rendered as a subtle secondary field by supported Kodi skins.
        try:
            item.setLabel2(label2)
        except AttributeError:
            pass
    if thumb:
        item.setArt({'thumb': thumb, 'poster': thumb, 'fanart': thumb})
    item.setProperty('IsPlayable', 'false' if folder else 'true')
    xbmcplugin.addDirectoryItem(ADDON_HANDLE, url, item, isFolder=folder)


def add_card(card):
    kind = card.get('kind', 'series')
    action = {'series': 'series', 'season': 'season', 'episode': 'episode'}.get(kind, 'browse')
    label = card['title']
    if card.get('label2'):
        label = '{} — {}'.format(label, card['label2'])
    params = {'url': card['url']}
    if kind == 'episode':
        params.update({'episode_title': card['title'], 'episode_plot': card.get('plot', ''), 'episode_thumb': card.get('thumb', '')})
    # An episode opens a source-selection directory; only an actual source item is playable.
    add_item(label, action, folder=True, title=card['title'], plot=card.get('plot', ''), label2=card.get('label2', ''), thumb=card.get('thumb', ''), **params)


def _source_display(source, occurrences):
    """Return a compact, coloured provider name and factual secondary metadata."""
    raw = (source.get('label') or 'Forrás').strip()
    if ' — ' in raw:
        provider, language = raw.split(' — ', 1)
    elif ' - ' in raw:
        provider, language = raw.split(' - ', 1)
    else:
        provider, language = raw, ''
    provider = provider.strip().upper() or 'FORRÁS'
    occurrences[provider] = occurrences.get(provider, 0) + 1
    if occurrences[provider] > 1:
        provider = '{} ({})'.format(provider, occurrences[provider])
    details = [language.strip()] if language.strip() else []
    details.extend(tag for tag in source.get('tags', []) if tag)
    if source.get('duration'):
        details.append(source['duration'])
    if source.get('bitrate'):
        details.append(source['bitrate'])
    source_color = COLOR_GREEN if source.get('direct') else COLOR_PURPLE if source.get('probed') else COLOR_CYAN
    secondary = ' • '.join(details)
    visible_label = colorize(provider, source_color)
    if secondary:
        visible_label = '{}  {}'.format(visible_label, colorize(secondary, COLOR_MUTED, bold=False))
    return visible_label, secondary


def end(content='videos'):
    xbmcplugin.setContent(ADDON_HANDLE, content)
    xbmcplugin.endOfDirectory(ADDON_HANDLE, updateListing=True, cacheToDisc=False)


def home():
    menu_item('Folytatás', COLOR_CYAN, 'recent')
    menu_item('Kiemelt és felkapott', COLOR_ORANGE, 'browse', url=s365.catalog_base() + '/')
    menu_item('Friss epizódok', COLOR_CYAN, 'browse', url=s365.catalog_base() + '/friss-epizodok')
    menu_item('Friss évadok', COLOR_PURPLE, 'browse', url=s365.catalog_base() + '/friss-evadok')
    menu_item('Új sorozatok', COLOR_GREEN, 'browse', url=s365.catalog_base() + '/uj-sorozatok')
    menu_item('Keresés', COLOR_ORANGE, 'search')
    menu_item('Beállítások', COLOR_MUTED, 'settings')
    end()


def _availability_progress(items, filter_function, item_kind):
    if not items:
        return []
    progress = xbmcgui.DialogProgress()
    progress.create('S365', 'Források ellenőrzése…')
    try:
        def update(index, total, title):
            percent = int(index * 100 / total) if total else 100
            progress.update(percent, '{} ellenőrzése — {} / {}: {}'.format(item_kind, index, total, title))
        return filter_function(items, progress=update, cancelled=progress.iscanceled)
    finally:
        progress.close()


def _catalog_page_parameters(page_url):
    """Return a compact Kodi-safe route for a numbered catalog page, if recognised."""
    parsed = urlparse(page_url)
    path_parts = [part for part in parsed.path.split('/') if part]
    if len(path_parts) != 2:
        return None
    section, number = path_parts
    if section not in PAGED_CATALOG_SECTIONS or not number.isdigit() or int(number) < 2:
        return None
    return section, number


def catalog_page(section, number):
    """Open a numbered catalog page without passing an external URL through Kodi."""
    section = (section or '').strip().strip('/')
    if section not in PAGED_CATALOG_SECTIONS:
        raise s365.S365Error('Érvénytelen katalóguslapozási útvonal.')
    try:
        page_number = int(number)
    except (TypeError, ValueError):
        raise s365.S365Error('Érvénytelen katalógusoldalszám.')
    if page_number < 2:
        raise s365.S365Error('Érvénytelen katalógusoldalszám.')
    target_url = '{}/{}/{}'.format(s365.catalog_base(), section, page_number)
    _log('catalog_page: section={}, number={}, target={}'.format(section, page_number, target_url))
    browse(target_url)


def browse(url):
    _log('browse: url={}'.format(url))
    cards, _metadata, pages = s365.browse(url)
    episode_cards = [card for card in cards if card.get('kind') == 'episode']
    if episode_cards:
        visible_urls = {item['url'] for item in _availability_progress(episode_cards, s365.filter_available_episodes, 'Epizódok')}
        cards = [card for card in cards if card.get('kind') != 'episode' or card['url'] in visible_urls]
    if not cards:
        notify('Nem található elérhető, megjeleníthető katalóguselem.')
    for card in cards:
        add_card(card)
    for page in pages:
        page_parameters = _catalog_page_parameters(page['url'])
        if page_parameters:
            section, number = page_parameters
            # Do not put a full external URL in the plugin query string. Kodi receives
            # a unique, compact route and catalog_page() reconstructs the exact target.
            menu_item(page.get('label', 'Következő oldal'), COLOR_ORANGE, 'catalog_page', section=section, number=number)
        else:
            menu_item(page.get('label', 'Következő oldal'), COLOR_ORANGE, 'browse', url=page['url'])
    end('videos')


def series(url):
    seasons, metadata = s365.series_seasons(url)
    if seasons:
        seasons = _availability_progress(seasons, s365.filter_available_seasons, 'Évadok')
    if not seasons:
        notify('Ehhez a sorozathoz jelenleg nincs elérhető évad.')
    for season in seasons:
        number = season.get('button', '')
        label = '{}. évad'.format(number) if number.isdigit() else season['title']
        add_item(label, 'season', title=season['title'], plot=metadata.get('plot', ''), thumb=metadata.get('thumb', ''), url=season['url'])
    end('tvshows')


def season(url):
    episodes, metadata = s365.season_episodes(url)
    if episodes:
        episodes = _availability_progress(episodes, s365.filter_available_episodes, 'Epizódok')
    if not episodes:
        notify('Ehhez az évadhoz jelenleg nincs elérhető epizód.')
    for episode_item in episodes:
        number = episode_item.get('button', '')
        label = '{}. rész'.format(number) if number.isdigit() else episode_item['title']
        # The episode must be a folder so Kodi renders the Linkek megtekintése source list.
        add_item(label, 'episode', folder=True, title=episode_item['title'], plot=metadata.get('plot', ''), thumb=metadata.get('thumb', ''), url=episode_item['url'], episode_title=episode_item['title'], episode_plot=metadata.get('plot', ''), episode_thumb=metadata.get('thumb', ''))
    end('episodes')


def show_search_results(query):
    cards = s365.search(query)
    if not cards:
        notify('Nincs találat: {}'.format(query))
    for card in cards:
        add_card(card)
    end('tvshows')


def search_menu():
    menu_item('Új keresés', COLOR_ORANGE, 'new_search')
    entries = _search_history()
    if entries:
        menu_item('Előzmények törlése', COLOR_MUTED, 'clear_history')
        for query in entries:
            add_item(colorize(query, COLOR_CYAN, bold=False), 'saved_search', title=query, label2='Korábbi keresés', query=query)
    end('tvshows')


def do_search():
    query = xbmcgui.Dialog().input('Keresés az S365 katalógusában', type=xbmcgui.INPUT_ALPHANUM)
    if not query:
        return
    remember_search(query)
    show_search_results(query)


def clear_history():
    _save_search_history([])
    notify('A keresési előzmények törölve lettek.')
    search_menu()


def recent():
    entries = _recent_episodes()
    if not entries:
        notify('Még nincs megnyitott epizód.')
        end('episodes')
        return
    menu_item('Folytatás törlése', COLOR_MUTED, 'clear_recent')
    for entry in entries:
        add_item(colorize(entry['title'], COLOR_CYAN, bold=False), 'episode', title=entry['title'], plot=entry.get('plot', ''), thumb=entry.get('thumb', ''), label2='Legutóbb megnyitott', url=entry['url'], episode_title=entry['title'], episode_plot=entry.get('plot', ''), episode_thumb=entry.get('thumb', ''))
    end('episodes')


def clear_recent():
    _save_recent_episodes([])
    notify('A Folytatás lista törölve lett.')
    recent()


def render_sources(sources, metadata):
    if not sources:
        notify('A „Linkek megtekintése” oldalon most nincs lejátszható forrás.')
        end()
        return
    occurrences = {}
    for source in sources:
        label, label2 = _source_display(source, occurrences)
        add_item(
            label,
            'play',
            folder=False,
            title=metadata.get('title', label),
            plot=metadata.get('plot', ''),
            thumb=metadata.get('thumb', ''),
            label2=label2,
            stream=source['url'],
            referer=source.get('referer', ''),
            headers=urlencode(source.get('headers', {})),
            direct='1' if source.get('direct') else '0',
        )
    end('videos')


def episode(url, episode_title='', episode_plot='', episode_thumb=''):
    sources, metadata = s365.sources_for_episode(url)
    remember_recent_episode(url, episode_title or metadata.get('title', ''), episode_plot or metadata.get('plot', ''), episode_thumb or metadata.get('thumb', ''))
    render_sources(sources, metadata)


def play(stream, referer='', headers='', direct='0'):
    playback_url = stream if direct == '1' else s365.resolve_with_resolveurl(stream, referer)
    if headers and '|' not in playback_url:
        playback_url = '{}|{}'.format(playback_url, headers)
    listitem = xbmcgui.ListItem(path=playback_url)
    listitem.setProperty('IsPlayable', 'true')
    xbmcplugin.setResolvedUrl(ADDON_HANDLE, True, listitem)


def open_settings():
    ADDON.openSettings()


def run():
    raw = sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith('?') else ''
    params = {key: values[0] for key, values in parse_qs(raw).items()}
    action = params.get('action', 'home')
    _log('dispatch: raw={}, action={}, params={}'.format(raw, action, params))
    try:
        if action == 'browse':
            browse(params['url'])
        elif action == 'catalog_page':
            catalog_page(params['section'], params['number'])
        elif action == 'search':
            search_menu()
        elif action == 'new_search':
            do_search()
        elif action == 'saved_search':
            show_search_results(params['query'])
        elif action == 'clear_history':
            clear_history()
        elif action == 'recent':
            recent()
        elif action == 'clear_recent':
            clear_recent()
        elif action == 'series':
            series(params['url'])
        elif action == 'season':
            season(params['url'])
        elif action == 'episode':
            episode(params['url'], params.get('episode_title', ''), params.get('episode_plot', ''), params.get('episode_thumb', ''))
        elif action == 'play':
            play(params['stream'], params.get('referer', ''), params.get('headers', ''), params.get('direct', '0'))
        elif action == 'settings':
            open_settings()
        else:
            home()
    except s365.S365Error as exc:
        xbmcgui.Dialog().ok('S365', str(exc))
        xbmcplugin.endOfDirectory(ADDON_HANDLE, succeeded=False, cacheToDisc=False)
    except Exception as exc:
        xbmc.log('S365 add-on error: {}'.format(exc), xbmc.LOGERROR)
        xbmcgui.Dialog().ok('S365', 'Váratlan hiba történt. Részletek a Kodi naplóban.\n\n{}'.format(exc))
        xbmcplugin.endOfDirectory(ADDON_HANDLE, succeeded=False, cacheToDisc=False)
