from dataclasses import dataclass
from typing import Optional

@dataclass
class Domain:
    """Represents a continuous segment of amino acids within a chain"""
    chain_id: str
    start: int
    end: int
    name: Optional[str] = None

    def __post_init__(self):
        if self.start > self.end:
            self.start, self.end = self.end, self.start 