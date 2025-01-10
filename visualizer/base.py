from abc import ABC, abstractmethod
from enum import Enum
from mathutils import Vector

class RenderStyle(Enum):
    BALL_AND_STICK = 'ball_stick'
    RIBBON = 'ribbon'
    SPHERES = 'spheres'
    CARTOON = 'cartoon'
    SURFACE = 'surface'
    HIDDEN = 'hidden'

class ProteinVisualizer(ABC):
    def __init__(self):
        self.scale = Vector((1.0, 1.0, 1.0))
        self.center_of_mass = Vector((0.0, 0.0, 0.0))
        self.rotation = Vector((0.0, 0.0, 0.0))
        self.style = RenderStyle.BALL_AND_STICK
        
    @abstractmethod
    def create_model(self, protein, style=None, position=None, scale=None, rotation=None):
        """Create the visual representation of the protein."""
        pass
    
    @abstractmethod
    def remove_model(self):
        """Remove the visual representation."""
        pass
    
    @abstractmethod
    def select_chain(self, chain_id):
        """Select a specific chain in the protein."""
        pass
    
    @abstractmethod
    def select_residue(self, chain_id, residue_name, residue_num):
        """Select a specific residue in the protein."""
        pass 