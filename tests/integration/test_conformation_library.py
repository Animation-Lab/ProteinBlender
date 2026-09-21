"""Imported multi-model state storage now feeds the Morphset workflow."""
import bpy
import numpy as np
import pytest

import helpers as H
from proteinblender.core import morphsets

pytestmark = pytest.mark.integration


def test_ensemble_models_become_morphsets_without_fitting(scene, sm):
    mid = H.import_local('1d3z.pdb.gz', 'ensemble')
    library = sm.molecules[mid].object.pb_conformations
    assert len(library.states) == 10
    original = [np.array([v.co[:] for v in state.mesh.vertices]) for state in library.states]
    from test_morphsets import _set, _morph, _key
    morph = _morph(_set(), mid, model=library.states[0].uid, end_model=library.states[6].uid)
    values = morphsets.states(morph)
    start = morphsets._coordinates(values[0]['members'][0]['mesh'])
    end = morphsets._coordinates(values[-1]['members'][0]['mesh'])
    np.testing.assert_allclose(end - start, original[6] - original[0], atol=1e-6)
    for index, frame in ((0, 1), (-1, 31), (0, 61)):
        assert _key(morph, frame, index) == {'FINISHED'}
    scene.frame_set(16)
    output = morphsets.outputs(scene)[0]
    assert output.data.shape_keys.key_blocks[values[-1]['uid']].value == pytest.approx(.5)


def test_old_morph_authoring_operators_are_unregistered():
    for name in ('morph', 'create_conformation', 'edit_conformation',
                 'browse_conformations', 'capture_conformation', 'conformation_preview'):
        with pytest.raises((AttributeError, RuntimeError, KeyError)):
            getattr(bpy.ops.proteinblender, name).get_rna_type()
