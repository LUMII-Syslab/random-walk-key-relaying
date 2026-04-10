#pragma once

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <unordered_map>
#include <utility>
#include <vector>

/**
 * ChunkSieve row-removal procedure from the paper (Algorithm "ChunkSieve").
 *
 * Input is a boolean table: rows = chunks, columns = relay nodes;
 * table[i][j] == true iff chunk i traveled through node j.
 *
 * The sieve removes rows until every column has tick-count <= targetTicks,
 * where targetTicks is ceil(average tick count among all columns).
 */
class ChunkSieve {
public:
    struct Result {
        // Indices of rows retained after sieving (referring to the original input row order).
        std::vector<int> retained_rows;
        // targetTicks = ceil(average tick count among all columns) on the original table.
        int target_ticks = 0;
    };

    // table[row][col] must be 0/1 values.
    static Result sieve(const std::vector<std::vector<unsigned char>> &table) {
        const int r0 = static_cast<int>(table.size());
        if (r0 <= 0) throw std::runtime_error("ChunkSieve: table must have at least 1 row");
        const int c0 = static_cast<int>(table[0].size());
        if (c0 <= 0) {
            // No relay nodes in history → nothing to balance, keep all rows.
            Result out;
            out.target_ticks = 0;
            out.retained_rows.resize(r0);
            for (int i = 0; i < r0; i++) out.retained_rows[i] = i;
            return out;
        }
        for (int i = 1; i < r0; i++) {
            if (static_cast<int>(table[i].size()) != c0) throw std::runtime_error("ChunkSieve: ragged table");
        }

        // Maintain active rows set via a boolean mask.
        std::vector<unsigned char> active(static_cast<size_t>(r0), 1);
        int active_rows = r0;

        auto col_tick_counts = [&]() -> std::vector<int> {
            std::vector<int> col(static_cast<size_t>(c0), 0);
            for (int i = 0; i < r0; i++) {
                if (!active[static_cast<size_t>(i)]) continue;
                for (int j = 0; j < c0; j++) {
                    if (table[static_cast<size_t>(i)][static_cast<size_t>(j)]) col[static_cast<size_t>(j)]++;
                }
            }
            return col;
        };

        auto row_tick_count = [&](int i) -> int {
            int s = 0;
            for (int j = 0; j < c0; j++) s += (table[static_cast<size_t>(i)][static_cast<size_t>(j)] != 0);
            return s;
        };

        // targetTicks = ceil(average tick count among columns).
        std::vector<int> col0 = col_tick_counts();
        long long sum = 0;
        for (int x : col0) sum += x;
        const double avg = static_cast<double>(sum) / static_cast<double>(c0);
        const int targetTicks = static_cast<int>(std::ceil(avg));

        while (true) {
            std::vector<int> col = col_tick_counts();
            int worst_col = -1;
            int worst_ticks = targetTicks;
            for (int j = 0; j < c0; j++) {
                if (col[static_cast<size_t>(j)] > worst_ticks) {
                    worst_ticks = col[static_cast<size_t>(j)];
                    worst_col = j;
                }
            }
            if (worst_col < 0) break; // all cols <= targetTicks

            // Among rows that have a tick in worst_col, remove the one with max row tick count.
            int chosen_row = -1;
            int chosen_row_weight = -1;
            for (int i = 0; i < r0; i++) {
                if (!active[static_cast<size_t>(i)]) continue;
                if (!table[static_cast<size_t>(i)][static_cast<size_t>(worst_col)]) continue;
                int w = row_tick_count(i);
                if (w > chosen_row_weight) {
                    chosen_row_weight = w;
                    chosen_row = i;
                }
            }
            if (chosen_row < 0) {
                // Column claims to be overweight but no row has that tick → inconsistent input.
                break;
            }
            if (active_rows <= 1) break; // always keep at least one row
            active[static_cast<size_t>(chosen_row)] = 0;
            active_rows--;
        }

        Result out;
        out.target_ticks = targetTicks;
        out.retained_rows.reserve(static_cast<size_t>(active_rows));
        for (int i = 0; i < r0; i++) {
            if (active[static_cast<size_t>(i)]) out.retained_rows.push_back(i);
        }
        return out;
    }
};

