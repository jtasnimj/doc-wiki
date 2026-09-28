import os
from functools import lru_cache
from pathlib import Path

import tiktoken


@lru_cache(maxsize=1)
def encoding():
    # The fixed, checksummed cl100k vocabulary ships with the wheel. No runtime download.
    os.environ["TIKTOKEN_CACHE_DIR"] = str(Path(__file__).parent / "assets" / "tiktoken")
    return tiktoken.get_encoding("cl100k_base")


def tokens(text: str) -> list[int]:
    return encoding().encode(text, disallowed_special=())
