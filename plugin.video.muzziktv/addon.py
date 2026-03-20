import sys
import urllib.parse
import xbmcgui
import xbmcplugin
import xbmcaddon
from resources.lib.muzzik_api import MuzzikAPI

# Addon beállítások
addon = xbmcaddon.Addon()
email = addon.getSetting('email')
password = addon.getSetting('password')

# API inicializálása
api = MuzzikAPI(email, password)
HANDLE = int(sys.argv[1])

def build_url(query):
    return f"{sys.argv[0]}?{urllib.parse.urlencode(query)}"

def main_menu():
    """Ez lesz az első dolog, amit látsz az addon megnyitásakor"""
    # TV Mappa
    li = xbmcgui.ListItem(label='[B]TV CSATORNÁK[/B]')
    url = build_url({'action': 'list', 'type': 'tv'})
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)

    # Rádió Mappa
    li = xbmcgui.ListItem(label='[B]RÁDIÓ ADÓK[/B]')
    url = build_url({'action': 'list', 'type': 'radio'})
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=li, isFolder=True)

    xbmcplugin.endOfDirectory(HANDLE)

def list_channels(is_radio=False):
    xbmcplugin.setContent(HANDLE, 'videos')

    if api.login():
        channels = api.get_channels()
        
        for channel in channels:
            # --- PONTOS AZONOSÍTÁS A JSON ALAPJÁN ---
            
            # 1. A legbiztosabb: audio_only mező (bool vagy string)
            # A JSON-ben: "audio_only": false
            api_audio_only = channel.get('audio_only')
            
            # Konvertáljuk biztos ami biztos alapon (ha stringként jönne)
            if isinstance(api_audio_only, str):
                is_this_radio = api_audio_only.lower() == 'true'
            else:
                is_this_radio = bool(api_audio_only)

            # 2. B-terv: Ha az 'audio_only' nem adna eredményt, nézzük a nevet/leírást
            name = channel.get('name', '').lower()
            description = channel.get('description', '').lower()
            if 'radio' in name or 'radio station' in description:
                is_this_radio = True

            # --- SZŰRÉS ---
            # Csak akkor adjuk hozzá, ha a kért típus (TV vagy Rádió) egyezik
            if is_this_radio == is_radio:
                name = channel.get('name', 'Unknown Channel')
                channel_id = channel.get('id')
                external_id = channel.get('external_id')
                thumbnail = channel.get('img') or channel.get('logo_url')
                
                list_item = xbmcgui.ListItem(label=name)
                list_item.setArt({'thumb': thumbnail, 'icon': thumbnail})
                
                # Ha rádió, beállíthatjuk a műfajt zenére
                genre = 'Radio' if is_this_radio else 'Music TV'
                list_item.setInfo('video', {'title': name, 'genre': genre})
                list_item.setProperty('IsPlayable', 'true')

                url = build_url({'action': 'play', 'id': channel_id, 'external_id': external_id})
                xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=list_item, isFolder=False)
    
    xbmcplugin.endOfDirectory(HANDLE)

def play_video(channel_id, external_id):
    if api.login():
        stream_url = api.get_stream_url(channel_id, external_id)
        # Itt fontos a path=stream_url és a setResolvedUrl
        play_item = xbmcgui.ListItem(path=stream_url)
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=play_item)

if __name__ == '__main__':
    params = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
    action = params.get('action')

    if not action:
        # Ha nincs akció, a főmenüt mutatjuk
        main_menu()
    elif action == 'list':
        # Listázás a 'type' paraméter alapján
        is_radio_requested = (params.get('type') == 'radio')
        list_channels(is_radio=is_radio_requested)
    elif action == 'play':
        play_video(params.get('id'), params.get('external_id'))