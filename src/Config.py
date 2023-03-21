

import yaml
import sys

class Config:
    def get_config(configfile):
        try:
            with open(configfile, "r", encoding='utf8') as yaml_file:
                return yaml.safe_load(yaml_file)
        except Exception as e:
            print(f'Error opening the configuration file: {e}')
            sys.exit(1)