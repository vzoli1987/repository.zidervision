# -*- coding: utf-8 -*-
"""Host search and playback built on the pluggable source adapters.

The adapter layer (resources/lib/adapters), net.py and aggregator.py come from
plugin.video.mozipremierek; the functions below are lifted from its default.py
so a Mafab.hu movie is looked up by title on the same sources and played the
same way (ZiderVision/ResolveURL resolvers, per-row hand-off to other add-ons).
"""
from __future__ import absolute_import

import hashlib
import json
import os
import re
import sys
import time
import uuid
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from .adapters import ADAPTERS
from .aggregator import group_movies, normalize_title

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
HANDLE = int(sys.argv[1])
PLUGIN_BASE = sys.argv[0]
HOST_CACHE_SCHEMA = 5
META = {}  # filled by main.film() with the movie's art/plot so host rows look like the movie


def plugin_url(action, **params):
    query = {'action': action}
    query.update(params)
    return PLUGIN_BASE + '?' + urlencode(query)



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




def quality_counts():
    return {'4K': 0, '1080p': 0, '720p': 0, 'HD': 0, 'SD': 0, 'DVD': 0, 'CAM': 0, 'Egyéb': 0, 'Összesen': 0}


def source_quality_sort_key(source):
    quality = str(source.get('quality', '') or '').upper()
    if '2160' in quality or '4K' in quality or 'UHD' in quality:
        rank = 0
    elif '1440' in quality or '2K' in quality:
        rank = 1
    elif '1080' in quality:
        rank = 2
    elif '720' in quality:
        rank = 3
    elif 'HD' in quality:
        rank = 4
    elif 'DVD' in quality:
        rank = 5
    elif '480' in quality or '360' in quality or 'SD' in quality:
        rank = 6
    elif 'CAM' in quality or 'TS' == quality.strip():
        rank = 7
    else:
        rank = 8
    return (
        rank,
        str(source.get('adapter_name', '')).casefold(),
        str(source.get('host', '')).casefold(),
        str(source.get('language', '')).casefold()
    )


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


def update_source_progress(progress, percent, page_name, completed, total, counts, phase):
    percent = max(0, min(100, int(percent)))
    frames = ('[>   ]', '[=>  ]', '[==> ]', '[===>]')
    frame = frames[(int(completed) + percent) % len(frames)]
    line1 = '[COLOR FFBCA8E8]%s[/COLOR]  [COLOR FF72D5C9]%s[/COLOR]  [COLOR FFFF9E64]%d%%[/COLOR]' % (
        phase, frame, percent
    )
    line2 = '[COLOR FFE6ECF2]Aktuális:[/COLOR] [COLOR FFD9B15F]%s[/COLOR]  [COLOR FF72D5C9]%d/%d[/COLOR]' % (
        page_name, max(0, int(completed)), max(1, int(total))
    )
    line3 = (
        '[COLOR FFBCA8E8]4K %d[/COLOR] | '
        '[COLOR FF72D5C9]1080p %d[/COLOR] | '
        '[COLOR FF77B5FF]720p %d[/COLOR] | '
        '[COLOR FF66CC88]HD %d[/COLOR] | '
        '[COLOR FFA7B0BA]SD %d[/COLOR] | '
        '[COLOR FFFFB86C]DVD %d[/COLOR] | '
        '[COLOR FFFF7777]CAM %d[/COLOR]  '
        '[COLOR FFE6ECF2]Össz: [COLOR FFFF9E64]%d[/COLOR][/COLOR]'
    ) % (
        counts['4K'], counts['1080p'], counts['720p'], counts['HD'],
        counts['SD'], counts['DVD'], counts['CAM'], counts['Összesen']
    )
    # Kodi 21's Python DialogProgress.update accepts percent plus one message.
    progress.update(percent, '\n'.join((line1, line2, line3)))


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
    progress.create('HOSTKERESÉS  |  %s' % title, 'Forrásoldalak előkészítése...')
    cancelled = False
    total_adapters = len(ADAPTERS)
    try:
        for index, adapter in enumerate(ADAPTERS):
            if progress.iscanceled():
                cancelled = True
                break
            update_source_progress(
                progress, int(25 * index / max(1, total_adapters)),
                adapter.name, index, total_adapters, counts, 'FORRÁSKERESÉS'
            )
            try:
                records.extend(adapter.search(title) or [])
            except Exception as exc:
                errors.append('%s: %s' % (adapter.name, exc))
                xbmc.log('%s adapter search failed: %s' % (ADDON_ID, exc), xbmc.LOGWARNING)
            update_source_progress(
                progress, int(25 * (index + 1) / max(1, total_adapters)),
                adapter.name, index + 1, total_adapters, counts, 'FORRÁSKERESÉS'
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
                    index, len(tasks), counts, 'HOSTOK KIOLVASÁSA'
                )
                try:
                    found = adapter.sources(movie) or []
                    accepted = []
                    for source in found:
                        source['adapter_name'] = source.get('adapter_name') or adapter.name
                        key = (
                            source['adapter_name'], str(source.get('host', '')).casefold(),
                            str(source.get('quality', '')).casefold(), str(source.get('language', '')).casefold(),
                            str(source.get('source_url') or source.get('source_page_url') or source.get('play_url', '')).casefold()
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
                    index + 1, len(tasks), counts, 'HOSTOK KIOLVASÁSA'
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
    sources = sorted(sources, key=source_quality_sort_key)
    shown = '%s [COLOR FFFFD700](%s)[/COLOR]' % (title, META['year']) if META.get('year') else title
    header = xbmcgui.ListItem(label='[COLOR FF65758B]--- %s | FILMHOSTOK ---[/COLOR]' % shown)
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
        quality = re.sub(r'\[/?COLOR[^\]]*\]', '', str(source.get('quality', '') or 'N/A'), flags=re.I)
        language = re.sub(r'\[/?COLOR[^\]]*\]', '', str(source.get('language', '') or 'N/A'), flags=re.I)
        label = (
            '[COLOR FFFD9B58]%s[/COLOR]  |  [COLOR FFE6ECF2]%s[/COLOR]  |  '
            '[COLOR FFD9B15F]%s[/COLOR]  |  [COLOR FFBCA8E8]%s[/COLOR]'
        ) % (quality, host, provider, language)
        item = xbmcgui.ListItem(label=label)
        info = {'title': title, 'mediatype': 'movie'}
        if META.get('plot'):
            info['plot'] = META['plot']
        if META.get('year'):
            info['year'] = META['year']
        set_video_info(item, info)
        art = {}
        if META.get('poster'):
            art.update({'thumb': META['poster'], 'poster': META['poster']})
        if META.get('fanart'):
            art['fanart'] = META['fanart']
        if art:
            item.setArt(art)
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
        xbmcgui.Dialog().notification('Mafab.hu', 'A forráslista lejárt; nyisd meg újra a filmet.', xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    title = queue.get('title', 'Film')
    sources = queue['sources']
    try:
        start_index = max(0, int(start_index))
    except (TypeError, ValueError):
        start_index = 0
    if start_index >= len(sources):
        xbmcgui.Dialog().notification('Mafab.hu', 'A kiválasztott forrássor már nem érhető el.', xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    progress = xbmcgui.DialogProgress()
    progress.create('Forrás ellenőrzése - %s' % title, 'Lejátszható host keresése indul...')
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
                            status = 'Cloudflare/ellenőrző oldal - nem kerüljük meg; következő forrás...'
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
                            '[COLOR FF72D5C9]%s[/COLOR]  |  [COLOR FFD9B15F]%s => %s[/COLOR]\n'
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
            stream = ''
            if source_url and source.get('direct_stream') and source_url.startswith(('http://', 'https://')):
                stream = source_url
            elif source_url and (zidervisionurlresolver or resolveurl):
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
            elif source_url and source.get('allow_raw_source') and source_url.startswith(('http://', 'https://')):
                # FilmDepo's supplied addon also passes the player URL through unchanged
                # when ResolveURL is not installed; availability checking still guards it.
                stream = source_url
            if stream:
                if stream_is_available(stream):
                    xbmc.log('%s resolved row %d (%s / %s)' % (ADDON_ID, index + 1, adapter_name, host), xbmc.LOGINFO)
                    progress.update(100, '[COLOR FF55C7C2]Forrás használható - lejátszás indítása:[/COLOR] [COLOR FFD9B15F]%s[/COLOR]' % host)
                    item = xbmcgui.ListItem(label=title, path=stream)
                    item.setProperty('IsPlayable', 'true')
                    set_video_info(item, {'title': title, 'mediatype': 'movie'})
                    xbmcplugin.setResolvedUrl(HANDLE, True, item)
                    return
                xbmc.log('%s resolved stream unavailable at row %d (%s / %s); continuing' % (ADDON_ID, index + 1, adapter_name, host), xbmc.LOGINFO)
            if source_url:
                xbmc.log('%s direct source unavailable at row %d (%s / %s); continuing' % (ADDON_ID, index + 1, adapter_name, host), xbmc.LOGINFO)
                if source.get('parent_resolve_only') and (source.get('direct_stream') or source.get('allow_raw_source') or zidervisionurlresolver or resolveurl):
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
            xbmcgui.Dialog().notification('Mafab.hu', 'A hostpróbát megszakítottad.', xbmcgui.NOTIFICATION_INFO)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        else:
            xbmcgui.Dialog().notification('Mafab.hu', 'Egyik hostot sem sikerült feloldani.', xbmcgui.NOTIFICATION_ERROR, 4500)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
    finally:
        progress.close()


def stream_is_available(url):
    """Lightweight availability check so a dead resolved link is skipped before playback."""
    target = url
    headers = {'User-Agent': 'Mozilla/5.0 (Kodi; plugin.video.mafab/0.2.0)', 'Range': 'bytes=0-0'}
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


