translations = {
    "lrv_nc_eff": "$\\eta$",
    "lrv_tput": "$\\overline{T}$",
    "shortest": "$d$",
    "lrv_max_vis_prob": "$X$",
    "lrv_max_vis_node": "$X_v$",
    "node_conn": "$C$",
    "lrv_hops": "$\\overline{H}$",
    "source": "$s$",
    "target": "$t$",
    "lrv_q2_hops": "$\\widetilde{H}$",
    "lrv_inflation": "$\\phi$",
    "lrv_infl_plus": "$\\phi^+$",
    "node_count": "$n$",
    "avg_tput": "$T$",
    "avg_hops": "$H$"
}

expansions = {
    "lrv_nc_eff": "secure throughput efficiency",
    "lrv_hops": "mean hop count",
    "lrv_q2_hops": "median hop count",
    "lrv_tput": "estimated throughput",
    "lrv_inflation": "route inflation",
    "lrv_infl_plus": "route inflation via median",
    "node_count": "number of nodes",
    "avg_tput": "throughput average",
    "avg_hops": "hop count average",
}

def get_axis_label(key: str) -> str:
    if key not in expansions:
        return translations[key]
    return f"{translations[key]} ({expansions[key]})"