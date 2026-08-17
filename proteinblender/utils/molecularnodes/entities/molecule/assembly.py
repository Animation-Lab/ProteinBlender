"""
A subpackage for reading rotation matrices and translation vectors
for biological assemblies from different file formats.

The central functions are `get_transformations_`
"""

from abc import ABCMeta, abstractmethod


class AssemblyParser(metaclass=ABCMeta):
    @abstractmethod
    def list_assemblies(self):
        """
        Return a ``list`` of ``str`` containing the available assembly
        IDs.
        """

    @abstractmethod
    def get_transformations(self, assembly_id):
        """
        Parse the necessary transformations for a given
        assembly ID.

        Return a ``list`` of transformations, each a ``dict``:

            {
                "chain_ids":     list[str],    # chains this transform applies to
                "matrix":        list[list[float]],  # 4x4 rotation + translation
                "pdb_model_num": int,          # which chain-set block it came from
            }

        The keys are not optional. ``utils.array_quaternions_from_dict``
        consumes these by name to build the transforms data object, so a
        parser returning any other shape breaks assembly building at the point
        of use rather than at the point of parsing.
        """

    @abstractmethod
    def get_assemblies(self):
        """
        Parse all the transformations for each assembly, returning a dictionary of
        key:value pairs of assembly_id:transformations. The transformations list
        comes from the `get_transformations(assembly_id)` method.

        Dictionary of all assemblies
        |     Assembly ID
        |     |   List of transformations to create biological assembly.
        |     |   |
        dict{'1', list[transformations]}

        """
