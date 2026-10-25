# -*- coding: utf-8 -*-
"""Kodi plugin: browse public MoziPont metadata and optional labeled YouTube trailers."""
import sys
import re
from urllib.parse import urlencode, parse_qs, urlparse

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin

try:
    import resolveurl
    HAS_RESOLVEURL = True
except ImportError:
    HAS_RESOLVEURL = False

import catalog

ADDON = xbmcaddon.Addon()
PLUGIN_URL = sys.argv[0]
HANDLE = int(sys.argv[1])

def log_debug(msg):
    xbmc.log(f"[MoziPont DEBUG] {msg}", xbmc.LOGINFO)

def plugin_url(**params):
    return PLUGIN_URL + '?' + urlencode(params)

def finish(content='files'):
    xbmcplugin.setContent(HANDLE, content)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=True, cacheToDisc=False)

def make_item(label, params=None, folder=True, poster='', plot='', info=None):
    item = xbmcgui.ListItem(label=label)
    item.setProperty('IsPlayable', 'false' if folder else 'true')
    art = {'thumb': poster, 'poster': poster}
    if poster: art['fanart'] = poster
    item.setArt(art)
    if plot:
        details = dict(info or {})
        details.setdefault('plot', plot)
        details.setdefault('title', label)
        item.setInfo('video', details)
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=plugin_url(**(params or {})), listitem=item, isFolder=folder)

def show_root():
    xbmcplugin.setPluginCategory(HANDLE, 'MoziPont katalógus')
    make_item('Filmek', {'action': 'list', 'kind': 'films', 'page': 1})
    make_item('Sorozatok', {'action': 'list', 'kind': 'series', 'page': 1})
    make_item('Film Műfajok', {'action': 'genres', 'kind': 'films'})
    make_item('Sorozat Műfajok', {'action': 'genres', 'kind': 'series'})
    make_item('Keresés…', {'action': 'search'})
    finish('videos')

def prompt_search():
    keyboard = xbmc.Keyboard('', 'Keresés a MoziPont katalógusában')
    keyboard.doModal()
    if not keyboard.isConfirmed():
        finish('videos'); return
    query = keyboard.getText().strip()
    if not query:
        finish('videos'); return
    show_listing('search', 1, query)

def show_genres(kind):
    try:
        genres = catalog.get_genres(kind)
        category = 'Film Műfajok' if kind == 'films' else 'Sorozat Műfajok'
        xbmcplugin.setPluginCategory(HANDLE, category)
        xbmcplugin.setContent(HANDLE, 'videos')
        for genre in genres:
            make_item(genre['name'], {'action': 'list', 'kind': kind, 'page': 1, 'mufaj': genre['value']}, folder=True)
        finish('videos')
    except Exception as exc:
        log_debug(f"Genres error: {repr(exc)}")
        xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Hiba a műfajok betöltésekor.', xbmcgui.NOTIFICATION_ERROR, 5000)
        finish('videos')

def show_listing(kind, page, query='', mufaj=''):
    if kind not in ('films', 'series', 'search'):
        finish('videos'); return
    try:
        page = max(1, min(500, int(page)))
        if kind == 'films':
            path = '/filmek'
            args = {'oldal': page} if page > 1 else {}
            if mufaj: args['mufaj'] = mufaj
            category = 'Filmek' + (f" - {mufaj}" if mufaj else "")
        elif kind == 'series':
            path = '/sorozatok'
            args = {'oldal': page} if page > 1 else {}
            if mufaj: args['mufaj'] = mufaj
            category = 'Sorozatok' + (f" - {mufaj}" if mufaj else "")
        else:
            path = '/kereses'
            args = {'q': query[:120]}
            category = 'Keresés: ' + query[:80]
            
        html = catalog.fetch(path, args)
        entries = catalog.parse_listing(html)
        xbmcplugin.setPluginCategory(HANDLE, category)
        xbmcplugin.setContent(HANDLE, 'movies' if kind == 'films' else ('tvshows' if kind == 'series' else 'videos'))
        
        # Az első film ID-jának mentése a "Teljes leírás" gombhoz
        first_entry_id = entries[0]['id'] if entries else None
        
        for entry in entries:
            detail_kind = entry['kind']
            label = entry['title']
            
            # TELJES LEÍRÁS ÉS MŰFAJ LEKÉRÉSE AZ API-RÓL
            media_info = catalog.get_media_info(entry['id'])
            
            plot_parts = []
            if entry.get('label'): plot_parts.append(f"[COLOR yellow][B]{entry['label']}[/B][/COLOR]")
            if entry.get('year_type'): plot_parts.append(entry['year_type'])
            if media_info.get('genres'): plot_parts.append(f"Műfaj: {media_info['genres']}")
            if media_info.get('duration'): plot_parts.append(f"Hossz: {media_info['duration']}")
            if entry.get('age'): plot_parts.append(f"Korhatár: {entry['age']}")
            if entry.get('rating'): plot_parts.append(f"Értékelés: {entry['rating']}")
            if entry.get('hd'): plot_parts.append("[COLOR lime]HD felbontás[/COLOR]")
            if entry.get('tags'): plot_parts.append("[B]" + " · ".join(entry['tags']) + "[/B]")
            plot_parts.append("")  # Üres sor
            
            # LEÍRÁS RÖVIDÍTÉSE A LISTÁBAN (max 150 karakter)
            full_description = media_info.get('description', '')
            if len(full_description) > 150:
                short_description = full_description[:150].rsplit(' ', 1)[0] + "..."
            else:
                short_description = full_description
            
            if short_description:
                plot_parts.append(short_description)
            else:
                plot_parts.append("Kattints az adatlap megnyitásához és a lejátszási forrásokért.")
            
            plot_text = '\n'.join(plot_parts)
            
            item_info = {'title': label, 'mediatype': 'movie' if detail_kind == 'film' else 'tvshow'}
            make_item(label, {'action': 'detail', 'kind': detail_kind, 'id': entry['id']}, folder=True, poster=entry.get('poster', ''), plot=plot_text, info=item_info)
            
        # "TELJES LEÍRÁS" GOMB HOZZÁADÁSA A LISTA VÉGÉN
        if first_entry_id:
            first_media_info = catalog.get_media_info(first_entry_id)
            full_desc = first_media_info.get('description', 'Nincs elérhető leírás.')
            make_item(
                label='[COLOR cyan][B] Teljes leírás megtekintése[/B][/COLOR]',
                params={'action': 'view_full_description', 'title': entries[0]['title'], 'description': full_desc},
                folder=False,
                poster=entries[0].get('poster', ''),
                plot=full_desc
            )
            
        if kind != 'search' and 'Következő' in html and entries:
            make_item('Következő oldal  →', {'action': 'list', 'kind': kind, 'page': page + 1, 'mufaj': mufaj})
        if not entries:
            xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Nem található katalóguselem.', xbmcgui.NOTIFICATION_INFO, 4000)
        finish('videos')
    except Exception as exc:
        log_debug(f"Listing error: {repr(exc)}")
        xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Hiba a katalógus betöltésekor.', xbmcgui.NOTIFICATION_ERROR, 5000)
        finish('videos')

def show_detail(kind, content_id):
    if kind not in ('film', 'sorozat') or not str(content_id).isdigit():
        finish('videos'); return
    try:
        html = catalog.fetch('/' + kind + '/' + str(int(content_id)))
        data = catalog.parse_detail(html, kind, content_id)
        title, poster = data['title'], data.get('poster', '')
        
        plot_lines = []
        if data.get('year'): plot_lines.append(f"Év: {data['year']}")
        if data.get('genre'): plot_lines.append(f"Műfaj: {data['genre']}")
        if data.get('duration'): plot_lines.append(f"Hossz: {data['duration']} perc")
        if data.get('tags'): plot_lines.append("[B]" + " · ".join(data['tags']) + "[/B]")
        plot_lines.append("")
        plot_lines.append(data.get('description') or 'Nincs elérhető leírás.')
        plot_text = '\n'.join(plot_lines)
        
        xbmcplugin.setPluginCategory(HANDLE, title)
        xbmcplugin.setContent(HANDLE, 'videos')

        # --- SOROZATOK KEZELÉSE ---
        if kind == 'sorozat':
            seasons = catalog.get_series_seasons(content_id)
            if not seasons:
                xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Nem találhatók évadok.', xbmcgui.NOTIFICATION_INFO, 4000)
                finish('videos'); return
            
            for s in seasons:
                make_item(
                    label=f"[COLOR cyan][B]{s['label']}[/B][/COLOR] ({s['count']} rész)",
                    params={'action': 'list_episodes', 'series_id': content_id, 'season': s['season'], 'series_title': title},
                    folder=True,
                    poster=poster,
                    plot=plot_text
                )
            finish('videos')
            return

        # --- FILMEK KEZELÉSE ---
        result = catalog.get_sources(content_id)
        sources = result.get('sources', [])
        unavailable_msg = result.get('unavailable_msg', '')
        
        # FONTOS: Előzetes hozzáadása a sources listához!
        if data.get('trailer_id'):
            sources.append({'name': 'YouTube', 'url': data['trailer_id'], 'is_trailer': True})
        
        if unavailable_msg and len(sources) == 0:
            make_item('[COLOR red][B]NEM ELÉRHETŐ[/B][/COLOR]', {'action': 'info', 'title': title, 'description': unavailable_msg}, folder=False, poster=poster, plot=unavailable_msg)
            finish('videos'); return
            
        # HA CSAK EGY FORRÁS VAN ÉS AZ NEM ELŐZETES -> AUTOMATIKUS LEJÁTSZÁS
        if len(sources) == 1 and not sources[0].get('is_trailer'):
            src = sources[0]
            resolved_url = src['url']
            
            if HAS_RESOLVEURL:
                try:
                    resolved = resolveurl.resolve(src['url'])
                    if resolved:
                        resolved_url = resolved
                        host_name = urlparse(resolved_url).netloc.replace('www.', '').split(':')[0]
                        log_debug(f"Sikeres feloldás: {resolved_url} (Host: {host_name})")
                        xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), f'Automatikus indítás: {host_name}', xbmcgui.NOTIFICATION_INFO, 3000)
                except Exception as e:
                    log_debug(f"ResolveURL hiba: {repr(e)}")
            
            log_debug(f"Automatikus lejátszás indítása: {resolved_url}")
            xbmc.executebuiltin('PlayMedia(' + resolved_url + ')')
            sys.exit()
            
        # HA NINCS FORRÁS (de esetleg van előzetes)
        if len(sources) == 0:
            make_item('[COLOR yellow][B]NINCS ELÉRHETŐ FORRÁS[/B][/COLOR]', {'action': 'info', 'title': title, 'description': 'Nem találtunk beágyazott videót.'}, folder=False, poster=poster, plot='Nem találtunk beágyazott videót.')
            finish('videos'); return
            
        # HA VAN ELŐZETES VAGY TÖBB FORRÁS -> LISTÁZÁS
        for src in sources:
            if src.get('is_trailer'):
                make_item('[COLOR yellow][B]> Előzetes[/B][/COLOR]', {'action': 'play_trailer', 'url': src['url'], 'title': title}, folder=False, poster=poster, plot=plot_text)
            else:
                make_item(f'[COLOR lime][B]> LEJÁTSZÁS[/B][/COLOR] - [I][COLOR orange]{src["name"]}[/COLOR][/I]', {'action': 'play', 'url': src['url'], 'title': title}, folder=False, poster=poster, plot=plot_text)
        
        finish('videos')
    except Exception as exc:
        log_debug(f"Detail error: {repr(exc)}")
        xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Az adatlap most nem érhető el.', xbmcgui.NOTIFICATION_ERROR, 5000)
        finish('videos')

def play_episode(series_id, season, ep_title, series_title, href):
    log_debug(f"Epizód lejátszása: {href}")
    watch_url = catalog.BASE + href
    referer = catalog.BASE + f'/sorozat/{series_id}/reszek/{season}'
    
    sources = catalog.get_sources_from_url(watch_url, referer=referer)
    if not sources:
        xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Nincs elérhető forrás ehhez a részhez.', xbmcgui.NOTIFICATION_ERROR, 5000)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
        
    src = sources[0]
    resolved_url = src['url']
    host_name = "Ismeretlen"
    
    if HAS_RESOLVEURL:
        try:
            resolved = resolveurl.resolve(src['url'])
            if resolved:
                resolved_url = resolved
                host_name = urlparse(resolved_url).netloc.replace('www.', '').split(':')[0]
                log_debug(f"Sikeres feloldás: {resolved_url} (Host: {host_name})")
                xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), f'Feloldva: {host_name}', xbmcgui.NOTIFICATION_INFO, 3000)
        except Exception as e:
            log_debug(f"ResolveURL hiba: {repr(e)}")
            
    item = xbmcgui.ListItem(path=resolved_url)
    item.setInfo('video', {'title': ep_title})
    xbmcplugin.setResolvedUrl(HANDLE, True, item)

def play_embedded_video(url, title):
    log_debug(f"Lejátszás kísérlete: {url}")
    resolved_url, host_name = url, ""
    if HAS_RESOLVEURL:
        try:
            resolved = resolveurl.resolve(url)
            if resolved:
                resolved_url = resolved
                host_name = urlparse(resolved_url).netloc.replace('www.', '').split(':')[0]
                log_debug(f"Sikeres feloldás: {resolved_url} (Host: {host_name})")
                xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), f'Feloldva: {host_name}', xbmcgui.NOTIFICATION_INFO, 3000)
        except Exception as e:
            log_debug(f"ResolveURL hiba: {repr(e)}")
    
    item = xbmcgui.ListItem(path=resolved_url)
    item.setInfo('video', {'title': title})
    xbmcplugin.setResolvedUrl(HANDLE, True, item)

def show_episodes(series_id, season, series_title):
    try:
        html = catalog.fetch(f'/sorozat/{series_id}')
        data = catalog.parse_detail(html, 'sorozat', series_id)
        poster = data.get('poster', '')
        
        plot_lines = [f"{series_title} - {season}. évad"]
        if data.get('description'): plot_lines.append(data.get('description'))
        plot_text = '\n'.join(plot_lines)
        
        episodes = catalog.get_episodes_for_season(series_id, season)
        if not episodes:
            xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Nem találhatók részek ebben az évadban.', xbmcgui.NOTIFICATION_INFO, 4000)
            finish('videos'); return
            
        for ep in episodes:
            make_item(
                label=f"[COLOR lime][B]▶ {ep['title']}[/B][/COLOR]",
                params={'action': 'play_episode', 'series_id': series_id, 'season': season, 'ep_title': ep['title'], 'series_title': series_title, 'href': ep['href']},
                folder=False,
                poster=poster,
                plot=plot_text
            )
        finish('videos')
    except Exception as exc:
        log_debug(f"Episodes error: {repr(exc)}")
        xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Hiba az évad betöltésekor.', xbmcgui.NOTIFICATION_ERROR, 5000)
        finish('videos')

def main():
    raw = sys.argv[2][1:] if len(sys.argv) > 2 and sys.argv[2].startswith('?') else ''
    args = parse_qs(raw, keep_blank_values=True)
    action = args.get('action', [''])[0]
    
    if not action: show_root()
    elif action == 'search': prompt_search()
    elif action == 'genres': show_genres(args.get('kind', [''])[0])
    elif action == 'list': show_listing(args.get('kind', [''])[0], args.get('page', ['1'])[0], mufaj=args.get('mufaj', [''])[0])
    elif action == 'detail': show_detail(args.get('kind', [''])[0], args.get('id', [''])[0])
    elif action == 'list_episodes': show_episodes(args.get('series_id', [''])[0], args.get('season', [''])[0], args.get('series_title', [''])[0])
    elif action == 'play_episode': play_episode(args.get('series_id', [''])[0], args.get('season', [''])[0], args.get('ep_title', [''])[0], args.get('series_title', [''])[0], args.get('href', [''])[0])
    elif action == 'play': play_embedded_video(args.get('url', [''])[0], args.get('title', [''])[0])
    elif action == 'play_trailer':
        video_id = args.get('url', [''])[0]
        if not xbmc.getCondVisibility('System.HasAddon(plugin.video.youtube)'):
            xbmcgui.Dialog().notification(ADDON.getAddonInfo('name'), 'Telepítsd a hivatalos YouTube kiegészítőt.', xbmcgui.NOTIFICATION_INFO, 6000)
        else:
            xbmcplugin.setResolvedUrl(HANDLE, True, xbmcgui.ListItem(path='plugin://plugin.video.youtube/play/?video_id=' + video_id))
    elif action == 'view_full_description':
        title = args.get('title', [''])[0]
        description = args.get('description', [''])[0] or 'Nincs elérhető leírás.'
        xbmcgui.Dialog().textviewer(title, description)
        finish('videos')
    elif action == 'info':
        xbmcgui.Dialog().textviewer(args.get('title', [''])[0], args.get('description', [''])[0] or 'Nincs leírás.')
        finish('videos')
    else: finish('videos')

if __name__ == '__main__':
    main()