#! /bin/bash

set -ex

cd cpp
make ./build/scouted
RUN_NAME="scouted-geant-1-max-b-t"

./build/scouted \
    -S MAR \
    -e ../graphs/geant/edges.csv \
    --verbose \
    --halt-at-keys 128 \
    --v-conn-cartel-size \
    --v-conn-csv ../graphs/geant/conn.csv \
    --block-chunks 32 \
    | tee ../data/${RUN_NAME}.log | grep Halted

