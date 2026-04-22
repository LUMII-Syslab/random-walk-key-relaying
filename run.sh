#! /bin/bash

set -ex

cd cpp
make ./build/scouted

./build/scouted \
    -S MAR \
    -e ../graphs/geant/edges.csv \
    --verbose \
    --v-conn-cartel-size \
    --v-conn-csv ../graphs/geant/conn.csv \
    --block-chunks 32 \

