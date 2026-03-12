from typing import List, Optional
import os
import logging
from dataclasses import dataclass
import time
import zipfile
from datetime import datetime

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


@dataclass
class ArtifactFileInfo:
    """Artifact metadata for local/PVC-backed storage."""
    name: str
    size: int
    last_modified: str


class ArtifactsHandlerError(Exception):
    pass


class RequestIDNotFoundError(ArtifactsHandlerError):
    pass


class NoFilesFoundError(ArtifactsHandlerError):
    pass


class ArtifactsFileHandler:
    """
    File handler using local filesystem storage.
    In Kubernetes, the storage path should be backed by a PersistentVolume.
    Provides a generic artifact interface for Kubernetes/local storage.
    """

    def __init__(self):
        self.base_dir = os.getenv('ARTIFACTS_STORAGE_PATH', '/app/data/artifacts')
        self.prefix = os.getenv('ARTIFACTS_PREFIX', 'runs')
        os.makedirs(os.path.join(self.base_dir, self.prefix), exist_ok=True)
        logger.info(f"Artifacts handler initialized with storage path: {self.base_dir}")

    def _get_full_path(self, request_id: str, filename: Optional[str] = None) -> str:
        if not request_id or not isinstance(request_id, str):
            raise ValueError("Invalid request_id provided")

        path = os.path.join(self.base_dir, self.prefix, request_id)
        if filename:
            path = os.path.join(path, filename)
        return path

    def _verify_request_exists(self, request_id: str) -> bool:
        try:
            full_path = self._get_full_path(request_id)
            return os.path.isdir(full_path) and any(os.scandir(full_path))
        except Exception as e:
            raise ArtifactsHandlerError(f"Error checking request: {str(e)}")

    def has_artifacts(self, request_id: str) -> bool:
        """Check if any artifact file exists for a request without creating archives."""
        try:
            full_path = self._get_full_path(request_id)
            if not os.path.isdir(full_path):
                return False
            for entry in os.scandir(full_path):
                if entry.is_file():
                    return True
            return False
        except Exception as e:
            raise ArtifactsHandlerError(f"Error checking artifacts: {str(e)}")

    def _check_existing_archive(self, request_id: str) -> Optional[str]:
        try:
            full_path = self._get_full_path(request_id)
            if not os.path.isdir(full_path):
                return None

            archives = [
                f for f in os.listdir(full_path)
                if f.endswith('.zip')
            ]

            if archives:
                latest = max(
                    archives,
                    key=lambda f: os.path.getmtime(os.path.join(full_path, f))
                )
                return os.path.join(full_path, latest)

            return None
        except Exception as e:
            raise ArtifactsHandlerError(f"Error checking archives: {str(e)}")

    def list_files(self, request_id: str) -> List[ArtifactFileInfo]:
        try:
            if not self._verify_request_exists(request_id):
                raise RequestIDNotFoundError(f"Request ID {request_id} not found")

            full_path = self._get_full_path(request_id)
            files = []

            for entry in os.scandir(full_path):
                if entry.is_file() and not entry.name.endswith('.zip'):
                    stat = entry.stat()
                    files.append(ArtifactFileInfo(
                        name=entry.name,
                        size=stat.st_size,
                        last_modified=datetime.fromtimestamp(stat.st_mtime).isoformat()
                    ))

            if not files:
                raise NoFilesFoundError(f"No files found for request ID {request_id}")

            return files
        except (RequestIDNotFoundError, NoFilesFoundError):
            raise
        except Exception as e:
            raise ArtifactsHandlerError(f"Error listing files: {str(e)}")

    def _create_archive(self, request_id: str, files: List[ArtifactFileInfo]) -> str:
        """Create a ZIP archive of all files"""
        try:
            request_dir = self._get_full_path(request_id)
            archive_name = f"{request_id}_archive_{int(time.time())}.zip"
            archive_path = os.path.join(request_dir, archive_name)

            with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for file_info in files:
                    file_path = os.path.join(request_dir, file_info.name)
                    zip_file.write(file_path, file_info.name)

            return archive_path
        except Exception as e:
            raise ArtifactsHandlerError(f"Error creating archive: {str(e)}")

    def get_download_url(self, request_id: str, expiry: int = 3600) -> str:
        """
        Returns the filesystem path to a downloadable archive.
        The API route should serve this file via FileResponse.
        """
        try:
            if not self._verify_request_exists(request_id):
                raise RequestIDNotFoundError(f"Request ID {request_id} not found")

            archive_path = self._check_existing_archive(request_id)

            if not archive_path:
                files = self.list_files(request_id)
                archive_path = self._create_archive(request_id, files)

            return archive_path

        except (NoFilesFoundError, RequestIDNotFoundError):
            raise
        except Exception as e:
            raise ArtifactsHandlerError(f"Error creating download: {str(e)}")

    def save_file(self, request_id: str, filename: str, content: bytes) -> str:
        """Save a file to the artifacts storage"""
        try:
            request_dir = self._get_full_path(request_id)
            os.makedirs(request_dir, exist_ok=True)

            file_path = os.path.join(request_dir, filename)
            with open(file_path, 'wb') as f:
                f.write(content)

            return file_path
        except Exception as e:
            raise ArtifactsHandlerError(f"Error saving file: {str(e)}")
