import math
import matplotlib.pyplot as plt

_tail_cache = {}


def _binomial_tail_probs(total_chunks, prob_good):
    cache_key = (total_chunks, prob_good)
    if cache_key in _tail_cache:
        return _tail_cache[cache_key]

    n = total_chunks
    p = prob_good
    q = 1.0 - p

    if p <= 0.0:
        tails = [1.0] + [0.0] * n
        _tail_cache[cache_key] = tails
        return tails
    if p >= 1.0:
        tails = [1.0] * (n + 1)
        _tail_cache[cache_key] = tails
        return tails

    log_p = math.log(p)
    log_q = math.log(q)
    log_fact_n = math.lgamma(n + 1)
    log_pmf = []
    for k in range(n + 1):
        log_nchoosek = log_fact_n - math.lgamma(k + 1) - math.lgamma(n - k + 1)
        log_pmf.append(log_nchoosek + k * log_p + (n - k) * log_q)

    max_log_pmf = max(log_pmf)
    pmf_scaled = [math.exp(lp - max_log_pmf) for lp in log_pmf]
    scale = math.exp(max_log_pmf)

    tails = [0.0] * (n + 1)
    running_scaled_sum = 0.0
    for k in range(n, -1, -1):
        running_scaled_sum += pmf_scaled[k]
        tails[k] = running_scaled_sum * scale

    _tail_cache[cache_key] = tails
    return tails


def prob(at_least_this_many_chunks_good, total_chunks, prob_good):
    return _binomial_tail_probs(total_chunks, prob_good)[at_least_this_many_chunks_good]

fig, axes = plt.subplots(2,2, figsize=(10, 10))
axes = axes.flatten()
threshold_64 = 1 - 2**-64
threshold_32 = 1 - 2**-32
for i, total_chunks in enumerate([64, 256, 1024, 4096]):
    axes[i].set_title(f"Total chunks = {total_chunks}")
    axes[i].set_xlabel("Number of good chunks")
    axes[i].set_ylabel("Probability")
    # axes[i].set_xlim(0, 128)
    axes[i].set_ylim(0, 1)
    axes[i].grid(True)
    for prob_good in [0.01, 0.05, 0.1, 0.2]:
        x = list(range(0, total_chunks + 1))
        y = [prob(i, total_chunks, prob_good) for i in x]
        (line,) = axes[i].plot(x, y, label=f"p_good = {prob_good}")
        color = line.get_color()

        x_below_64 = next((x_val for x_val, y_val in zip(x, y) if y_val < threshold_64), None)
        x_below_32 = next((x_val for x_val, y_val in zip(x, y) if y_val < threshold_32), None)

        if x_below_64 is not None:
            axes[i].axvline(x_below_64, color=color, linestyle="--", alpha=0.5)
        if x_below_32 is not None:
            axes[i].axvline(x_below_32, color=color, linestyle=":", alpha=0.7)
    axes[i].legend()
plt.tight_layout()
plt.show()

# for prob_good in [0.01, 0.05, 0.1, 0.2]:
#     x = list(range(0, 129))
#     y = [prob(i, 128, prob_good) for i in x]
#     plt.plot(x, y, label=f"p_good = {prob_good}")
# plt.legend()
# plt.show()
