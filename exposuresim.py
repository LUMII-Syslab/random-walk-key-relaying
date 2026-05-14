from readgraphcsv import read_graph

geant = read_graph('geant')
nodes = list(geant.nodes())

for a in nodes:
    for b in nodes:
        if b == a: continue
        for c in nodes:
            if c == a or c == b: continue
            if sorted([a, b, c]) != [a, b, c]: continue
            print(a,b,c)