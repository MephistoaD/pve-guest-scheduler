import sys
import requests
import urllib3
from loguru import logger
from copy import deepcopy
from time import sleep
import socket
import yaml

"""Global config"""
valid_node_states = {"RUNNING", "CORDON", "DRAIN", "IGNORE"}
valid_guest_states = {"IGNORED", "MANAGED"}

"""Global settings"""
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ClusterApi:
    def __init__(self, proxmox_config):
        logger.debug('Creating Cluster object...')

        """Proxmox (process parameters)"""
        self.server_url = f'https://{proxmox_config["url"]["ip"]}:{proxmox_config["url"]["port"]}'
        self.auth = dict(proxmox_config["auth"])

        """Authenticate initially"""
        self.authentication(self.server_url, self.auth)

        """Necessary for isQuorate and isManager"""
        self.manager_status = self.get('/api2/json/cluster/ha/status/manager_status')

        """Necessary for getNodes and getGuests"""
        self.resources = self.get('/api2/json/cluster/resources')
        self.nodes = self.fetchNodes()

    def authentication(self, server: str, data: dict):
        """Authentication and receipt of a token and ticket."""
        global payload, header
        url = f'{server}/api2/json/access/ticket'
        logger.debug('Authorization attempt...')
        try:
            get_token = requests.post(url, data=data, verify=False)
        except Exception as exc:
            message = f'Incorrect server address or port settings: {exc}'
            logger.exception(message)
            #send_mail(f'Proxmox node ({self.server_url}) is unavailable. Network or settings problem')
            sys.exit(1)
        if get_token.ok:
            logger.debug(f'Successful authentication. Response code: {get_token.status_code}')
        else:
            logger.debug(f'Execution error {self.authentication.__qualname__}')
            logger.error(f'Authentication failed. Response code: {get_token.status_code}. Reason: {get_token.reason}')
            sys.exit(1)
        self.auth_payload = {'PVEAuthCookie': (get_token.json()['data']['ticket'])}
        self.auth_header = {'CSRFPreventionToken': (get_token.json()['data']['CSRFPreventionToken'])}

    def isQuorate(self):
        """Getting nodes from cluster resources"""
        logger.debug("Launching Cluster.isQuorate")
        return (self.manager_status['quorum']['quorate'] == "1")

    def isManager(self):
        """Getting nodes from cluster resources"""
        logger.debug("Launching Cluster.isManager")
        master = self.manager_status['manager_status']['master_node']

        # black magic, don't try to understand
        currentHost = socket.gethostname()

        return (currentHost == master)

    def fetchNodes(self):
        nodes_dict = {}
        resources = deepcopy(self.resources)
        for item in resources:
            if item['type'] == "node" and item['status'] == "online":
                """Process the nodes resources consumption:"""
                #self.cluster_information.remove(item)
                item["cpu_used"] = round(item["maxcpu"] * item["cpu"], 2)  # Adding the value of the cores used
                item["free_mem"] = item["maxmem"] - item["mem"]  # Adding the value of free RAM
                item["mem_load"] = item["mem"] / item["maxmem"]  # Adding the RAM load value

                """Process the nodes state:"""
                node_config = self.get(f'/api2/json/nodes/{item["node"]}/config')
                try:
                    node_config = yaml.safe_load(node_config['description'].split('<pve-devil>')[1].split('</pve-devil>')[0])
                    item["node_state"] = node_config['node_state']
                except:
                    item["node_state"] = "IGNORE"  # default value

                #logger.debug(item["node_state"])
                if item["node_state"] == "IGNORE":
                    logger.warning(f'no node state defined for node {item["node"]}! ignoring...')
                elif item["node_state"] not in valid_node_states:
                    logger.warning(f'invalid node state defined for node {item["node"]}! ignoring...')
                else:
                    nodes_dict[item["node"]] = item
        del resources
        return nodes_dict

    def getNodes(self):
        return self.nodes

    def getGuests(self, lxc_migration):
        guests_dict = {}
        resources = deepcopy(self.resources)
        for item in resources:
            #logger.debug(item)
            # status must be checked after the types!!!
            if ((item['type'] == "qemu") or (lxc_migration and item['type'] == "lxc")) and item['status'] == "running":
                """Exclude if vms running on ignored nodes"""
                if item["node"] not in self.nodes:
                    continue

                """Fetch the guests state"""
                guest_config = self.get(f'/api2/json/nodes/{item["node"]}/{item["type"]}/{item["vmid"]}/config')

                try:
                    guest_config = yaml.safe_load(guest_config['description'].split('<pve-devil>')[1].split('</pve-devil>')[0])
                    item["node_state"] = guest_config['node_state']
                except:
                    item["guest_state"] = "MANAGED"  # default value


                if item["guest_state"] == "IGNORED":
                    logger.info(f'IGNORED guest state defined for {item["type"]} {item["vmid"]}! ignoring...')
                elif item["guest_state"] not in valid_guest_states:
                    logger.warning(f'invalid node state defined for node {item["node"]}! ignoring...')
                else:
                    guests_dict[item["vmid"]] = item
        del resources
        return guests_dict

    def get(self, path):
        url = f'{self.server_url}{path}'
        logger.debug(f'Running get request on {path}')
        get = requests.get(url, cookies=self.auth_payload, verify=False)
        if get.ok:
            logger.debug(f'Information from get request ({path}) has been received. Response code: {get.status_code}')
        else:
            logger.warning(f'Could not get information from get request ({path}). Response code: {get.status_code}. Reason: ({get.reason})')
            sys.exit(0)

        return get.json()['data']

    def post(self, path, data):
        url = f'{self.server_url}{path}'
        logger.debug(f'Running post request on {path} with {data}')
        #logger.debug(f'payload = {self.auth_payload} header = {self.auth_header}')
        post = requests.post(url, cookies=self.auth_payload, headers=self.auth_header, data=data, verify=False)
        return post

    def migrate(self, movable_guests: list, dest_node: dict) -> bool:
        orig = movable_guests[0][1]["node"]
        dest = dest_node["node"]


        """VM migration function from the suggested variants"""
        for guest in movable_guests:
            guest = guest[1]
            vmid = guest["vmid"]
            type = guest["type"]
            logger.info(f'Starting guest migration of {guest["vmid"]} from {guest["node"]} to {dest_node["node"]}')

            # TODO: get request on migrate to receive local ressources and migrate offline
            # get information about the coming migration
            #migrate = self.get(f'/api2/json/nodes/{orig}/qemu/{vmid}/migrate')


            # migrate request
            if type == "lxc":
                data = {'target': dest, 'restart': 1}
            elif type == "qemu":
                data = {'target': dest, 'online': 1}
            path = f'/api2/json/nodes/{guest["node"]}/{type}/{vmid}/migrate'
            post = self.post(path, data)
            if post.ok:
                logger.info(f'Migrating {type}:{vmid} ({round(guest["mem"] / (1024*1024*1024), 2)} GB mem) from {orig} to {dest}...')
                pid = post.json()['data']
            else:
                logger.warning(f'Error while requesting migration of {type}: {vmid} from {orig} to {dest}\nREASON: {post.status_code}: {post.reason}')
                # in this case the user should consider setting the guest state to "ignored" or adding the guest to a HA group to limit the potential destination nodes
                continue

            # wait for the guest to arrive at dest_node
            status = True
            timer: int = 0
            while status: # confirm the migration is done
                timer += 20
                sleep(20)

                # continue waiting if the migration is still running
                url = f'{self.server_url}/api2/json/nodes/{orig}/{type}/{vmid}/migrate'
                migrate = requests.get(url, cookies=self.auth_payload, verify=False)
                if not migrate.ok and "VM is locked (migrate)" == migrate.reason:
                    continue

                # the migration job finished
                # get vms on destination node
                dest_guests = self.get(f'/api2/json/nodes/{dest}/{type}')
                for dest_guest in dest_guests:
                    if int(dest_guest['vmid']) == vmid and dest_guest['status'] == 'running':
                        logger.info(f'{pid} - Completed!')
                        sleep(10)
                        if type == "qemu":
                            post = self.post(f'/api2/json/nodes/{dest}/qemu/{vmid}/status/resume', '')
                            logger.debug(f'Resuming {vmid} after {pid}: {post.ok}')
                        return True # for dest_guest in dest_guests:
                    elif dest_guest['vmid'] == vmid and dest_guest['status'] != 'running':
                        #send_mail(f'Problems occurred during VM:{vm} migration. Check the VM status')
                        logger.exception(f'Something went wrong during the migration. Response code{post.status_code}')
                        sys.exit(1)
                    else:
                        logger.info(f'VM Migration: {vmid}... {timer} sec.')

        return False