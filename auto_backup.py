import shutil, os, time
from datetime import datetime

FILES = [
    "/Users/alessiovalori/arkitect_agent/ui_app.py",
    "/Users/alessiovalori/arkitect_agent/generator.py",
    "/Users/alessiovalori/arkitect_agent/builder.py",
]
BACKUP_DIR = "/Users/alessiovalori/arkitect_agent/backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

MAX_BACKUPS = 5

while True:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for src in FILES:
        if os.path.exists(src):
            name = os.path.basename(src).replace(".py", "")
            dest = os.path.join(BACKUP_DIR, f"{name}_{ts}.py")
            shutil.copy2(src, dest)
            print(f"Backup saved: {dest}")
            existing = sorted([
                f for f in os.listdir(BACKUP_DIR)
                if f.startswith(name + "_") and f.endswith(".py")
            ])
            while len(existing) > MAX_BACKUPS:
                os.remove(os.path.join(BACKUP_DIR, existing.pop(0)))
    time.sleep(1800)
