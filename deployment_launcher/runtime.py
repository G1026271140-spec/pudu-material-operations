from __future__ import annotations

from pathlib import Path
from typing import Callable

from .app import config_from_current_install
from .plan import _install_tasks
from .prerequisites import ensure_prerequisites, environment_with_prerequisites


def synchronize_current_runtimes(root: Path, progress: Callable[[str], None] = print) -> None:
    config = config_from_current_install(root)
    paths = ensure_prerequisites(progress)
    _install_tasks(root, config, environment_with_prerequisites(paths), progress)
