#! /bin/bash

for NODES in $(seq 3 3 99); do
    echo "processing $NODES nodes..."
    python3 construct.py graphs/generated/edges.csv "$NODES"

    for WALK in R NB LRV; do
        (
            OUT_DIR="./out/$NODES/$WALK"
            mkdir -p "$OUT_DIR.tmp"
            make run EDGE=constructed.csv WALK=$WALK OUT_DIR="$OUT_DIR.tmp"
            python3 connectivity.py constructed.csv "$OUT_DIR.tmp"
            mkdir -p "$OUT_DIR"
            mv "$OUT_DIR.tmp"/* "$OUT_DIR/"
            rm -rf "$OUT_DIR.tmp"
        ) &
    done

    wait
    rm -f constructed.csv
done