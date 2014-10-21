# -*- coding: iso-8859-1 -*-

import sys
import os
import json
import threading
import logging
import time
import SocketServer
import common
from datetime import datetime


# ==================== Global variables ====================
# Dictionary to store information lists about each client:
#   [client name, network address, process identification (PID), 
#   ID of the resource being collected, number of resources already 
#   collected, collection start date and last update date] 
clientsInfo = {} 

# Store a reference for the thread running the client 
# and an event to interrupt its execution
clientsThreads = {}

# Define the next ID to give to a new client
nextFreeID = 1

# Define locks for critical regions of the code
nextFreeIDLock = threading.Lock()
getIDLock = threading.Lock()


# ==================== Classes ====================
class ServerHandler(SocketServer.BaseRequestHandler):
    def setup(self):
        # Get filters instances
        self.parallelFilters = [FilterClass(filterName) for (FilterClass, filterName) in self.server.ParallelFiltersClasses]
        self.sequentialFilters = [FilterClass(filterName) for (FilterClass, filterName) in self.server.SequentialFiltersClasses]
        # Get persistence instance
        self.persist = self.server.PersistenceHandlerClass(self.server.config["persistence"])

    def handle(self):
        # Define some local variables
        config = self.server.config
        client = common.NetworkHandler(self.request)
        persist = self.persist
        status = persist.statusCodes
    
        # Start to handle
        clientID = 0
        running = True
        while (running):
            try: 
                message = client.recv()
                
                # Stop thread execution if the client has closed the connection
                if (not message): 
                    if (config["server"]["logging"]): logging.info("Connection to client %d closed." % clientID)
                    if (config["server"]["verbose"]): print "Connection to client %d closed." % clientID
                    running = False
                    continue

                command = message["command"]
                
                if (command == "GET_LOGIN"):
                    with nextFreeIDLock:
                        global nextFreeID
                        clientID = nextFreeID
                        nextFreeID += 1
                    clientName = message["name"]
                    clientAddress = client.getaddress()
                    clientPid = message["processid"]
                    clientsInfo[clientID] = [clientName, clientAddress, clientPid, None, 0, datetime.now(), None]
                    clientsThreads[clientID] = (threading.current_thread(), threading.Event())
                    client.send({"command": "GIVE_LOGIN", "clientid": clientID})
                    if (config["server"]["logging"]): logging.info("New client connected: %d" % clientID)
                    if (config["server"]["verbose"]): print "New client connected: %d" % clientID
                
                elif (command == "GET_ID"):
                    clientStopEvent = clientsThreads[clientID][1]
                    tryagain = True
                    while (tryagain):
                        tryagain = False
                        # If the client hasn't been removed, check resource availability
                        if (not clientStopEvent.is_set()):
                            clientName = clientsInfo[clientID][0]
                            with getIDLock:
                                (resourceID, resourceInfo) = persist.selectResource()
                                if (resourceID): persist.updateResource(resourceID, None, status["INPROGRESS"], clientName)
                            # If there is a resource available, send ID to client
                            if (resourceID):
                                clientsInfo[clientID][3] = resourceID
                                clientsInfo[clientID][4] += 1
                                clientsInfo[clientID][6] = datetime.now()
                                filters = self.applyFilters(resourceID, resourceInfo)
                                client.send({"command": "GIVE_ID", "resourceid": resourceID, "filters": filters})
                            else:
                                # If there isn't resources available and loopforever is true, wait and check again
                                if (config["server"]["loopforever"]): 
                                    time.sleep(5)
                                    tryagain = True
                                # If there isn't resources available and loopforever is false, finish client
                                else:
                                    client.send({"command": "FINISH"})
                                    del clientsInfo[clientID]
                                    running = False
                                    # If there isn't any more clients to finish, finish server
                                    if (not clientsInfo):
                                        self.server.shutdown()
                                        if (config["server"]["logging"]): logging.info("Task done, server finished.")
                                        if (config["server"]["verbose"]): print "Task done, server finished."
                        # If the client has been removed, kill it
                        else:
                            client.send({"command": "KILL"})
                            del clientsInfo[clientID]
                            if (config["server"]["logging"]): logging.info("Client %d removed." % clientID)
                            if (config["server"]["verbose"]): print "Client %d removed." % clientID
                            running = False
                    
                elif (command == "DONE_ID"):
                    clientName = clientsInfo[clientID][0]
                    clientResourceID = message["resourceid"]
                    clientResourceInfo = message["resourceinfo"]
                    persist.updateResource(clientResourceID, clientResourceInfo, status["SUCCEDED"], clientName)
                    client.send({"command": "DID_OK"})
                    
                elif (command == "STORE_IDS"):
                    clientName = clientsInfo[clientID][0]
                    clientResourcesList = message["resourceslist"]
                    for resource in clientResourcesList:
                        persist.insertResource(resource[0], resource[1], clientName)
                    client.send({"command": "STORE_OK"})
                    
                elif (command == "GET_STATUS"):
                    status = "\n" + (" Status (%s:%s/%s) " % (config["global"]["connection"]["address"], config["global"]["connection"]["port"], os.getpid())).center(50, ':') + "\n\n"
                    if (clientsInfo): 
                        for (ID, clientInfo) in clientsInfo.iteritems():
                            clientAlive = (" " if clientsThreads[ID][0].is_alive() else "+")
                            clientName = clientInfo[0]
                            clientAddress = clientInfo[1]
                            clientPid = clientInfo[2]
                            clientResourceID = clientInfo[3]
                            clientAmount = clientInfo[4]
                            clientStartTime = clientInfo[5]
                            clientUpdatedAt = clientInfo[6]
                            elapsedTime = datetime.now() - clientStartTime
                            elapsedMinSec = divmod(elapsedTime.seconds, 60)
                            elapsedHoursMin = divmod(elapsedMinSec[0], 60)
                            status += "  #%d %s %s (%s:%s/%s): %s since %s [%d collected in %s]\n" % (ID, clientAlive, clientName, clientAddress[0], clientAddress[1], clientPid, clientResourceID, clientUpdatedAt.strftime("%d/%m/%Y %H:%M:%S"), clientAmount, "%02dh%02dm%02ds" % (elapsedHoursMin[0],  elapsedHoursMin[1], elapsedMinSec[1]))
                    else:
                        status += "  No client connected right now.\n"
                    resourcesTotal = float(persist.totalResourcesCount())
                    resourcesCollected = float(persist.resourcesCollectedCount())
                    collectedResourcesPercent = (resourcesCollected / resourcesTotal) * 100
                    status += "\n" + (" Status (%.1f%% collected) " % (collectedResourcesPercent)).center(50, ':') + "\n"
                    client.send({"command": "GIVE_STATUS", "status": status})
                    running = False
                    
                elif (command == "RM_CLIENT"):
                    ID = int(message["clientid"])
                    if (ID in clientsThreads):
                        # If the thread is alive, set the associated interrupt event and wait for the thread to safely stop
                        if (clientsThreads[ID][0].is_alive()):
                            clientsThreads[ID][1].set()
                            while (clientsThreads[ID][0].is_alive()): pass
                        # If the thread isn't alive, mark the last ID requested by the client as not collected, 
                        # so that it can be requested again by any other client, ensuring collection consistency
                        else:
                            clientName = clientsInfo[ID][0]
                            clientResourceID = clientsInfo[ID][3]
                            persist.updateResource(clientResourceID, None, status["AVAILABLE"], clientName)
                            del clientsInfo[ID]
                            if (config["server"]["logging"]): logging.info("Client %d removed." % ID)
                            if (config["server"]["verbose"]): print "Client %d removed." % ID
                        del clientsThreads[ID]
                        client.send({"command": "RM_OK"})
                    else:
                        client.send({"command": "RM_ERROR", "reason": "ID does not exist."})
                    running = False
                        
                elif (command == "SHUTDOWN"):
                    # Interrupt all active clients and mark resources requested by inactive 
                    # clients as not collected. After that, shut down server
                    if (config["server"]["logging"]): logging.info("Removing all clients to shut down...")
                    if (config["server"]["verbose"]): print "Removing all clients to shut down..."
                    for ID in clientsThreads.keys():
                        if (clientsThreads[ID][0].is_alive()):
                            clientsThreads[ID][1].set()
                        else:
                            clientName = clientsInfo[ID][0]
                            clientResourceID = clientsInfo[ID][3]
                            persist.updateResource(clientResourceID, None, status["AVAILABLE"], clientName)
                            del clientsInfo[ID]
                    while (clientsInfo): pass
                    self.server.shutdown()    
                    client.send({"command": "SD_OK"})
                    if (config["server"]["logging"]): logging.info("Server manually shut down.")
                    if (config["server"]["verbose"]): print "Server manually shut down."
                    running = False
            
            except Exception as error:
                if (config["server"]["logging"]): logging.exception("Exception while processing a request from client %d. Execution of thread '%s' aborted." % (clientID, threading.current_thread().name))
                if (config["server"]["verbose"]): 
                    print "ERROR: %s" % str(error)
                    excType, excObj, excTb = sys.exc_info()
                    fileName = os.path.split(excTb.tb_frame.f_code.co_filename)[1]
                    print (excType, fileName, excTb.tb_lineno)
                running = False
    
    def finish(self):
        self.persist.close()
                
    def threadedFilterWrapper(self, filter, resourceID, resourceInfo, outputList):
        data = filter.apply(resourceID, resourceInfo, None)
        outputList.append({"filter": filter.getName(), "order": None, "data": data})
                
    def applyFilters(self, resourceID, resourceInfo):
        parallelFilters = self.parallelFilters
        sequentialFilters = self.sequentialFilters
        filters = []
    
        # Start threaded filters
        filterThreads = []
        for filter in parallelFilters:
            t = threading.Thread(target=self.threadedFilterWrapper, args=(filter, resourceID, resourceInfo, filters))
            filterThreads.append(t)
            t.start()
        
        # Execute sequential filters
        data = {}
        for filter in sequentialFilters:
            data = filter.apply(resourceID, resourceInfo, data.copy())
            filters.append({"name": filter.getName(), "order": sequentialFilters.index(filter), "data": data})
            
        # Wait for threaded filters to finish
        for filter in filterThreads:
            filter.join()
        
        return filters
                
                
class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    def __init__(self, configurationsDictionary, PersistenceHandlerClass):
        self.config = configurationsDictionary
        self.PersistenceHandlerClass = PersistenceHandlerClass
        self.ParallelFiltersClasses = []
        self.SequentialFiltersClasses = []
        
        # Configure logging
        if (self.config["server"]["logging"]):
            logging.basicConfig(format="%(asctime)s %(module)s %(levelname)s: %(message)s", datefmt="%d/%m/%Y %H:%M:%S", 
                                filename="server[%s%s].log" % (self.config["global"]["connection"]["address"], self.config["global"]["connection"]["port"]), filemode="w", level=logging.DEBUG)
        
        # Call SocketSever constructor
        SocketServer.TCPServer.__init__(self, (self.config["global"]["connection"]["address"], self.config["global"]["connection"]["port"]), ServerHandler)
    
    def start(self):
        if (self.config["server"]["logging"]): logging.info("Server ready. Waiting for connections...")
        if (self.config["server"]["verbose"]): print "Server ready. Waiting for connections..."
        self.serve_forever()
        
    def addFilter(self, FilterClass, filterName="", parallel=False):        
        if (parallel): self.ParallelFiltersClasses.append((FilterClass, filterName))
        else: self.SequentialFiltersClasses.append((FilterClass, filterName))
