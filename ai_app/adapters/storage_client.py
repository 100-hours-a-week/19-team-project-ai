"""Storage client adapter for file operations (local/S3)."""

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile


class StorageClient:
    """Wrapper for file storage operations."""

    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or os.getenv("STORAGE_PATH", "./uploads"))
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _generate_file_id(self) -> str:
        """Generate unique file ID."""
        return f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    async def save_file(self, file: UploadFile, subdirectory: str = "resumes") -> dict:
        """
        Save uploaded file to storage.

        Returns:
            dict with file_id, path, filename, size
        """
        file_id = self._generate_file_id()
        save_dir = self.base_path / subdirectory
        save_dir.mkdir(parents=True, exist_ok=True)

        # Preserve original extension
        original_filename = file.filename or "unknown"
        extension = Path(original_filename).suffix or ".pdf"
        saved_filename = f"{file_id}{extension}"
        file_path = save_dir / saved_filename

        # Save file
        content = await file.read()
        file_path.write_bytes(content)

        return {
            "file_id": file_id,
            "path": str(file_path),
            "filename": original_filename,
            "size": len(content),
        }

    def get_file_path(self, file_id: str, subdirectory: str = "resumes") -> Path | None:
        """Get file path by ID."""
        save_dir = self.base_path / subdirectory

        # Find file with matching ID prefix
        for file_path in save_dir.iterdir():
            if file_path.stem.startswith(file_id) or file_id in file_path.stem:
                return file_path

        return None

    def read_file(self, file_path: str | Path) -> bytes:
        """Read file content."""
        return Path(file_path).read_bytes()

    def delete_file(self, file_path: str | Path) -> bool:
        """Delete a file."""
        path = Path(file_path)
        if path.exists():
            path.unlink()
            return True
        return False

    def file_exists(self, file_path: str | Path) -> bool:
        """Check if file exists."""
        return Path(file_path).exists()


# Singleton instance
_storage_client: StorageClient | None = None


def get_storage_client() -> StorageClient:
    """Get or create storage client singleton."""
    global _storage_client
    if _storage_client is None:
        _storage_client = StorageClient()
    return _storage_client
