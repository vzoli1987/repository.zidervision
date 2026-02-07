import hashlib
import os
import zipfile
import time
from xml.etree import ElementTree

# Beállítások
IGNORE = [".git", ".github", ".gitignore", "zips", "generate.py", "venv", "__pycache__", ".vscode", "index.html"]

def generate():
    root = os.getcwd()
    zips_path = os.path.join(root, "zips")
    
    if not os.path.exists(zips_path):
        os.makedirs(zips_path)

    addons_xml_root = ElementTree.Element('addons')
    
    # Csak azokat a mappákat nézzük, amikben tényleg van addon.xml
    folders = [f for f in os.listdir(root) if os.path.isdir(f) and f not in IGNORE]
    
    zip_list = [] # Itt gyűjtjük a ZIP-eket az index.html-hez

    for folder in folders:
        xml_path = os.path.join(root, folder, "addon.xml")
        if not os.path.exists(xml_path):
            continue

        # XML beolvasása
        tree = ElementTree.parse(xml_path)
        addon_node = tree.getroot()
        addon_id = addon_node.get('id')
        version = addon_node.get('version')

        # 1. ZIP létrehozása
        addon_zip_dir = os.path.join(zips_path, addon_id)
        if not os.path.exists(addon_zip_dir):
            os.makedirs(addon_zip_dir)
            
        zip_name = f"{addon_id}-{version}.zip"
        zip_file_path = os.path.join(addon_zip_dir, zip_name)
        
        # Elmentjük a listába az index.html-hez
        zip_list.append(f"zips/{addon_id}/{zip_name}")

        with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as z:
            addon_folder_path = os.path.join(root, folder)
            for r, d, files in os.walk(addon_folder_path):
                for f in files:
                    abs_path = os.path.join(r, f)
                    rel_path = os.path.join(folder, os.path.relpath(abs_path, addon_folder_path))
                    z.write(abs_path, rel_path)

        # 2. XML hozzáadása a gyűjtőhöz
        addons_xml_root.append(addon_node)
        print(f"Kész: {addon_id} v{version}")

    # Mentés a zips mappába
    xml_out = os.path.join(zips_path, "addons.xml")
    ElementTree.ElementTree(addons_xml_root).write(xml_out, encoding="utf-8", xml_declaration=True)
    
    # MD5 generálás
    with open(xml_out, "rb") as f:
        md5_hash = hashlib.md5(f.read()).hexdigest()
    with open(xml_out + ".md5", "w") as f:
        f.write(md5_hash)

    # --- INDEX.HTML GENERÁLÁSA ---
    index_path = os.path.join(root, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write('<html><head><meta charset="UTF-8"><title>ZiderVision Repo</title>')
        f.write('<style>body{font-family:sans-serif;margin:2em;} td{padding:8px;border-bottom:1px solid #ddd;} a{text-decoration:none;color:#0066cc;font-weight:bold;}</style></head>')
        f.write('<body><h1>ZiderVision Repository Index</h1><table>')
        f.write('<tr><th>Elérhető fájlok</th></tr>')
        for zip_rel_path in zip_list:
            file_name = os.path.basename(zip_rel_path)
            f.write(f'<tr><td><a href="{zip_rel_path}">{file_name}</a></td></tr>')
        f.write('</table></body></html>')
    # ------------------------------

    print(f"Generálás kész! MD5: {md5_hash}")
    print("Sikeresen legenerálva: index.html")
    
    # Biztonsági várakozás a korábbi kérésednek megfelelően
    time.sleep(0.5)

if __name__ == "__main__":
    generate()