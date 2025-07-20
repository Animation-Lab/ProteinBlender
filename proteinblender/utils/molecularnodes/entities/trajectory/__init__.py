try:
    from . import selections
except ImportError as e:
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Failed to import selections module: {e}")
    selections = None

from . import ui
from .ui import load
from .trajectory import Trajectory

CLASSES = ui.CLASSES

__all__ = ['selections', 'ui', 'load', 'Trajectory', 'CLASSES']