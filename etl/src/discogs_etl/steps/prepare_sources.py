"""Step 1 — Prepare sources: validate releases.xml exists, record size + checksum."""
from __future__ import annotations

from ..io.file_utils import sha256_file
from ..pipeline.context import RunContext
from ..pipeline.manifest import Manifest


class PrepareSourcesStep:
    name = "prepare_sources"

    def outputs_exist(self, ctx: RunContext) -> bool:
        # Pure manifest mutation; nothing on disk to check.
        return False

    def delete_outputs(self, ctx: RunContext) -> None:
        pass

    def run(self, ctx: RunContext, manifest: Manifest) -> None:
        path = ctx.releases_xml_path()
        if not path.exists():
            raise FileNotFoundError(f"releases.xml not found at {path}")
        size = path.stat().st_size
        ctx.logger.info("prepare_sources: hashing %s (%d bytes)", path, size)
        checksum = sha256_file(path)
        manifest.record_source_file("releases", path=path, size_bytes=size, checksum=checksum)
