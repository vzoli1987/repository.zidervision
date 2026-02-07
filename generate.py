import hashlib
import os
import zipfile
import time
import datetime
import html
from xml.etree import ElementTree

# --- Beállítások ---
IGNORE = [".git", ".github", ".gitignore", "zips", "generate.py", "venv", "__pycache__", ".vscode", "index.html"]
ROOT_DIR = os.getcwd()

def generate_addons():
    """ZIP-ek és addons.xml létrehozása"""
    zips_path = os.path.join(ROOT_DIR, "zips")
    if not os.path.exists(zips_path):
        os.makedirs(zips_path)

    addons_xml_root = ElementTree.Element('addons')
    folders = [f for f in os.listdir(ROOT_DIR) if os.path.isdir(f) and f not in IGNORE]
    
    for folder in folders:
        xml_path = os.path.join(ROOT_DIR, folder, "addon.xml")
        if not os.path.exists(xml_path):
            continue

        tree = ElementTree.parse(xml_path)
        addon_node = tree.getroot()
        addon_id = addon_node.get('id')
        version = addon_node.get('version')

        # ZIP mappa létrehozása a zips alatt
        addon_zip_dir = os.path.join(zips_path, addon_id)
        if not os.path.exists(addon_zip_dir):
            os.makedirs(addon_zip_dir)
            
        zip_name = f"{addon_id}-{version}.zip"
        zip_file_path = os.path.join(addon_zip_dir, zip_name)
        
        # Tömörítés
        with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as z:
            addon_folder_path = os.path.join(ROOT_DIR, folder)
            for r, d, files in os.walk(addon_folder_path):
                for f in files:
                    abs_path = os.path.join(r, f)
                    rel_path = os.path.join(folder, os.path.relpath(abs_path, addon_folder_path))
                    z.write(abs_path, rel_path)

        addons_xml_root.append(addon_node)
        print(f"Kész addon: {addon_id} v{version}")

    # addons.xml mentése
    xml_out = os.path.join(zips_path, "addons.xml")
    ElementTree.ElementTree(addons_xml_root).write(xml_out, encoding="utf-8", xml_declaration=True)
    
    # MD5 generálás
    with open(xml_out, "rb") as f:
        md5_hash = hashlib.md5(f.read()).hexdigest()
    with open(xml_out + ".md5", "w") as f:
        f.write(md5_hash)
    print(f"XML és MD5 kész. Hash: {md5_hash}")

def format_size(size_bytes):
    if size_bytes is None: return "--"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024: return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

def generate_indexes():
    """Minden mappába index.html generálása (Kodi navigációhoz)"""
    print("Index.html fájlok generálása...")
    for current_dir, dirs, files in os.walk(ROOT_DIR):
        # Szűrés
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in IGNORE]
        files = [f for f in files if not f.startswith('.') and f not in IGNORE and f != 'index.html']

        rel_path = os.path.relpath(current_dir, ROOT_DIR)
        display_path = "/" if rel_path == "." else f"/{rel_path.replace(os.path.sep, '/')}"

        # HTML fejléc
        html_content = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
        <title>Index of {display_path}</title>
        <style>
            body {{ font-family: sans-serif; margin: 2em; background: #f5f5f5; }}
            table {{ border-collapse: collapse; width: 100%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
            th, td {{ border-bottom: 1px solid #ddd; padding: 12px; text-align: left; }}
            th {{ background-color: #eee; }}
            a {{ text-decoration: none; color: #0066cc; font-weight: bold; }}
            .dir {{ color: #e67e22; }}
        </style></head><body>
        <h1>Index of {display_path}</h1>
        <table><tr><th>Név</th><th>Méret</th><th>Módosítva</th></tr>"""

        # Vissza gomb (kivéve a főkönyvtárban)
        if rel_path != ".":
            html_content += '<tr><td><a href="../">.. (Vissza)</a></td><td>--</td><td>--</td></tr>'

        # Mappák listázása
        for d in sorted(dirs):
            d_path = os.path.join(current_dir, d)
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(d_path)).strftime('%Y-%m-%d %H:%M')
            html_content += f'<tr><td class="dir"><a href="{d}/">{d}/</a></td><td>--</td><td>{mtime}</td></tr>'

        # Fájlok listázása
        for f in sorted(files):
            f_path = os.path.join(current_dir, f)
            size = format_size(os.path.getsize(f_path))
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f_path)).strftime('%Y-%m-%d %H:%M')
            html_content += f'<tr><td><a href="{f}">{f}</a></td><td>{size}</td><td>{mtime}</td></tr>'

        html_content += "</table></body></html>"

        with open(os.path.join(current_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(html_content)

if __name__ == "__main__":
    generate_addons()
    generate_indexes()
    print("\nSikeresen lefutott minden! Most jöhet a git push.")
    time.sleep(0.5) # Biztonsági várakozás a korábbi kérésednek megfelelően