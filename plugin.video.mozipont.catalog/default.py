# -*- coding: utf-8 -*-
"""Kodi entry point for the MoziPont catalog add-on."""
import sys
from urllib.parse import parse_qs, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

try:
    import resolveurl
except ImportError:
    resolveurl = None

import catalog

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo('name')
PLUGIN_URL = sys.argv[0]
HANDLE = int(sys.argv[1])


def _log(message):
    xbmc.log('[MoziPont] ' + str(message), xbmc.LOGINFO)


def _url(**params):
    return PLUGIN_URL + '?' + urlencode(params)


def _finish(content='videos', cache=False):
    xbmcplugin.setContent(HANDLE, content)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=True, cacheToDisc=cache)


def _notify(message, error=False, duration=4500):
    level = xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_INFO
    xbmcgui.Dialog().notification(ADDON_NAME, message, level, duration)


def _add_item(label, params, *, folder=True, poster='', plot='', info=None):
    item = xbmcgui.ListItem(label=label)
    item.setProperty('IsPlayable', 'false' if folder else 'true')
    if poster:
        item.setArt({'thumb': poster, 'poster': poster, 'fanart': poster})
    if plot or info:
        details = dict(info or {})
        details.setdefault('title', label)
        if plot:
            details['plot'] = plot
        item.setInfo('video', details)
    xbmcplugin.addDirectoryItem(
        handle=HANDLE,
        url=_url(**(params or {})),
        listitem=item,
        isFolder=folder,
    )


def show_root():
    xbmcplugin.setPluginCategory(HANDLE, 'MoziPont katalógus')
    _add_item('Filmek', {'action': 'list', 'kind': 'films', 'page': 1})
    _add_item('Sorozatok', {'action': 'list', 'kind': 'series', 'page': 1})
    _add_item('Film műfajok', {'action': 'genres', 'kind': 'films'})
    _add_item('Sorozat műfajok', {'action': 'genres', 'kind': 'series'})
    _add_item('Keresés…', {'action': 'search'})
    _finish('videos', cache=True)


def prompt_search():
    keyboard = xbmc.Keyboard('', 'Keresés a MoziPont katalógusában')
    keyboard.doModal()
    if not keyboard.isConfirmed():
        _finish('videos')
        return
    query = keyboard.getText().strip()
    if not query:
        _finish('videos')
        return
    show_listing('search', 1, query=query)


def show_genres(kind):
    try:
        genres = catalog.get_genres(kind)
        category = 'Film műfajok' if kind == 'films' else 'Sorozat műfajok'
        xbmcplugin.setPluginCategory(HANDLE, category)
        for genre in genres:
            _add_item(genre['name'], {
                'action': 'list', 'kind': kind, 'page': 1,
                'mufaj': genre['value'],
            })
        if not genres:
            _notify('Nem találhatók műfajok.')
        _finish('videos', cache=True)
    except Exception as exc:
        _log('Genre listing failed: ' + repr(exc))
        _notify('Hiba a műfajok betöltésekor.', error=True)
        _finish('videos')


def _genres_text(raw_genres):
    if isinstance(raw_genres, list):
        return ' · '.join(
            genre.get('name', '') for genre in raw_genres
            if isinstance(genre, dict) and genre.get('name')
        )
    if isinstance(raw_genres, str):
        return raw_genres
    return ''


def _listing_plot(entry, media):
    parts = []
    if entry.get('label'):
        parts.append('[COLOR yellow][B]' + entry['label'] + '[/B][/COLOR]')
    if entry.get('year_type'):
        parts.append(entry['year_type'])
    genres = _genres_text(media.get('genres'))
    if genres:
        parts.append('Műfaj: ' + genres)
    if media.get('duration'):
        parts.append('Hossz: ' + str(media['duration']))
    if entry.get('age') or media.get('age'):
        parts.append('Korhatár: ' + str(entry.get('age') or media.get('age')))
    if entry.get('rating') or media.get('rating'):
        parts.append('★ ' + str(entry.get('rating') or media.get('rating')))
    if entry.get('hd') or media.get('hd'):
        parts.append('[COLOR lime]HD felbontás[/COLOR]')
    if entry.get('tags'):
        parts.append('[B]' + ' · '.join(entry['tags']) + '[/B]')
    description = (media.get('description') or '').strip()
    if len(description) > 180:
        description = description[:180].rsplit(' ', 1)[0] + '…'
    if description:
        parts.extend(['', description])
    else:
        parts.extend(['', 'Kattints a részletekért.'])
    return '\n'.join(parts)


def show_listing(kind, page, query='', mufaj=''):
    if kind not in ('films', 'series', 'search'):
        _finish('videos')
        return
    try:
        page = max(1, min(500, int(page)))
        if kind == 'films':
            path = '/filmek'
            params = {'oldal': page} if page > 1 else {}
            if mufaj:
                params['mufaj'] = mufaj
            category = 'Filmek' + (' – ' + mufaj if mufaj else '')
            content = 'movies'
        elif kind == 'series':
            path = '/sorozatok'
            params = {'oldal': page} if page > 1 else {}
            if mufaj:
                params['mufaj'] = mufaj
            category = 'Sorozatok' + (' – ' + mufaj if mufaj else '')
            content = 'tvshows'
        else:
            path = '/kereses'
            params = {'q': query[:120]}
            category = 'Keresés: ' + query[:80]
            content = 'videos'

        markup = catalog.fetch(path, params)
        entries = catalog.parse_listing(markup)
        xbmcplugin.setPluginCategory(HANDLE, category)
        xbmcplugin.setContent(HANDLE, content)

        # Parallel first-time lookups; future listing loads use the on-disk API cache.
        media_infos = catalog.get_media_infos([entry['id'] for entry in entries])
        for entry, media in zip(entries, media_infos):
            title = entry.get('title') or 'Ismeretlen cím'
            kind_for_item = entry.get('kind', 'film')
            is_movie = kind_for_item == 'film'
            item_info = {
                'title': title,
                'mediatype': 'movie' if is_movie else 'tvshow',
            }
            if media.get('year'):
                item_info['year'] = media['year']
            poster = entry.get('poster', '')
            plot = _listing_plot(entry, media)

            # An API-confirmed movie without a trailer is a playable item, not a
            # folder that auto-runs PlayMedia. Kodi resolves it once and returns
            # to this cached directory when playback stops.
            if is_movie and media.get('ok') and not media.get('trailer'):
                item_params = {'action': 'play_movie', 'id': entry['id'], 'title': title}
                folder = False
            else:
                item_params = {'action': 'detail', 'kind': kind_for_item, 'id': entry['id']}
                folder = True
            _add_item(title, item_params, folder=folder, poster=poster,
                      plot=plot, info=item_info)

        if kind != 'search' and 'Következő' in markup and entries:
            _add_item('Következő oldal  →', {
                'action': 'list', 'kind': kind, 'page': page + 1,
                'mufaj': mufaj,
            })
        if not entries:
            _notify('Nem található katalóguselem.')
        _finish(content, cache=True)
    except Exception as exc:
        _log('Listing failed: ' + repr(exc))
        _notify('Hiba a katalógus betöltésekor.', error=True)
        _finish('videos')


def show_detail(kind, content_id):
    if kind not in ('film', 'sorozat') or not str(content_id).isdigit():
        _finish('videos')
        return
    try:
        markup = catalog.fetch('/' + kind + '/' + str(int(content_id)))
        data = catalog.parse_detail(markup, kind, content_id)
        title = data['title']
        poster = data.get('poster', '')
        plot_lines = []
        if data.get('year'):
            plot_lines.append('Év: ' + str(data['year']))
        if data.get('genre'):
            plot_lines.append('Műfaj: ' + data['genre'])
        if data.get('duration'):
            plot_lines.append('Hossz: ' + data['duration'])
        if data.get('tags'):
            plot_lines.append(' · '.join(data['tags']))
        if plot_lines:
            plot_lines.append('')
        plot_lines.append(data.get('description') or 'Nincs elérhető leírás.')
        plot = '\n'.join(plot_lines)
        xbmcplugin.setPluginCategory(HANDLE, title)
        xbmcplugin.setContent(HANDLE, 'videos')

        if kind == 'sorozat':
            seasons = catalog.get_series_seasons(content_id)
            for season in seasons:
                _add_item(
                    '[COLOR cyan][B]' + season['label'] + '[/B][/COLOR] (' + str(season['count']) + ' rész)',
                    {'action': 'episodes', 'series_id': content_id,
                     'season': season['season'], 'series_title': title},
                    folder=True, poster=poster, plot=plot,
                )
            if not seasons:
                _notify('Nem találhatók évadok.')
            _finish('videos', cache=True)
            return

        trailer_id = data.get('trailer_id', '')
        if not trailer_id:
            api = catalog.get_media_info(content_id)
            trailer_id = api.get('trailer', '') if api.get('ok') else ''
        result = catalog.get_sources(content_id)
        sources = result.get('sources', [])
        if result.get('unavailable_msg') and not sources:
            _add_item('[COLOR red][B]NEM ELÉRHETŐ[/B][/COLOR]',
                      {'action': 'info', 'title': title,
                       'description': result['unavailable_msg']},
                      folder=False, poster=poster, plot=result['unavailable_msg'])
        else:
            if not sources:
                _add_item('[COLOR yellow][B]NINCS ELÉRHETŐ FORRÁS[/B][/COLOR]',
                          {'action': 'info', 'title': title,
                           'description': 'Nem találtunk elérhető videóforrást.'},
                          folder=False, poster=poster,
                          plot='Nem találtunk elérhető videóforrást.')
            for source in sources:
                _add_item(
                    '[COLOR lime][B]▶ LEJÁTSZÁS[/B][/COLOR] – [I][COLOR orange]' + source['name'] + '[/COLOR][/I]',
                    {'action': 'play', 'url': source['url'], 'title': title},
                    folder=False, poster=poster, plot=plot,
                )
        if trailer_id:
            _add_item('[COLOR yellow][B]▶ Előzetes[/B][/COLOR]',
                      {'action': 'play_trailer', 'url': trailer_id, 'title': title},
                      folder=False, poster=poster, plot=plot)
        _finish('videos', cache=True)
    except Exception as exc:
        _log('Detail failed: ' + repr(exc))
        _notify('Az adatlap most nem érhető el.', error=True)
        _finish('videos')


def _play_resolved(url, title):
    resolved_url = url
    if resolveurl is not None:
        try:
            resolved = resolveurl.resolve(url)
            if resolved:
                resolved_url = resolved
        except Exception as exc:
            _log('ResolveURL failed: ' + repr(exc))
    item = xbmcgui.ListItem(path=resolved_url)
    item.setInfo('video', {'title': title})
    xbmcplugin.setResolvedUrl(HANDLE, True, item)


def play_movie(content_id, title):
    if not str(content_id).isdigit():
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    try:
        result = catalog.get_sources(content_id)
        sources = result.get('sources', [])
        if not sources:
            _notify(result.get('unavailable_msg') or 'Nem található elérhető lejátszási forrás.', error=True)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        _play_resolved(sources[0]['url'], title)
    except Exception as exc:
        _log('Movie playback failed: ' + repr(exc))
        _notify('A film lejátszása most nem indítható.', error=True)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def play_episode(series_id, season, title, series_title, href):
    try:
        if not href.startswith('/nezes/'):
            raise ValueError('Invalid episode player path')
        watch_url = catalog.BASE + href
        referer = catalog.BASE + '/sorozat/' + str(series_id) + '/reszek/' + str(season)
        sources = catalog.get_sources_from_url(watch_url, referer=referer)
        if not sources:
            _notify('Nincs elérhető forrás ehhez a részhez.', error=True)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        _play_resolved(sources[0]['url'], title or series_title)
    except Exception as exc:
        _log('Episode playback failed: ' + repr(exc))
        _notify('A rész lejátszása most nem indítható.', error=True)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def show_episodes(series_id, season, series_title):
    try:
        markup = catalog.fetch('/sorozat/' + str(int(series_id)))
        data = catalog.parse_detail(markup, 'sorozat', series_id)
        episodes = catalog.get_episodes_for_season(series_id, season)
        xbmcplugin.setPluginCategory(HANDLE, series_title + ' – ' + str(season) + '. évad')
        xbmcplugin.setContent(HANDLE, 'episodes')
        plot = series_title + ' – ' + str(season) + '. évad'
        if data.get('description'):
            plot += '\n\n' + data['description']
        for episode in episodes:
            _add_item(
                '[COLOR lime][B]▶ ' + episode['title'] + '[/B][/COLOR]',
                {'action': 'play_episode', 'series_id': series_id,
                 'season': season, 'title': episode['title'],
                 'series_title': series_title, 'href': episode['href']},
                folder=False, poster=data.get('poster', ''), plot=plot,
                info={'title': episode['title'], 'mediatype': 'episode'},
            )
        if not episodes:
            _notify('Nem találhatók részek ebben az évadban.')
        _finish('episodes', cache=True)
    except Exception as exc:
        _log('Episode listing failed: ' + repr(exc))
        _notify('Hiba az évad betöltésekor.', error=True)
        _finish('videos')


def main():
    raw = sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith('?') else ''
    args = parse_qs(raw, keep_blank_values=True)
    action = args.get('action', [''])[0]
    if not action:
        show_root()
    elif action == 'search':
        prompt_search()
    elif action == 'genres':
        show_genres(args.get('kind', [''])[0])
    elif action == 'list':
        show_listing(args.get('kind', [''])[0], args.get('page', ['1'])[0],
                     mufaj=args.get('mufaj', [''])[0])
    elif action == 'detail':
        show_detail(args.get('kind', [''])[0], args.get('id', [''])[0])
    elif action == 'episodes':
        show_episodes(args.get('series_id', [''])[0], args.get('season', [''])[0],
                      args.get('series_title', [''])[0])
    elif action == 'play_movie':
        play_movie(args.get('id', [''])[0], args.get('title', [''])[0])
    elif action == 'play_episode':
        play_episode(args.get('series_id', [''])[0], args.get('season', [''])[0],
                     args.get('title', [''])[0], args.get('series_title', [''])[0],
                     args.get('href', [''])[0])
    elif action == 'play':
        _play_resolved(args.get('url', [''])[0], args.get('title', [''])[0])
    elif action == 'play_trailer':
        video_id = args.get('url', [''])[0]
        if not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
            _notify('Telepítsd a hivatalos YouTube kiegészítőt.')
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        else:
            url = 'plugin://plugin.video.youtube/play/?video_id=' + video_id
            xbmcplugin.setResolvedUrl(HANDLE, True, xbmcgui.ListItem(path=url))
    elif action == 'info':
        xbmcgui.Dialog().textviewer(args.get('title', [''])[0],
                                    args.get('description', [''])[0] or 'Nincs leírás.')
        _finish('videos')
    else:
        _finish('videos')


if __name__ == '__main__':
    main()
