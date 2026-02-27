import hashlib
import os
import shutil
import zipfile
import time
import datetime
import subprocess  # Új modul a Git parancsokhoz
from xml.etree import ElementTree

# --- Beállítások ---
IGNORE = [".git", ".github", ".gitignore", "zips", "generate.py", "upload.bat", "upload.sh", "venv", "__pycache__", ".vscode", "index.html", ".DS_Store", "thumbs.db"]
ROOT_DIR = os.getcwd()

def clean_binaries():
    """Törli a felesleges Python szemét fájlokat"""
    for parent, dirnames, filenames in os.walk(ROOT_DIR):
        for fn in filenames:
            if fn.lower().endswith(("pyo", "pyc")):
                try: os.remove(os.path.join(parent, fn))
                except: pass
        for d in dirnames:
            if "__pycache__" in d.lower():
                try: shutil.rmtree(os.path.join(parent, d))
                except: pass

def generate_repository():
    """ZIP csomagolás, XML és MD5 generálás a zips mappába ÉS a főkönyvtárba"""
    zips_path = os.path.join(ROOT_DIR, "zips")
    if not os.path.exists(zips_path):
        os.makedirs(zips_path)

    addons_root = ElementTree.Element('addons')
    folders = [f for f in os.listdir(ROOT_DIR) if os.path.isdir(f) and f not in IGNORE and f != "zips"]

    found_any = False
    for folder in folders:
        xml_path = os.path.join(ROOT_DIR, folder, "addon.xml")
        if not os.path.exists(xml_path):
            continue

        try:
            tree = ElementTree.parse(xml_path)
            addon_node = tree.getroot()
            addon_id = addon_node.get('id')
            version = addon_node.get('version')

            dest_folder = os.path.join(zips_path, addon_id)
            if not os.path.exists(dest_folder): os.makedirs(dest_folder)

            zip_name = f"{addon_id}-{version}.zip"
            zip_path = os.path.join(dest_folder, zip_name)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
                addon_dir = os.path.join(ROOT_DIR, folder)
                for root, _, files in os.walk(addon_dir):
                    for f in files:
                        if any(x in f for x in IGNORE): continue
                        abs_p = os.path.join(root, f)
                        rel_p = os.path.join(addon_id, os.path.relpath(abs_p, addon_dir))
                        z.write(abs_p, rel_p)

            for meta_f in ["addon.xml", "icon.png", "fanart.jpg", "fanart.png"]:
                src_meta = os.path.join(ROOT_DIR, folder, meta_f)
                if os.path.exists(src_meta):
                    shutil.copy(src_meta, os.path.join(dest_folder, meta_f))

            addons_root.append(addon_node)
            found_any = True
            print(f"[OK] {addon_id} v{version} hozzáadva.")
        except Exception as e:
            print(f"[HIBA] Hiba a {folder} feldolgozásakor: {e}")

    if found_any:
        # XML formázása
        if hasattr(ElementTree, 'indent'):
            ElementTree.indent(addons_root, space="    ")
        
        # 1. Mentés a zips mappába (A Kodi innen olvassa az URL alapján)
        xml_zips = os.path.join(zips_path, "addons.xml")
        tree_out = ElementTree.ElementTree(addons_root)
        tree_out.write(xml_zips, encoding="utf-8", xml_declaration=True)
        
        # 2. Mentés a FŐ mappába (Hogy ott is friss legyen)
        xml_root = os.path.join(ROOT_DIR, "addons.xml")
        tree_out.write(xml_root, encoding="utf-8", xml_declaration=True)
        
        # MD5 generálása a zips mappába
        with open(xml_zips, "rb") as f:
            md5_h = hashlib.md5(f.read()).hexdigest()
        
        with open(xml_zips + ".md5", "w", encoding="utf-8") as f:
            f.write(md5_h)
            
        # MD5 másolása a fő mappába is
        shutil.copy(xml_zips + ".md5", os.path.join(ROOT_DIR, "addons.xml.md5"))
        
        print(f"\n[KÉSZ] addons.xml és MD5 frissítve mindenhol. Hash: {md5_h}")
    else:
        print("\n[!] Nem találtam egyetlen érvényes addont sem!")

def generate_indexes():
    """Kodi-kompatibilis HTML indexek gyártása"""
    for cur, dirs, files in os.walk(ROOT_DIR):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in IGNORE]
        files = [f for f in files if not f.startswith('.') and f not in IGNORE and f != 'index.html']
        rel = os.path.relpath(cur, ROOT_DIR)
        title = "/" if rel == "." else f"/{rel.replace(os.path.sep, '/')}"
        h = f"<html><head><title>Index of {title}</title></head><body><h1>Index of {title}</h1><hr><pre>"
        if rel != ".": h += '<a href="../">../</a>\n'
        for d in sorted(dirs): h += f'<a href="{d}/">{d}/</a>\n'
        for f in sorted(files): h += f'<a href="{f}">{f}</a>\n'
        h += "</pre><hr></body></html>"
        with open(os.path.join(cur, "index.html"), "w", encoding="utf-8") as f:
            f.write(h)

def git_push():
    """Git műveletek végrehajtása"""
    try:
        print("\n--- Git Feltöltés ---")
        confirm = input("Szeretnéd feltölteni a változásokat GitHubra? (i/n): ")
        if confirm.lower() != 'i':
            print("Feltöltés megszakítva.")
            return

        commit_msg = input("Commit üzenet (üresen hagyva automata dátum): ")
        if not commit_msg:
            commit_msg = f"Repo update: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"

        # Git parancsok futtatása
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "push"], check=True)
        print("\n[SIKER] Minden fent van GitHubon!")
    except Exception as e:
        print(f"\n[HIBA] Git hiba történt: {e}")

if __name__ == "__main__":
    print("--- Repository Karbantartás Indítása ---")
    clean_binaries()
    generate_repository()
    generate_indexes()
    print("\nGenerálás sikeres!")
    
    time.sleep(0.5) # A kért várakozás
    git_push()