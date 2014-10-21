#!/usr/bin/python
# -*- coding: iso-8859-1 -*-

import sys
import json
import argparse
import common


# Analyse arguments
parser = argparse.ArgumentParser(add_help=False, description="Send action commands to be performed by the server or retrieve status information. If none of the optional arguments are given, basic status information is shown.")
parser.add_argument("configFilePath")
parser.add_argument("-h", "--help", action="help", help="show this help message and exit")
parser.add_argument("-e", "--extended", action="store_true", help="show extended status information")
parser.add_argument("-r", "--remove", metavar="clientID", help="remove the client specified by the given ID from the server's list")
parser.add_argument("--shutdown", action="store_true", help="remove all clients from the server's list and shutdown server")
args = parser.parse_args()

# Load configurations
config = common.loadConfig(args.configFilePath)

# Connect to server
try:
    server = common.NetworkHandler()
    server.connect(config["global"]["connection"]["address"], config["global"]["connection"]["port"])
except:
    sys.exit("ERROR: It was not possible to connect to server at %s:%s." % (config["global"]["connection"]["address"], config["global"]["connection"]["port"]))

# Remove client
if (args.remove):
    server.send({"command": "RM_CLIENT", "clientid": args.remove})
    message = server.recv()
    server.close()
    
    command = message["command"]
    if (command == "RM_OK"):
        print "Client %s successfully removed." % args.remove
    elif (command == "RM_ERROR"):
        print "ERROR: %s." % message["reason"] 
    
# Shut down server
elif (args.shutdown):   
    server.send({"command": "SHUTDOWN"})
    message = server.recv()
    server.close()
    
    command = message["command"]
    if (command == "SD_OK"):
        print "Server successfully shut down."
        
# Show status
else:
    server.send({"command": "GET_STATUS"})
    message = server.recv()
    server.close()
    
    command = message["command"]
    if (command == "GIVE_STATUS"):
        print message["status"] 