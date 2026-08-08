class VersionedContentService:
    def save_version(self, content: str) -> str:
        return "version-1"

    def restore_version(self, version_id: str) -> str:
        return version_id

    def list_versions(self) -> list[str]:
        return ["version-1"]

