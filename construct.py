import csv
import sys

edges_csv = sys.argv[1]
out_csv = "constructed.csv"
n_limit = int(sys.argv[2])
with open(edges_csv, 'r') as f:
    reader = csv.reader(f)
    with open(out_csv, 'w') as f:
        writer = csv.writer(f)
        writer.writerow(next(reader))
        for row in reader:
            source, target = row
            if int(source) > n_limit:
                break
            else:
                # pad with zeros to make source and target 3 digits
                source, target = int(source), int(target)
                source,target = f"{source:03d}", f"{target:03d}"
                writer.writerow([source, target])