from bpy.types import PropertyGroup
from bpy.props import BoolProperty, StringProperty, IntProperty

class Domain(PropertyGroup):
    """Represents a continuous segment of amino acids within a chain"""
    is_expanded: BoolProperty(default=False)
    chain_id: StringProperty()
    start: IntProperty()
    end: IntProperty()
    name: StringProperty()

    def __post_init__(self):
        if self.start > self.end:
            self.start, self.end = self.end, self.start 

