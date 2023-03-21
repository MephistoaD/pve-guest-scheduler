from Config import Config
from ClusterApi import ClusterApi
from loguru import logger
from time import sleep
import sys

"""Loguru"""
logger.remove()
# For Linux service
logger.add(sys.stdout, format="{level} | {message}", level='DEBUG')


def getGuestsToDrain(guests, nodes):
    guests_to_move = dict()
    for id, guest in guests.items():
        if guest['guest_state'] == "MANAGED" and nodes[guest["node"]]["node_state"] == "DRAIN":
            guests_to_move[guest["vmid"]] = guest
    return guests_to_move


def getGuestsOnlyFromNode(guests: dict, node: dict):
    guests_from_node = dict()
    for id,guest in guests.items():
        #logger.debug(guest)
        if guest["node"] == node["node"]:
            guests_from_node[guest["vmid"]] = guest
    return guests_from_node

def getSortedMigrationsFromTo(orig_node: dict, dest_node: dict, guests: dict):
    memory_amount_to_move = min(abs(orig_node["maxmem"]*orig_node["deviation"]), abs(dest_node["maxmem"]*dest_node["deviation"]))
    logger.debug(f'orig = {orig_node["node"]} dest = {dest_node["node"]} mem = {memory_amount_to_move}')

    """get guest fitting the requirements"""
    guests_from_node = dict()
    for id, guest in guests.items():
        logger.debug(guest)
        # if guest is on node of origin and has destination has enought memory to run it
        if guest["node"] == orig_node["node"] and guest["maxmem"] < dest_node["maxmem"]:
            guests_from_node[guest["vmid"]] = guest
    guests = guests_from_node
    """sort the guests by the difference of their memory consumtion and the memory_amount_to_move"""
    guests = sorted(guests.items(), key=lambda item: abs(item[1]["mem"]-memory_amount_to_move)+(memory_amount_to_move if item[1]["type"] == "lxc" else 0)) # ternary operator gives lxc a disadvantage

    logger.debug(f'on host {orig_node["node"]} are the following vms: {guests}')
    # at this point the first of the guests fits best for migration
    return guests

def getMigrationPath(nodes):
    """get node with max and min procentual ressources consume"""
    nodes = sorted(nodes.items(), key=lambda item: item[1]["deviation"])
    max_free_mem = 0
    for node in nodes:
        free_mem = node[1]["maxmem"]*node[1]["deviation"]
        # excludes all nodes with cordon; free memory left; node with greatest free space so far
        if node[1]["node_state"] == "RUNNING" and free_mem < max_free_mem:
            dest_node = node[1]  # the second index is to get the data
            break
    orig_node = nodes[len(nodes) - 1][1]
    return orig_node, dest_node

def hasToSkip(cluster, only_on_manager):
    # TODO test
    if cluster.isQuorate():
        logger.info('Cluster is quorate!')
    else:
        logger.info('Cluster is not quorate! skipping run...')
        return True

    # TODO test
    if (only_on_manager) and (not cluster.isManager()):
        logger.info('Host is not manager. skipping run...')
        return True

def getClusterMem(nodes: dict, node_states: dict):
    mem = {"max": 0.0, "current": 0.0, "load": 0.0}
    for id,node in nodes.items():
        if node["node_state"] in node_states:
            mem["max"] += node["maxmem"]
            mem["current"] += node["mem"]
    mem["load"] = mem["current"] / mem["max"]
    return mem

def calculateNodesDeviation(nodes: dict):
    average_mem_load_with = getClusterMem(nodes, {"RUNNING", "CORDON"})
    average_mem_load_without = getClusterMem(nodes, {"RUNNING"})
    logger.debug(f'{average_mem_load_with["current"]} / {average_mem_load_with["max"]} = {average_mem_load_with["load"]}')
    for id, node in nodes.items():
        if node["node_state"] == "CORDON":
            """Calculate the deviation"""
            node["deviation"] = node["mem"] / node["maxmem"] - average_mem_load_with["load"]
        else:
            """Calculate the deviation"""
            node["deviation"] = node["mem"] / node["maxmem"] - average_mem_load_without["load"]

        logger.info(f'Deviation for node {id} is {round(node["deviation"]*100, 2)}% with {round(node["maxmem"]*node["deviation"]/1024/1024/1024, 3)} GB of free memory')

def getMaxNodesDeviation(nodes):
    max = float()
    for name,node in nodes.items():
        dev = abs(node["deviation"])
        if dev > max:
            max = abs(node["deviation"])
    return max*100


def main():
    """Load newest config"""
    config = Config.get_config("config.yml")

    while True:
        """Auth at cluster endpoint"""
        cluster = ClusterApi(config['proxmox'])

        """Check if allowed to run"""
        if hasToSkip(cluster, config["parameters"]["only_on_manager"]):
            sleep(int(config['parameters']['sleep_time']['error']))
            continue

        """Fetch current cluster state"""
        nodes = cluster.getNodes()
        #logger.debug(nodes)
        # if drain:
        """Fetch all VMs on host to drain"""
        #guests_to_move = getGuestsToDrain(guests, nodes)

        #if not bool(guests_to_move): # if there are vms to drain from a host
        #    logger.info("no guests to drain found")

        """Prioritize easiest first"""
        # else:
        """Get running guests"""
        guests = cluster.getGuests(config['parameters']['lxc_migration'])
        #logger.debug(guests)
        """Calculate necessary migrations"""
        calculateNodesDeviation(nodes)
        # at this point the nodes deviation dict is sorted from low to high
        # -> a migration from last to first must be found in case the deviation is higher than the allowed

        """Prioritize Migrations"""
        movable_guests = list()
        while len(movable_guests) == 0:
            orig_node, dest_node = getMigrationPath(nodes)
            movable_guests = getSortedMigrationsFromTo(orig_node, dest_node, guests)

            #if orig_node["deviation"] < 0:
            #    logger.info(f'No suitable migration option found. skipping...')
            #    movable_guests = list()
            #    break

            if getMaxNodesDeviation(nodes) < config["parameters"]["deviation"]:
                logger.info(f'No deviation greater than {config["parameters"]["deviation"]}% found on any node. skipping...')
                movable_guests = list()
                break

        # done
        """Perform first Migration"""
        if len(movable_guests) > 0:
            cluster.migrate(movable_guests, dest_node)

        """Wait for the cluster to calm down"""
        sleep(int(config['parameters']['sleep_time']['sucess']))
        logger.info('------------ restarting ------------')


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    main()
