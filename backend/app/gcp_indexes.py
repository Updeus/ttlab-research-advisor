from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import get_settings
from app.storage import publish_gcs_vector_generation


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish one already-built immutable vector-index generation to GCS"
    )
    parser.add_argument("index_path", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    if settings.service_role != "offline_worker":
        raise RuntimeError("Vector generation publication requires the offline worker identity")
    result = publish_gcs_vector_generation(args.index_path.resolve(), settings)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
