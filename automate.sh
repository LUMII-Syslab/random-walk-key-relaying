#! /bin/bash

make run EDGE=graphs/geant/edges.csv WALK=R
mv out2/hops.csv out2/geant_r_hops.csv

make run EDGE=graphs/nsfnet/edges.csv WALK=R
mv out2/hops.csv out2/nsfnet_r_hops.csv

make run EDGE=graphs/secoqc/edges.csv WALK=R
mv out2/hops.csv out2/secoqc_r_hops.csv

make run EDGE=graphs/geant/edges.csv WALK=NB
mv out2/hops.csv out2/geant_nb_hops.csv

make run EDGE=graphs/nsfnet/edges.csv WALK=NB
mv out2/hops.csv out2/nsfnet_nb_hops.csv

make run EDGE=graphs/secoqc/edges.csv WALK=NB
mv out2/hops.csv out2/secoqc_nb_hops.csv

make run EDGE=graphs/geant/edges.csv WALK=LRV
mv out2/hops.csv out2/geant_lrv_hops.csv

make run EDGE=graphs/nsfnet/edges.csv WALK=LRV
mv out2/hops.csv out2/nsfnet_lrv_hops.csv

make run EDGE=graphs/secoqc/edges.csv WALK=LRV
mv out2/hops.csv out2/secoqc_lrv_hops.csv
