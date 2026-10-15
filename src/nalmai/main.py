from __future__ import annotations

import uvicorn

from nalmai.config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "nalmai.web:create_app",
        factory=True,
        host="127.0.0.1",
        port=settings.local_api_port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
