# read from data/effs_tputs.log
# for each graph
# for each walk variant, extract
# 1. assumed efficiencies without loop erasure
# 2. true efficiencies without loop erasure
# 3. assumed efficiencies with loop erasure
# 4. true efficiencies with loop erasure

# No need to use re.compile -- just use re.search directly!

import re

with open("data/effs_tputs.log", "r") as f:
    lines = list(f.readlines())

    for key in [
        # "assm_eff_dont_erase_loops_mean",
        # "true_eff_dont_erase_loops_median",
        # "assm_eff_erase_loops_mean",
        # "true_eff_erase_loops_median",
        "tput_mean"
    ]:
        search_key = key
        print(f"search_key={search_key}")
        for graph in ["NSFNet", "GÉANT", "Generated"]:
            for variant in ["NB", "LRV", "NC", "HS"]:
                values = []
                for line in lines:
                    if variant not in line or graph not in line:
                        continue
                    match = re.search(f"{search_key}=([0-9.]+)", line)
                    if match is None:
                        continue
                    value = float(match.group(1))
                    values.append(value)
                assert len(values) == 1
                value = values[0]
                print(f"{graph} {variant} {value/1000:.3g}")
        print()
