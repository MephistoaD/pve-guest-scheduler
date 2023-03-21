# PVE Guest scheduler

This is a guest scheduler based on the memory consumption of each guest.
It's designed to work both with LXC and VMs.

## How does it work?

The program calculates each nodes deviation of all nodes average memory consume (`dev_mem`).

The goal of the scheduler is to converge each nodes `dev_mem` value below the `deviation` parameter given in the config.yml.

_This has the advantage that the memory consumption on all nodes is comparable, even if the absolute amount a node has may differ._

### How does it select the guest to migrate?

By convergence. The algorithm sorts the nodes by their `dev_mem` value and extracts a `max_mem_node` (with `dev_mem > 0`) and a `min_mem_node` (with `dev_mem < 0`).
Then it searches for a guest which has a memory consume as close as possible to `move_mem := min(dev_mem[max_mem_node], dev_mem[min_mem_node])`, and migrates it to the node with the lower memory consumption (while preferring vms, since they can be migrated online).