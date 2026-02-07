import hashlib
import os
import zipfile
import time
from xml.etree import ElementTree

# Beállítások - Bővítve, hogy ne olvasson bele felesleges dolgokba
IGNORE = [".git", ".github", ".gitignore", "zips", "generate.py", "venv", "__pycache__", ".vscode"]

def generate():
    root = os.getcwd()
    zips_path = os.path.join(root, "zips")
    
    if not os.path.exists(zips_path):
        os.makedirs(zips_path)

    addons_xml_root = ElementTree.Element('addons')
    
    # Csak azokat a mappákat nézzük, amikben tényleg van addon.xml
    folders = [f for f in os.listdir(root) if os.path.isdir(f) and f not in IGNORE]
    
    for folder in folders:
        xml_path = os.path.join(root, folder, "addon.xml")
        if not os.path.exists(xml_path):
            continue

        # XML beolvasása
        tree = ElementTree.parse(xml_path)
        addon_node = tree.getroot()
        addon_id = addon_node.get('id')
        version = addon_node.get('version')

        # 1. ZIP létrehozása - JAVÍTOTT ÚTVONALKEZELÉS
        addon_zip_dir = os.path.join(zips_path, addon_id)
        if not os.path.exists(addon_zip_dir):
            os.makedirs(addon_zip_dir)
            
        zip_name = f"{addon_id}-{version}.zip"
        zip_file_path = os.path.join(addon_zip_dir, zip_name)
        
        with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as z:
            addon_folder_path = os.path.join(root, folder)
            for r, d, files in os.walk(addon_folder_path):
                for f in files:
                    abs_path = os.path.join(r, f)
                    # Itt a trükk: a ZIP-en belül a struktúra a mappa nevével kezdődjön
                    rel_path = os.path.join(folder, os.path.relpath(abs_path, addon_folder_path))
                    z.write(abs_path, rel_path)

        # 2. XML hozzáadása a gyűjtőhöz
        addons_xml_root.append(addon_node)
        print(f"Kész: {addon_id} v{version}")

    # Mentés a zips mappába
    xml_out = os.path.join(zips_path, "addons.xml")
    
    # Szép formázás (indent) nélkül a Kodi néha finnyás, de a lényeg az utf-8
    ElementTree.ElementTree(addons_xml_root).write(xml_out, encoding="utf-8", xml_declaration=True)
    
    # MD5 generálás
    with open(xml_out, "rb") as f:
        md5_hash = hashlib.md5(f.read()).hexdigest()
    with open(xml_out + ".md5", "w") as f:
        f.write(md5_hash)

    print(f"Generálás kész! MD5: {md5_hash}")
    # Biztonsági várakozás
    time.sleep(0.5)

if __name__ == "__main__":
    generate()