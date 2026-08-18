## Worth highlighting for R-CCS Cloud

This is a heterogeneous ~20-partition cluster — when picking a partition
for Step 5's test job, prefer one with an idle CPU-only node (e.g. `genoa`)
for a quick, uncontended demo rather than a scarce GPU partition, unless
the user specifically wants to see a GPU job.
