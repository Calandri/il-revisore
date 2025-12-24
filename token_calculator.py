#!/usr/bin/env python3
"""
Token Calculator for TurboWrap agents.

Uses tiktoken BPE tokenizer (cl100k_base) for accurate token counts.
This encoding is ~70% similar to Claude's tokenizer.
"""

from pathlib import Path
from typing import NamedTuple

import tiktoken


class FileStats(NamedTuple):
    name: str
    chars: int
    words: int
    lines: int
    tokens: int  # Real BPE token count


# Cache the tokenizer
_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(file_path: Path) -> FileStats:
    """Calculate real token count for a file using tiktoken."""
    content = file_path.read_text(encoding="utf-8")

    chars = len(content)
    words = len(content.split())
    lines = content.count("\n") + 1

    # Real BPE tokenization
    tokens = len(_encoder.encode(content))

    return FileStats(
        name=file_path.name,
        chars=chars,
        words=words,
        lines=lines,
        tokens=tokens,
    )


def main():
    agents_dir = Path("agents")
    md_files = sorted(agents_dir.glob("*.md"))

    print("=" * 80)
    print("ULTRAWRAP - TOKEN CALCULATOR (tiktoken cl100k_base)")
    print("=" * 80)
    print()
    print(f"{'File':<40} {'Chars':>10} {'Words':>8} {'Lines':>7} {'Tokens':>10}")
    print("-" * 80)

    total = FileStats("TOTAL", 0, 0, 0, 0)
    stats_list = []

    for md_file in md_files:
        stats = count_tokens(md_file)
        stats_list.append(stats)

        print(
            f"{stats.name:<40} {stats.chars:>10,} {stats.words:>8,} "
            f"{stats.lines:>7,} {stats.tokens:>10,}"
        )

        total = FileStats(
            "TOTAL",
            total.chars + stats.chars,
            total.words + stats.words,
            total.lines + stats.lines,
            total.tokens + stats.tokens,
        )

    print("-" * 80)
    print(
        f"{'TOTAL':<40} {total.chars:>10,} {total.words:>8,} "
        f"{total.lines:>7,} {total.tokens:>10,}"
    )
    print("=" * 80)
    print()
    print("Tokenizer: tiktoken cl100k_base (GPT-4 compatible, ~70% similar to Claude)")
    print()

    # Sort by tokens
    print("Top files by token count:")
    max_tokens = max(s.tokens for s in stats_list) if stats_list else 1
    for i, stats in enumerate(
        sorted(stats_list, key=lambda x: x.tokens, reverse=True), 1
    ):
        bar_len = int((stats.tokens / max_tokens) * 30)
        bar = "█" * bar_len
        print(f"  {i}. {stats.name:<35} {stats.tokens:>8,} tokens {bar}")


if __name__ == "__main__":
    main()
