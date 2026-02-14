#! /bin/bash

for NODES in $(seq 3 3 99); do
    echo "processing $NODES nodes..."
    for WALK in R NB LRV; do
        python3 construct.py graphs/generated/edges.csv "$NODES"
        make run EDGE=constructed.csv WALK=$WALK
        python3 connectivity.py constructed.csv
        mkdir -p ./out/"$NODES"/"$WALK"
        mv ./out/*.csv ./out/"$NODES"/"$WALK"/
        rm constructed.csv
    done
done