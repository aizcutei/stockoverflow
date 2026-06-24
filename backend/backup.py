"""SQLite database backup utility."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("stockoverflow")

BACKUP_DIR = Path(__file__).resolve().parent.parent / "data" / "backups"
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "stocks.db"


def create_backup() -> dict:
    """Create a timestamped backup of the SQLite database."""
    if not DB_PATH.exists():
        return {"error": "Database file not found"}

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"stocks_{timestamp}.db"

    try:
        shutil.copy2(DB_PATH, backup_path)
        size_mb = backup_path.stat().st_size / (1024 * 1024)

        # cleanup old backups (keep last 10)
        backups = sorted(BACKUP_DIR.glob("stocks_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[10:]:
            old.unlink()
            logger.info("Removed old backup: %s", old.name)

        return {
            "status": "ok",
            "file": str(backup_path),
            "size_mb": round(size_mb, 2),
            "timestamp": timestamp,
            "total_backups": min(len(backups), 10),
        }
    except Exception as e:
        return {"error": str(e)}


def list_backups() -> list[dict]:
    """List all available backups."""
    if not BACKUP_DIR.exists():
        return []

    backups = sorted(BACKUP_DIR.glob("stocks_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "file": b.name,
            "size_mb": round(b.stat().st_size / (1024 * 1024), 2),
            "created": datetime.fromtimestamp(b.stat().st_mtime).isoformat()[:19],
        }
        for b in backups
    ]


def restore_backup(filename: str) -> dict:
    """Restore database from a backup file."""
    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        return {"error": f"Backup not found: {filename}"}

    try:
        # create a backup of current before restore
        create_backup()
        shutil.copy2(backup_path, DB_PATH)
        return {"status": "restored", "file": filename}
    except Exception as e:
        return {"error": str(e)}
