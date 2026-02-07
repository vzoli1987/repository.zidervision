import hashlib
import os
import zipfile
import time
from xml.etree import ElementTree

# Beállítások
IGNORE = [".git", ".github", ".gitignore", "zips", "generate.py", "venv"]

def generate():
    root = os.getcwd()
    zips_path = os.path.join(root, "zips")
    
    if not os.path.exists(zips_path):
        os.makedirs(zips_path)

    addons_xml_root = ElementTree.Element('addons')
    
    # Végigmegyünk a mappákon
    folders = [f for f in os.listdir(root) if os.path.isdir(f) and f not in IGNORE]
    
    for folder in folders:
        xml_path = os.path.join(root, folder, "addon.xml")
        if not os.path.exists(xml_path):
            continue

        # XML beolvasása az ID és verzió miatt
        tree = ElementTree.parse(xml_path)
        addon_node = tree.getroot()
        addon_id = addon_node.get('id')
        version = addon_node.get('version')

        # 1. ZIP létrehozása (Ezt a Kodi kéri, a script megcsinálja helyetted!)
        addon_zip_dir = os.path.join(zips_path, addon_id)
        if not os.path.exists(addon_zip_dir):
            os.makedirs(addon_zip_dir)
            
        zip_name = f"{addon_id}-{version}.zip"
        with zipfile.ZipFile(os.path.join(addon_zip_dir, zip_name), 'w', zipfile.ZIP_DEFLATED) as z:
            for r, d, files in os.walk(os.path.join(root, folder)):
                for f in files:
                    abs_path = os.path.join(r, f)
                    rel_path = os.path.relpath(abs_path, root)
                    z.write(abs_path, rel_path)

        # 2. XML hozzáadása a gyűjtőhöz
        addons_xml_root.append(addon_node)
        print(f"Kész: {addon_id} v{version}")

    # Mentés
    xml_out = os.path.join(zips_path, "addons.xml")
    ElementTree.ElementTree(addons_xml_root).write(xml_out, encoding="utf-8", xml_declaration=True)
    
    # MD5 generálás
    with open(xml_out, "rb") as f:
        md5_hash = hashlib.md5(f.read()).hexdigest()
    with open(xml_out + ".md5", "w") as f:
        f.write(md5_hash)

    # Biztonsági várakozás a szerver miatt (ahogy kérted)
    print("Várakozás 0.5 másodpercig...")
    time.sleep(0.5)

if __name__ == "__main__":
    generate()