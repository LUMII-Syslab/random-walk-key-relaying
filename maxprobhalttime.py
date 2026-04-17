import numpy as np
import matplotlib.pyplot as plt
import signal
import tqdm
from helpers.maxprobhalttime import query_maxprob_halt_time

signal.signal(signal.SIGINT, signal.SIG_DFL)

plt.figure(figsize=(5.25, 3.5))

plt.rcParams.update(
    {
        "axes.labelsize": 14,
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "legend.fontsize": 12,
        "axes.titlesize": 14,
    }
)

WATERMARK_SZ = 256

max_consume_probs = list(np.linspace(0.01, 0.1, 10))+list(np.linspace(0.1, 0.9, 10))+list(np.linspace(0.9, 0.99, 10))
max_consume_probs = list(filter(lambda x: x < 0.9 and x > 0.1, max_consume_probs))
max_consume_probs.sort()
halt_at_keys_list = [1, 4, 16, 64, 256]
# expand colors and linestyles to cover all halt_at_keys values
colors = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
linestyles = ["-", "--", "-.", ":", (0, (3, 1, 1, 1))]

all_results = []  # list of (halt_at_keys, [list of halted times for each max_consume_prob])
for halt_at_keys in halt_at_keys_list:
    halted_times = []
    for max_consume_prob in tqdm.tqdm(max_consume_probs, desc=f"Halt={halt_at_keys}"):
        halted_times.append(
            query_maxprob_halt_time(
                max_consume_prob=float(max_consume_prob),
                halt_at_keys=int(halt_at_keys),
                watermark_sz=int(WATERMARK_SZ),
            )
        )
    all_results.append((halt_at_keys, halted_times))

# --- Drawing Phase ---
for (halt_at_keys, halted_times), color, style in zip(all_results, colors, linestyles):
    plt.plot(
        max_consume_probs,
        halted_times,
        label=f'Halt At Keys = {halt_at_keys}',
        color=color,
        linestyle=style,
        marker='o'
    )

plt.xlabel("Max Consume Probability")
plt.ylabel("Halted Time")
plt.title(f"Time vs Max Pr (Watermark = {WATERMARK_SZ})")
plt.legend()
plt.tight_layout()
plt.show()