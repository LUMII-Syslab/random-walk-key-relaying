#! /bin/bash

set -ex

cd cpp
make
./build/hops -s MAR -t TIR -w HS -e ../graphs/geant/edges.csv -n 256 --record-paths
