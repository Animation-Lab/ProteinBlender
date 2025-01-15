#!/bin/bash

# Create random number once at the start
myrand=$RANDOM

rm -rf /mnt/c/Users/dlee1/Documents/PublishedBlenderAddons/ProteinBlender*
rm -rf libs/

# Run setup.py with sdist command
python setup.py sdist

mkdir -p tmp
tar -xvzf dist/proteinblender-0.1.0.tar.gz -C tmp/
cp -r blender_manifest.toml tmp/proteinblender-0.1.0/
cp -r libs tmp/proteinblender-0.1.0/

# Rename the directory to a consistent name without version
mv tmp/proteinblender-0.1.0 tmp/proteinblender

cd tmp
zip -r proteinblender.zip proteinblender/*
cp proteinblender.zip "/mnt/c/Users/dlee1/Documents/PublishedBlenderAddons/ProteinBlender_0.${myrand}.0.zip"
cd ..
rm -rf dist/* tmp/
