import sys
import time
import requests
import re
import urllib.parse
from datetime import datetime
import xbmcgui
import xbmcplugin
import xbmcaddon

HANDLE = int(sys.argv[1])

def get_html(url):
    session = requests.Session()
    time.sleep(0.5) # [2026-01-05] Szerver kímélése
    cookies = {'ljtz': 'Europe/Budapest', 'ljoffset': '3600'}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'}
    try:
        session.get("https://liveonsat.com/", headers=headers, cookies=cookies, timeout=10)
        r = session.get(url, headers=headers, cookies=cookies, timeout=10)
        r.encoding = 'utf-8'
        return r.text
    except: return ""

def super_clean(text):
    if not text: return ""
    t = text.replace('&ndash;', '-').replace('&nbsp;', ' ').replace('&deg;', '°').replace('&quot;', '"')
    t = re.sub(r'<[^>]*>', ' ', t)
    return " ".join(t.split()).strip()

def list_matches():
    xbmcplugin.setContent(HANDLE, 'files')
    html = get_html("https://liveonsat.com/2day.php")
    if not html: return

    # Aktuális Unix idő (másodpercben)
    current_unix = int(time.time())

    blocks = re.split(r'background-color:#ffd379', html)
    for i in range(1, len(blocks)):
        curr_part = blocks[i]
        
        # Keressük meg a timestamp-et a HTML-ben
        ts_m = re.search(r'data-timestamp="(\d+)"', curr_part)
        time_text_m = re.findall(r'ST:\s*(\d{2}:\d{2})', curr_part)
        
        if not ts_m or not time_text_m: continue
        
        match_unix = int(ts_m.group(1))
        match_time_str = time_text_m[0]

        # --- AZ ULTIMÁTUM SZŰRÉS ---
        # Ha a meccs kezdete óta eltelt több mint 135 perc (2 óra 15 perc), akkor már vége
        if current_unix > (match_unix + 135 * 60):
            continue
            
        # Ha a meccs több mint 24 óra múlva lesz (biztonsági szűrő), ne mutassuk
        if match_unix > (current_unix + 86400):
            continue

        # Csapatok
        team_m = re.search(r'^[^>]*>(.*?)</div>', curr_part, re.DOTALL)
        if not team_m: continue
        teams = super_clean(team_m.group(1))
        if not teams or "LiveOnSat" in teams: continue

        channels_data = []
        chan_matches = re.findall(r'overlib\(\'(.*?)\',CAPTION,\s*\'(.*?)\'', curr_part, re.DOTALL)
        
        for ovl_raw, name_raw in chan_matches:
            c_name = super_clean(name_raw).split(' - ')[0].strip()
            ovl = ovl_raw.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
            rows = re.split(r'<br/?>|</tr>', ovl)
            cleaned_rows = []
            for r in rows:
                cleaned = super_clean(r)
                for word in ['pos', 'satellite', 'freq', 'symbol', 'encryption']:
                    cleaned = re.sub(word, '', cleaned, flags=re.IGNORECASE).strip()
                if cleaned and len(cleaned) > 5 and cleaned not in cleaned_rows:
                    cleaned_rows.append(cleaned)
            
            if c_name and cleaned_rows:
                tech_str = "§§§".join(cleaned_rows)
                channels_data.append(f"{c_name}:::{tech_str}")

        if channels_data:
            live_tag = ""
            # LIVE ha: a kezdés már elmúlt, de még nem telt el 125 perc
            if match_unix <= current_unix <= (match_unix + 125 * 60):
                live_tag = "[COLOR red][ LIVE ][/COLOR] "
            
            title = f"{live_tag}[COLOR white]{match_time_str}[/COLOR] - [B]{teams}[/B]"
            encoded_data = urllib.parse.quote("|||".join(channels_data))
            u = f"{sys.argv[0]}?mode=chans&data={encoded_data}"
            xbmcplugin.addDirectoryItem(HANDLE, url=u, listitem=xbmcgui.ListItem(label=title), isFolder=True)

    xbmcplugin.endOfDirectory(HANDLE)

# Feltételezve, hogy a HANDLE és egyéb változók definiálva vannak az addonodban
# HANDLE = int(sys.argv[1])

def list_channels(data_str):
    try:
        ADDON = xbmcaddon.Addon()
        hide_streams = ADDON.getSettingBool('hide_streams')
        only_fta = ADDON.getSettingBool('only_fta')
    except:
        hide_streams, only_fta = False, False

    xbmcplugin.setContent(HANDLE, 'videos')
    decoded_data = urllib.parse.unquote(data_str)
    
    processed_list = []
    blacklist = ['0', 'liveonsat.com', 'liveonsat', 'advertisement', 'tablepad', 'none']
    IPTV_PATTERN = r'(?<!\d)0\.0°(?![EWew])'
    FTA_PATTERN = r'(?i)free to air|\bfta\b'
    HD_PATTERN = r'(?i)\bhd\b'

    for item in decoded_data.split('|||'):
        if ':::' in item:
            name, tech_bundle = item.split(':::', 1)
            name = name.strip()
            if name.lower() in blacklist or len(name) < 2: continue
                
            tech_lines = [line.strip() for line in tech_bundle.split('§§§') if line.strip()]
            if not tech_lines or (len(tech_lines) == 1 and tech_lines[0] == '0'): continue
            
            is_fta = any(re.search(FTA_PATTERN, l) for l in tech_lines) or re.search(FTA_PATTERN, name)
            is_online = any(re.search(IPTV_PATTERN, l) for l in tech_lines)

            if (only_fta and not is_fta) or (hide_streams and is_online): continue

            priority = 1 if is_fta else (3 if is_online else 2)
            clean_name = re.sub(FTA_PATTERN, '', name).replace('()', '').strip()

            processed_list.append({
                'priority': priority, 'name': clean_name, 'tech': tech_lines, 
                'is_fta': is_fta, 'is_online': is_online
            })

    processed_list.sort(key=lambda x: x['priority'])

    for ch in processed_list:
        # Főcím stílus
        prefix = "[COLOR gold]★[/COLOR]" if ch['is_fta'] else ("[COLOR cyan]★[/COLOR]" if ch['is_online'] else "[COLOR lime]★[/COLOR]")
        name_color = "gray" if ch['is_online'] else "white"
        label = f"{prefix} [COLOR {name_color}][B]{ch['name']}[/B][/COLOR]"

        if ch['is_online']:
            for t in ch['tech']:
                if re.search(IPTV_PATTERN, t):
                    info = re.sub(IPTV_PATTERN + r'|0\.000|\b0\b|- \(0/0\)|\d{5}\s*[VHvhLRlr]|(?i)liveonsat(?:\.com)?', '', t).strip()
                    info = re.sub(HD_PATTERN, '[COLOR skyblue]HD[/COLOR]', info)
                    info = info.lstrip('* :').rstrip(' ,-()').strip()
                    label += f" [COLOR cyan][ IPTV: {info} ][/COLOR]" if info else " [COLOR cyan][ STREAM ][/COLOR]"
                    break

        list_item = xbmcgui.ListItem(label=label)
        
        # MAPPING / KERESÉS ELŐKÉSZÍTÉSE
        # Tisztított név a későbbi kereséshez
        clean_search = ch['name'].split('(')[0].strip()
        search_url = f"plugin://plugin.video.searcher/?q={urllib.parse.quote(clean_search)}"
        
        list_item.addContextMenuItems([
            ('Csatorna keresése (Mapping)', f'RunPlugin({search_url})'),
            ('Műsorinformáció', 'Action(Info)')
        ])
        list_item.setProperty('IsPlayable', 'false')
        xbmcplugin.addDirectoryItem(HANDLE, url="", listitem=list_item, isFolder=False)
        
        # Technikai al-sorok (Műhold esetén)
        if not ch['is_online']:
            for t_line in ch['tech']:
                # Színezések
                l_lab = re.sub(r'(\d+\.\d°[EWew])', r'[COLOR dodgerblue][B]\1[/B][/COLOR]', t_line) # Pozíció
                l_lab = re.sub(r'(\d{2,5}(?:\.\d{3})?)\s*([VHvhLRlr])', r'[COLOR white]\1[/COLOR] [COLOR orange][B]\2[/B][/COLOR]', l_lab) # Freq
                l_lab = re.sub(r'(\d{4,5})\s*-\s*(\d/\d)', r'[COLOR springgreen]\1[/COLOR] [COLOR gray](\2)[/COLOR]', l_lab) # SR/FEC
                
                # HD kiemelés
                l_lab = re.sub(HD_PATTERN, r'[COLOR skyblue][B]HD[/B][/COLOR]', l_lab)
                
                # Takarítás
                l_lab = re.sub(r'(?i)liveonsat(?:\.com)?', '', l_lab)
                if re.search(FTA_PATTERN, t_line):
                    l_lab = re.sub(FTA_PATTERN, '', l_lab).strip()
                    l_lab += " [COLOR gold][B][ KÓDOLATLAN ][/B][/COLOR]"
                
                if "geo" in t_line.lower(): l_lab += " [COLOR red]⚠ [B]GEO[/B][/COLOR]"

                l_lab = l_lab.replace('()', '').rstrip(' ,-()').strip()
                if l_lab:
                    sub_item = xbmcgui.ListItem(label=f"    [COLOR gray]►[/COLOR] {l_lab}")
                    sub_item.setProperty('IsPlayable', 'false')
                    xbmcplugin.addDirectoryItem(HANDLE, url="", listitem=sub_item, isFolder=False)
                
    xbmcplugin.endOfDirectory(HANDLE)

if __name__ == '__main__':
    p = dict(urllib.parse.parse_qsl(sys.argv[2][1:]))
    if p.get('mode') == 'chans':
        list_channels(p.get('data', ''))
    else:
        list_matches()