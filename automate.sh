#! /bin/bash

make run EDGE=graphs/geant/edges.csv
mv out2/throughput.csv out2/geant_r_throughput.csv

make run EDGE=graphs/nsfnet/edges.csv
mv out2/throughput.csv out2/nsfnet_r_throughput.csv

make run EDGE=graphs/secoqc/edges.csv
mv out2/throughput.csv out2/secoqc_r_throughput.csv
