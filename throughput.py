"""
Measures transmission throughput of random walk key relaying in a QKD network.

First of all, source node "s" wants to send a packet to destination node "t".
Actually, let's assume that node "s" wants to send a continous infinite stream
of packets to node "t". 

When a node receives a packet with the key to relay, it will put in a queue
for a specific neighbouring node. The queue is FIFO. When the relay node has 
spare capacity amounting to the size of the relayed key, it will pop the packet
and send it to the neighbouring node. There is one more condition:
the neighbouring node accepts the packet and it does so only if it has spare
space in its buffer.

The procedure works as follows.

Configurable parameters:
1. key size (after ecc information and privacy amplification)
2. buffer size of each node
3. secure key generation rate (bits/s)

My hypothesis is that the throughput will converge to a constant value.

Event brainstorming:
1. can send the key (engouh key material for otp; and buffer of neighbour is empty)
2. buffer got empty -> neighbour that waited the longest sends the key
3. enough key material for otp
4. pop key
5. receive key (now + LATENCY at destination node)
"""

import random
from heapq import heappush as push, heappop as pop
import sys
import csv
from collections import defaultdict
from random import choice

random.seed(42)

KEY_SIZE = 2 # bits
NODE_BUFF_SZ = 10000
LINK_BUFF_SZ = 10 # reservable bits stored at each of 2 endpoints of the link
LINKS_EMPTY_AT_START = True
QKD_SKR = 1 # secure key generation rate (bits/s)
LATENCY = 0.01 # seconds

class Node:
    def __init__(self, name: str):
        self.name = name
        self.waiting = [] # nodes that are waiting in standby
        self.buffer_space = NODE_BUFF_SZ

class Link:
    def __init__(self, src: str, tgt: str, skr: float, latency: float):
        self.src = src
        self.tgt = tgt
        self.skr = skr
        self.latency = latency
        self.history = [] # list of (time, key_size) tuples
        self.bit_balance = 0
        if not LINKS_EMPTY_AT_START:
            self.bit_balance = LINK_BUFF_SZ
        self.last_request = 0

    def reserve(self, current_time: float, necessary_bits: int) -> float:
        '''
        Reserves necessary bits for the link. Returns seconds until the link has enough material.
        To calculate the time we go through the history of the link.
        '''
        if current_time < self.last_request:
            raise ValueError(f"current_time {current_time} is less than last_request {self.last_request}")
        if necessary_bits > LINK_BUFF_SZ:
            raise ValueError(f"necessary_bits {necessary_bits} is greater than LINK_BUFF_SZ {LINK_BUFF_SZ}")
        time_delta = current_time - self.last_request
        self.bit_balance += time_delta * self.skr
        # bit_balance + waiting_time * skr >= necessary_bits
        waiting_time = max(0, (necessary_bits - self.bit_balance) / self.skr)
        self.last_request = current_time
        self.bit_balance -= necessary_bits
        return waiting_time

def main(adj_list: defaultdict[str, list[str]], S: str, T: str, nodes: dict[str, Node], edges: dict[tuple[str, str], Link]):
    def get_edge(src: str, tgt: str) -> Link:
        return edges[(min(src, tgt), max(src, tgt))]
    events = []
    for _ in range(NODE_BUFF_SZ):
        neighbour = choice(adj_list[S])
        # first we have to wait for the link to be ready
        waiting_time = get_edge(S, neighbour).reserve(0, KEY_SIZE)
        nodes[S].buffer_space -= 1
        push(events, (0+waiting_time, ("link_ready", S, neighbour)))
    
    rcv_at_destination = 0 # received bits at destination node


    while True and len(events) > 0:
        time, e = pop(events)
        type = e[0]
        # print(f"time: {time}, event: {e}")
        
        if type == "rcv_ready": # receiving "ready" implies the sender wants to send a key and has reserved key material from link
            src, me = e[1], e[2]
            if nodes[me].buffer_space > 0:
                assert len(nodes[me].waiting) == 0
                nodes[me].buffer_space -= 1 # reserve a spot in the buffer
                push(events, (time+LATENCY, ("rcv_can_send", me, src)))
            else:
                nodes[me].waiting.append(src)
        elif type == "rcv_can_send":
            me, target = e[2], e[1]
            # we send the key to the target. they will receive it after latency
            push(events, (time+LATENCY, ("rcv_key", me, target)))
            nodes[me].buffer_space += 1
            if len(nodes[me].waiting) > 0:
                next_waiting = nodes[me].waiting.pop(0)
                nodes[me].buffer_space -= 1
                push(events, (time+LATENCY, ("rcv_can_send", me, next_waiting)))
            elif me == S:
                assert len(nodes[me].waiting) == 0
                neighbour = choice(adj_list[S])
                nodes[S].buffer_space -= 1
                waiting_time = get_edge(S, neighbour).reserve(time, KEY_SIZE)
                push(events, (time+waiting_time, ("link_ready", S, neighbour)))
        elif type == "rcv_key":
            src, tgt = e[1], e[2]
            if tgt == T:
                rcv_at_destination += KEY_SIZE
                nodes[T].buffer_space += 1  # key consumed, free buffer
                # notify anyone waiting to send to T
                if len(nodes[T].waiting) > 0:
                    next_waiting = nodes[T].waiting.pop(0)
                    nodes[T].buffer_space -= 1
                    push(events, (time + LATENCY, ("rcv_can_send", T, next_waiting)))
                print(f"throughput: {rcv_at_destination / time}")
            else:
                # where do we send the key?
                me = tgt
                neighbour = choice(adj_list[me])
                waiting_time = get_edge(me, neighbour).reserve(time, KEY_SIZE)
                push(events, (time+waiting_time, ("link_ready", me, neighbour)))
        elif type == "link_ready":
            me, neighbour = e[1], e[2]
            push(events, (time+LATENCY, ("rcv_ready", me, neighbour))) # i (me) wish to send my key to neighbour

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: throughput.py <edge_list_csv>")
        sys.exit(1)
    edge_list_csv = sys.argv[1]
    node_id_set = set()
    adj_list = defaultdict[str, list[str]](list)
    with open(edge_list_csv, 'r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            src, tgt = row['Source'], row['Target']
            node_id_set.add(src), node_id_set.add(tgt)
            adj_list[src].append(tgt), adj_list[tgt].append(src)

    nodes = {node_id: Node(node_id) for node_id in node_id_set}
    edges = {}
    for src in node_id_set:
        for tgt in adj_list[src]:
            if src < tgt:
                edges[(src, tgt)] = Link(src, tgt, QKD_SKR, LATENCY)

    S, T = "", ""
    for node in node_id_set:
        if S == "": S = node
        else: T = node

    if S == "" or T == "":
        print("S or T not found")
        sys.exit(1)
    
    print(f"S: {S}, T: {T}")
    
    main(adj_list, S, T, nodes, edges)
