# -*- coding: utf-8 -*-
"""LiveTV SX public schedule browser for Kodi 21.x.

Reads public event listings, adds sport/time/live metadata, and resolves only
plain public HLS/DASH/MP4 URLs explicitly exposed by provider pages.
"""
import html
import http.cookiejar
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
BASE = 'https://livetv.sx'
HOME = BASE + '/enx/'
ALL_EVENTS = BASE + '/enx/allupcoming/'
HANDLE = int(sys.argv[1])
COOKIE_JAR = http.cookiejar.CookieJar()
HTTP_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))


def log(message, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, message), level)


def notify(message):
    xbmcgui.Dialog().notification('LiveTV SX', message, xbmcgui.NOTIFICATION_INFO, 5000)


def fetch(url, referer=HOME):
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Kodi; LiveTV-SX add-on) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.8',
            'Referer': referer,
        },
    )
    with HTTP_OPENER.open(request, timeout=20) as response:
        data = response.read(6 * 1024 * 1024)
        charset = response.headers.get_content_charset() or 'utf-8'
    return data.decode(charset, errors='replace')


class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors = []
        self.href = None
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'a':
            self.href = attrs.get('href')
            self.parts = []

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.skip:
            self.skip -= 1
        if tag == 'a' and self.href is not None:
            text = ' '.join(' '.join(self.parts).split())
            self.anchors.append((self.href, text))
            self.href = None
            self.parts = []

    def handle_data(self, data):
        if self.href is not None and not self.skip:
            self.parts.append(data.strip())


def get_anchors(document):
    parser = AnchorParser()
    parser.feed(document)
    return parser.anchors


class SportNavParser(HTMLParser):
    """Read the site's own sport menu labels and sportN.gif artwork."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.current = None
        self.icons = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and '/allupcomingsports/' in (attrs.get('href', '') or ''):
            self.current = {}
        elif tag == 'img' and self.current is not None:
            self.current['title'] = (attrs.get('title') or attrs.get('alt') or '').strip()
            self.current['src'] = (attrs.get('src') or '').strip()

    def handle_endtag(self, tag):
        if tag == 'a' and self.current is not None:
            title = self.current.get('title', '')
            src = self.current.get('src', '')
            if title and src:
                self.icons[title.casefold()] = urllib.parse.urljoin(BASE, src)
            self.current = None


def sport_navigation_icons(document):
    parser = SportNavParser()
    parser.feed(document)
    return parser.icons


class EventRowParser(HTMLParser):
    """Extract sport, displayed schedule time, score and live marker from one row."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sport_label = ''
        self.icon_src = ''
        self.time_parts = []
        self.live_parts = []
        self.live_marker = False
        self.span_stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img':
            alt = html.unescape(attrs.get('alt', '') or '').strip()
            raw_src = (attrs.get('src', '') or '').strip()
            src = raw_src.lower()
            if alt and not self.sport_label:
                self.sport_label = alt
                self.icon_src = raw_src
            if 'live.gif' in src:
                self.live_marker = True
        elif tag == 'span':
            classes = (attrs.get('class', '') or '').lower().split()
            self.span_stack.append({'classes': classes, 'text': []})

    def handle_data(self, data):
        for span in self.span_stack:
            span['text'].append(data)

    def handle_endtag(self, tag):
        if tag == 'span' and self.span_stack:
            span = self.span_stack.pop()
            text = ' '.join(' '.join(span['text']).split())
            if 'evdesc' in span['classes'] and text:
                self.time_parts.append(text)
            elif 'live' in span['classes'] and text:
                self.live_parts.append(text)


def event_day_for_position(document, pos):
    """Return the last meaningful date heading before an event, if present."""
    prefix = document[:pos]
    pattern = r'<span\b[^>]*class=["\'][^"\']*\bdate\b[^"\']*["\'][^>]*>(.*?)</span>'
    matches = list(re.finditer(pattern, prefix, flags=re.I | re.S))
    for match in reversed(matches):
        text = re.sub(r'<[^>]+>', ' ', match.group(1))
        text = ' '.join(html.unescape(text).split())
        if text and 'top events live' not in text.lower() and 'your current time zone' not in text.lower():
            return text
    return ''


def event_row_metadata(document, href):
    # The public schedule places sport icon, event title, live marker/score,
    # and evdesc time in the same nested table row.
    pos = document.find(href)
    if pos < 0:
        path = urllib.parse.urlsplit(href).path
        pos = document.find(path)
    if pos < 0:
        return {'sport': 'Other', 'time': '', 'live': False, 'score': '', 'icon': ''}
    start = document.rfind('<tr', 0, pos)
    end = document.find('</tr>', pos)
    row = document[start:end + 5] if start >= 0 and end >= 0 else document[max(0, pos - 700):pos + 1200]
    parser = EventRowParser()
    parser.feed(row)
    sport_label = html.unescape(parser.sport_label).strip()
    sport = sport_label.split('.', 1)[0].strip() if sport_label else 'Other'
    return {
        'sport': sport or 'Other',
        'sport_detail': sport_label,
        'icon': urllib.parse.urljoin(BASE, parser.icon_src) if parser.icon_src else '',
        'date': event_day_for_position(document, pos),
        'time': parser.time_parts[0] if parser.time_parts else '',
        'live': parser.live_marker,
        'score': parser.live_parts[0] if parser.live_parts else '',
    }


def parse_events(document):
    events = []
    seen = set()
    for href, title in get_anchors(document):
        href = html.unescape(href or '')
        if '/eventinfo/' not in href:
            continue
        absolute = urllib.parse.urljoin(BASE, href)
        title = html.unescape(title).strip()
        if not title or absolute in seen:
            continue
        seen.add(absolute)
        meta = event_row_metadata(document, href)
        events.append({
            'title': title,
            'url': absolute,
            'sport': meta['sport'],
            'sport_detail': meta['sport_detail'],
            'sport_icon': meta['icon'],
            'date': meta['date'],
            'time': meta['time'],
            'live': meta['live'],
            'score': meta['score'],
        })
    return events


def plugin_url(**params):
    return 'plugin://%s/?%s' % (ADDON_ID, urllib.parse.urlencode(params))


def add_directory(label, url, folder=True, info=None, playable=False, art=None):
    item = xbmcgui.ListItem(label=label)
    icon = art or ADDON.getAddonInfo('icon')
    if icon:
        item.setArt({'icon': icon, 'thumb': icon})
    if info:
        item.setInfo('video', info)
    if playable:
        item.setProperty('IsPlayable', 'true')
    xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=folder)


def home():
    xbmcplugin.setPluginCategory(HANDLE, 'LiveTV SX')
    xbmcplugin.setContent(HANDLE, 'videos')
    add_directory('[COLOR red][B]● LIVE NOW[/B][/COLOR]', plugin_url(action='events', view='live'))
    add_directory('[COLOR deepskyblue][B]◷ UPCOMING[/B][/COLOR]', plugin_url(action='events', view='upcoming'))
    add_directory('[COLOR orange][B]SPORTS CATEGORIES[/B][/COLOR]', plugin_url(action='sports'))
    add_directory('[COLOR gold][B]ALL EVENTS[/B][/COLOR]', plugin_url(action='events', view='all'))
    add_directory('[COLOR silver]About / playback requirements[/COLOR]', plugin_url(action='about'))
    xbmcplugin.endOfDirectory(HANDLE)


def load_events(url=ALL_EVENTS):
    document = fetch(url)
    return parse_events(document)


def list_sports():
    xbmcplugin.setPluginCategory(HANDLE, 'Sports')
    xbmcplugin.setContent(HANDLE, 'videos')
    try:
        document = fetch(ALL_EVENTS)
        events = parse_events(document)
        menu_icons = sport_navigation_icons(document)
        counts = {}
        fallbacks = {}
        for event in events:
            counts[event['sport']] = counts.get(event['sport'], 0) + 1
            if event['sport_icon'] and event['sport'] not in fallbacks:
                fallbacks[event['sport']] = event['sport_icon']
        palette = ['deepskyblue', 'orange', 'springgreen', 'orchid', 'gold', 'turquoise', 'coral']
        for index, sport in enumerate(sorted(counts, key=lambda x: x.casefold())):
            color = palette[index % len(palette)]
            icon = menu_icons.get(sport.casefold()) or fallbacks.get(sport)
            add_directory('[COLOR %s][B]%s[/B][/COLOR]  [COLOR gray](%d)[/COLOR]' % (color, sport, counts[sport]), plugin_url(action='events', view='all', sport=sport), art=icon)
        if not counts:
            notify('No sports categories were found.')
    except Exception as exc:
        log('Could not load sports: %s' % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().ok('LiveTV SX', 'Sports could not be loaded.\n\n%s' % exc)
    xbmcplugin.endOfDirectory(HANDLE)


def event_label(event):
    status = '[COLOR red][B]● LIVE[/B][/COLOR]' if event['live'] else '[COLOR deepskyblue][B]◷ UPCOMING[/B][/COLOR]'
    time_text = event['time'] or 'Start time unavailable'
    if event.get('date'):
        time_text = '%s · %s' % (event['date'], time_text)
    label = '%s  [COLOR khaki]%s[/COLOR]  [COLOR orange]%s[/COLOR]  [B]%s[/B]' % (status, time_text, event['sport'], event['title'])
    if event['live'] and event['score']:
        label += '  [COLOR lime][B]%s[/B][/COLOR]' % event['score']
    return label


def list_events(view='all', sport=''):
    title = 'Events'
    if view == 'live':
        title = 'Live now'
    elif view == 'upcoming':
        title = 'Upcoming'
    if sport:
        title = sport
    xbmcplugin.setPluginCategory(HANDLE, title)
    xbmcplugin.setContent(HANDLE, 'videos')
    try:
        events = load_events()
        if view == 'live':
            events = [event for event in events if event['live']]
        elif view == 'upcoming':
            events = [event for event in events if not event['live']]
        if sport:
            events = [event for event in events if event['sport'].casefold() == sport.casefold()]
        # Keep the site's page order (live entries and then the displayed schedule).
        for event in events:
            plot = '%s\n%s\n%s' % (
                'LIVE' if event['live'] else 'UPCOMING',
                ('%s · ' % event['date'] if event.get('date') else '') + (event['time'] or 'Start time unavailable'),
                event.get('sport_detail', event['sport']),
            )
            if event['score']:
                plot += '\nScore: ' + event['score']
            item = xbmcgui.ListItem(label=event_label(event))
            item.setInfo('video', {'title': event['title'], 'plot': plot, 'genre': event['sport']})
            icon = event['sport_icon'] or ADDON.getAddonInfo('icon')
            if icon:
                item.setArt({'icon': icon, 'thumb': icon})
            xbmcplugin.addDirectoryItem(HANDLE, plugin_url(action='event', url=event['url']), item, isFolder=True)
        if not events:
            notify('No matching events found.')
    except Exception as exc:
        log('Could not read event list: %s' % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().ok('LiveTV SX', 'The public event list could not be loaded.\n\n%s' % exc)
    xbmcplugin.endOfDirectory(HANDLE)


def provider_for(document, lid, stream_type):
    if lid:
        match = re.search(
            r'<span[^>]*id=["\']ltonq%s["\'][^>]*>(.*?)</span>' % re.escape(lid),
            document,
            flags=re.I | re.S,
        )
        if match:
            name = re.sub(r'<[^>]+>', '', match.group(1))
            name = html.unescape(name).strip()
            if name:
                return name
    return stream_type or 'Web player'


def extract_streams(document):
    streams = []
    seen = set()
    for raw_href, _ in get_anchors(document):
        href = html.unescape(raw_href or '')
        if 'webplayer2.php' not in href:
            continue
        web_url = urllib.parse.urljoin(BASE, href)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(web_url).query)
        stream_type = query.get('t', [''])[0]
        content_id = query.get('c', [''])[0]
        lid = query.get('lid', [''])[0]
        if stream_type.lower() == 'acestream':
            continue
        key = (stream_type, content_id)
        if not stream_type or not content_id or key in seen:
            continue
        seen.add(key)
        provider = provider_for(document, lid, stream_type)
        streams.append({
            'title': '%s — stream' % provider,
            'target': web_url,
            'playable': True,
            'info': 'The add-on will look for a public direct HLS/DASH media URL in this provider page. DRM or sign-in bypass is not supported.',
        })
    return streams


def show_event(url):
    xbmcplugin.setPluginCategory(HANDLE, 'Available broadcasts')
    xbmcplugin.setContent(HANDLE, 'videos')
    try:
        document = fetch(url)
        streams = extract_streams(document)
        for stream in streams:
            li = xbmcgui.ListItem(label='[COLOR gold][B]▶ PLAY[/B][/COLOR]  [COLOR white]%s[/COLOR]' % stream['title'])
            li.setInfo('video', {'title': stream['title'], 'plot': stream['info']})
            icon = ADDON.getAddonInfo('icon')
            if icon:
                li.setArt({'icon': icon, 'thumb': icon})
            li.setProperty('IsPlayable', 'true')
            xbmcplugin.addDirectoryItem(HANDLE, plugin_url(action='play', target=stream['target']), li, isFolder=False)
        if not streams:
            add_directory('No public stream links found — open event page URL', plugin_url(action='webinfo', target=url), folder=False)
        add_directory('Official event page URL', plugin_url(action='webinfo', target=url), folder=False)
    except Exception as exc:
        log('Could not read event page: %s' % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().ok('LiveTV SX', 'This event page could not be loaded.\n\n%s' % exc)
    xbmcplugin.endOfDirectory(HANDLE)


def iframe_urls(page, page_url):
    urls = []
    pattern = r'<iframe\b[^>]*\bsrc\s*=\s*(["\'])(.*?)\1'
    for match in re.finditer(pattern, page, flags=re.I | re.S):
        raw = html.unescape(match.group(2)).replace('\\/', '/')
        candidate = urllib.parse.urljoin(page_url, raw)
        parsed = urllib.parse.urlsplit(candidate)
        host = (parsed.hostname or '').lower()
        if parsed.scheme not in ('http', 'https') or not host:
            continue
        if host.startswith('ad.') or host.startswith('ads.') or '/getbanner.php' in parsed.path.lower():
            continue
        if candidate not in urls:
            urls.append(candidate)
        if len(urls) >= 8:
            break
    return urls


def media_url_from_page(page, page_url):
    # These are plain media URLs already emitted in the provider's public HTML/JS.
    # The add-on does not execute obfuscated scripts or decrypt protected sources.
    normalized = html.unescape(page).replace('\\/', '/')
    pattern = r'(?:(?:https?:)?//|/)[^\s"\'<>\\]+?\.(?:m3u8|mpd|mp4)(?:\?[^\s"\'<>\\]*)?'
    for match in re.finditer(pattern, normalized, flags=re.I):
        candidate = match.group(0).rstrip('),;]')
        absolute = urllib.parse.urljoin(page_url, candidate)
        parsed = urllib.parse.urlsplit(absolute)
        if parsed.scheme in ('http', 'https') and parsed.hostname:
            return absolute
    return ''


def resolve_webplayer(webplayer_url):
    player_page = fetch(webplayer_url, referer=HOME)
    direct = media_url_from_page(player_page, webplayer_url)
    if direct:
        return direct, webplayer_url
    for frame_url in iframe_urls(player_page, webplayer_url):
        try:
            frame_page = fetch(frame_url, referer=webplayer_url)
        except Exception as exc:
            log('Provider frame could not be loaded (%s).' % type(exc).__name__, xbmc.LOGWARNING)
            continue
        direct = media_url_from_page(frame_page, frame_url)
        if direct:
            return direct, frame_url
    raise ValueError('The provider page did not publish a direct HLS, DASH, or MP4 URL.')


def play(target):
    try:
        media_url, referer = resolve_webplayer(target)
        extension = urllib.parse.urlsplit(media_url).path.lower()
        mime = 'application/vnd.apple.mpegurl' if extension.endswith('.m3u8') else (
            'application/dash+xml' if extension.endswith('.mpd') else 'video/mp4'
        )
        headers = {'User-Agent': 'Mozilla/5.0 (Kodi; LiveTV-SX add-on) AppleWebKit/537.36'}
        if referer:
            headers['Referer'] = referer
            parsed_referer = urllib.parse.urlsplit(referer)
            headers['Origin'] = '%s://%s' % (parsed_referer.scheme, parsed_referer.netloc)
        media_url += '|' + urllib.parse.urlencode(headers)
        item = xbmcgui.ListItem(path=media_url)
        item.setProperty('IsPlayable', 'true')
        if mime:
            item.setMimeType(mime)
            item.setContentLookup(False)
            if mime == 'application/dash+xml':
                item.setProperty('inputstream', 'inputstream.adaptive')
                item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
        xbmcplugin.setResolvedUrl(HANDLE, True, item)
    except Exception as exc:
        log('Could not resolve public provider URL (%s).' % type(exc).__name__, xbmc.LOGERROR)
        xbmcgui.Dialog().ok(
            'Cannot play this source',
            'A direct, non-protected media URL was not found in the provider page.\n\n'
            'Check whether this source is public HLS/DASH/MP4, or provide an official playback API/manifest URL. DRM and sign-in protected sources are not resolved.'
        )
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())


def show_web_info(target):
    xbmcgui.Dialog().textviewer('Official website player URL', target)
    xbmcplugin.endOfDirectory(HANDLE, succeeded=True, updateListing=False, cacheToDisc=False)


def show_about():
    xbmcgui.Dialog().ok(
        'LiveTV SX add-on',
        'Events are grouped by sport. Schedule times are shown exactly as the website displays them; LIVE is identified from the site\'s live marker and score.\n\n'
        'AceStream sources are currently omitted. For other web-player entries, the add-on looks for a public HLS/DASH/MP4 URL in the provider page and passes it to Kodi.\n\n'
        'It does not bypass sign-in, execute obfuscated player scripts, or decrypt DRM-protected streams.'
    )
    xbmcplugin.endOfDirectory(HANDLE)


def main():
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(sys.argv[2]).query)) if len(sys.argv) > 2 else {}
    action = params.get('action', 'home')
    url = params.get('url', ALL_EVENTS)
    if action == 'home':
        home()
    elif action == 'sports':
        list_sports()
    elif action == 'events':
        list_events(params.get('view', 'all'), params.get('sport', ''))
    elif action == 'event':
        show_event(url)
    elif action == 'play':
        play(params.get('target', ''))
    elif action == 'webinfo':
        show_web_info(params.get('target', ''))
    elif action == 'about':
        show_about()
    else:
        notify('Unknown menu action.')
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


if __name__ == '__main__':
    main()
