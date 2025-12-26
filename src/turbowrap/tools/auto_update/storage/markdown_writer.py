"""Markdown writer for FUNZIONALITA.md."""

import logging
import time
from pathlib import Path

from ..models import Functionality

logger = logging.getLogger(__name__)

FUNZIONALITA_FILENAME = "FUNZIONALITA.md"


class MarkdownWriter:
    """Writes FUNZIONALITA.md file with extracted functionalities."""

    def __init__(self, repo_path: Path):
        """Initialize writer.

        Args:
            repo_path: Path to repository root.
        """
        self.repo_path = Path(repo_path).resolve()

    def write_functionalities(self, functionalities: list[Functionality]) -> Path:
        """Write FUNZIONALITA.md with extracted functionalities.

        Args:
            functionalities: List of functionalities to write.

        Returns:
            Path to written file.
        """
        output_path = self.repo_path / FUNZIONALITA_FILENAME

        lines = [
            f"# {self.repo_path.name} - Funzionalita",
            "",
            "Documento generato automaticamente da TurboWrap Auto-Update.",
            "",
            f"**Totale funzionalita**: {len(functionalities)}",
            f"**Generato il**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        # Group by category
        categories: dict[str, list[Functionality]] = {}
        for func in functionalities:
            cat = func.category.capitalize()
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(func)

        # Table of contents
        lines.append("## Indice")
        lines.append("")
        for category in sorted(categories.keys()):
            lines.append(f"- [{category}](#{category.lower()})")
        lines.append("")

        # Each category
        for category in sorted(categories.keys()):
            funcs = categories[category]
            lines.append(f"## {category}")
            lines.append("")

            for func in sorted(funcs, key=lambda f: f.name):
                lines.append(f"### {func.name}")
                lines.append("")
                lines.append(f"**ID**: `{func.id}`")
                lines.append(f"**Maturity**: {func.maturity}")
                lines.append("")
                lines.append(func.description)
                lines.append("")

                if func.files:
                    lines.append("**File principali**:")
                    for file in func.files[:10]:
                        lines.append(f"- `{file}`")
                    lines.append("")

                if func.dependencies:
                    lines.append(
                        f"**Dipendenze**: {', '.join(f'`{d}`' for d in func.dependencies)}"
                    )
                    lines.append("")

                lines.append("---")
                lines.append("")

        # Footer
        lines.extend(
            [
                "",
                f"*Generato da TurboWrap Auto-Update - ts:{int(time.time())}*",
            ]
        )

        # Write file
        content = "\n".join(lines)
        output_path.write_text(content, encoding="utf-8")

        logger.info(f"Wrote {output_path}")
        return output_path
