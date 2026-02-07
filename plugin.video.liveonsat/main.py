import sys
import time
import requests
import re
import html
import xbmcgui
import xbmcplugin

HANDLE = int(sys.argv[1])

def get_html(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
    }
    # A kért 0.5 mp várakozás, hogy ne legyünk gyanúsak
    time.sleep(0.5)
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return html.unescape(r.text)
    except:
        return ""

def list_live_matches():
    xbmcplugin.setContent(HANDLE, 'videos')
    url = "https://m.liveonsat.com/2day.php"
    html_content = get_html(url)
    
    if not html_content:
        return

    # 1. Összes elem kigyűjtése pozícióval együtt
    elements = []

    # Időpontok: (Pozíció, Típus, Érték)
    for m in re.finditer(r'ST:\s*(\d{2}:\d{2})', html_content):
        elements.append((m.start(), 'TIME', m.group(1)))

    # Csapatok (sárga cellák):
    for m in re.finditer(r'background-color:#ffd379;.*?>(.*?)</td>', html_content, re.DOTALL):
        clean_name = re.sub(r'<[^>]*>', '', m.group(1)).strip()
        if clean_name:
            elements.append((m.start(), 'TEAM', clean_name))

    # Csatornák:
    for m in re.finditer(r'class\s*=\s*["\']\s*(chan_live_[^"\']+)\s*["\'][^>]*>(.*?)</a>', html_content, re.IGNORECASE):
        chan_class = m.group(1)
        chan_name = re.sub(r'<[^>]*>', '', m.group(2)).strip()
        if chan_name:
            elements.append((m.start(), 'CHAN', (chan_class, chan_name)))

    # 2. Sorbarendezés az oldalon elfoglalt helyük alapján
    elements.sort(key=lambda x: x[0])

    # 3. Feldolgozás: emlékezünk az utolsó időre és csapatra
    curr_time = "??:??"
    curr_team = "Ismeretlen esemény"

    for _, kind, value in elements:
        if kind == 'TIME':
            curr_time = value
        elif kind == 'TEAM':
            curr_team = value
        elif kind == 'CHAN':
            chan_class, chan_name = value
            
            # Színezés
            color = "white"
            prefix = ""
            if "free" in chan_class and "not_free" not in chan_class:
                color = "green"
                prefix = "[COLOR green][FTA][/COLOR] "
            elif "not_free" in chan_class:
                color = "red"
                prefix = "[COLOR red][$][/COLOR] "

            label = f"[COLOR lightblue][{curr_time}][/COLOR] [B]{curr_team}[/B] - {prefix}{chan_name}"
            
            list_item = xbmcgui.ListItem(label=label)
            list_item.setInfo('video', {'title': curr_team, 'plot': f"{curr_team}\n{chan_name}"})
            xbmcplugin.addDirectoryItem(HANDLE, url="", listitem=list_item, isFolder=False)

    xbmcplugin.endOfDirectory(HANDLE)