﻿import socket
import struct
from threading import Thread
import numpy as np
import time

VERBOSE = False

# Create structs for reading various object types to speed up parsing.
Vector3 = struct.Struct('<fff')
Quaternion = struct.Struct('<ffff')
FloatValue = struct.Struct('<f')
DoubleValue = struct.Struct('<d')


"""
print(*args) if VERBOSE is set to True. does nothing otherwise
"""


def from_bytes(data, byteorder):
    if len(data) == 2:
        return int(struct.unpack('<H', data)[0])
    elif len(data) == 4:
        return int(struct.unpack('<I', data)[0])


def trace(*args):
    if VERBOSE:
        print("".join(map(str, args)))


class OptiTrackPythonClient:
    def __init__(self, client_ip=None, server_ip="192.168.2.100", 
                                       multicast_address="239.255.42.99",
                                       command_port = 1510,
                                       data_port = 1511):
        self.is_alive = True
        self.client_ip = client_ip
        self.server_address = server_ip
        self.multicast_address = multicast_address
        self.command_port = command_port
        self.data_port = data_port

        # Set this to a callback method of your choice to receive per-rigid-body data at each frame.
        self.rigidBodyListener = None

        self.newFrameListener = None

        # Indicates nothing was received yet (or no rigid bodies available)
        self.rigidBodyDescriptor = None

        self.__natNetStreamVersion = (3, 0, 0, 0)

    # Client/server message ids
    NAT_PING = 0
    NAT_PINGRESPONSE = 1
    NAT_REQUEST = 2
    NAT_RESPONSE = 3
    NAT_REQUEST_MODELDEF = 4
    NAT_MODELDEF = 5
    NAT_REQUEST_FRAMEOFDATA = 6
    NAT_FRAMEOFDATA = 7
    NAT_MESSAGESTRING = 8
    NAT_DISCONNECT = 9
    NAT_UNRECOGNIZED_REQUEST = 100

    # Create a data socket to attach to the NatNet stream
    def __createDataSocket(self, port, client_ip=None):
        result = socket.socket(socket.AF_INET,  # Internet
                               socket.SOCK_DGRAM,
                               socket.IPPROTO_UDP)  # UDP

        # https://stackoverflow.com/a/1151620
        try:
            result.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except AttributeError:
            pass
        # https://stackoverflow.com/a/49491687
        result.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 32) 
        result.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)

        result.bind((self.multicast_address, port))

        if not client_ip:
            # after reading the comments...
            client_ip = socket.gethostbyname(socket.gethostname())

        result.setsockopt(socket.SOL_IP, socket.IP_MULTICAST_IF, socket.inet_aton(client_ip))
        result.setsockopt(socket.SOL_IP, socket.IP_ADD_MEMBERSHIP, 
                        socket.inet_aton(self.multicast_address) + socket.inet_aton(client_ip))

        return result

    # Create a command socket to attach to the NatNet stream
    def __createCommandSocket(self):
        result=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        result.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        result.bind(('', 0))
        result.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        result.setblocking(1)

        return result

    # Unpack a rigid body object from a data packet
    def __unpackRigidBody(self, data):
        offset=0

        # ID (4 bytes)
        id =from_bytes(data[offset:offset + 4], byteorder ='little')
        trace("ID:", id)
        offset += 4

        # Position and orientation
        pos=Vector3.unpack(data[offset:offset + 12])
        offset += 12

        trace("\tPosition:", pos[0], ",", pos[1], ",", pos[2])
        rot=Quaternion.unpack(data[offset:offset + 16])
        offset += 16
        trace("\tOrientation:", rot[0], ",", rot[1], ",", rot[2], ",", rot[3])

        # Send information to any listener.
        if self.rigidBodyListener is not None:
            self.rigidBodyListener(id, pos, rot, self.rigidBodyDescriptor)
            trace("Sending info to rigidBodyListener")

        # RB Marker Data ( Before version 3.0.  After Version 3.0 Marker data is in description )
        if( self.__natNetStreamVersion[0] < 3  and self.__natNetStreamVersion[0] != 0) :
            # Marker count (4 bytes)
            markerCount = from_bytes( data[offset:offset+4], byteorder='little' )
            offset += 4
            markerCountRange = range( 0, markerCount )
            trace( "\tMarker Count:", markerCount )

            # Marker positions
            for i in markerCountRange:
                pos = Vector3.unpack( data[offset:offset+12] )
                offset += 12
                trace( "\tMarker", i, ":", pos[0],",", pos[1],",", pos[2] )

            if( self.__natNetStreamVersion[0] >= 2 ):
                # Marker ID's
                for i in markerCountRange:
                    id = from_bytes( data[offset:offset+4], byteorder='little' )
                    offset += 4
                    trace( "\tMarker ID", i, ":", id )

                # Marker sizes
                for i in markerCountRange:
                    size = FloatValue.unpack( data[offset:offset+4] )
                    offset += 4
                    trace( "\tMarker Size", i, ":", size[0] )
                    
        if( self.__natNetStreamVersion[0] >= 2 ):
            markerError, = FloatValue.unpack( data[offset:offset+4] )
            offset += 4
            trace( "\tMarker Error:", markerError )

        # Version 2.6 and later
        if( ( ( self.__natNetStreamVersion[0] == 2 ) and ( self.__natNetStreamVersion[1] >= 6 ) ) or self.__natNetStreamVersion[0] > 2 or self.__natNetStreamVersion[0] == 0 ):
            param, = struct.unpack( 'h', data[offset:offset+2] )
            trackingValid = ( param & 0x01 ) != 0
            offset += 2
            trace( "\tTracking Valid:", 'True' if trackingValid else 'False' )

        return offset

    # Unpack a skeleton object from a data packet
    def __unpackSkeleton( self, data ):
        offset = 0
        
        id = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4
        trace( "ID:", id )
        
        rigidBodyCount = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4
        trace( "Rigid Body Count:", rigidBodyCount )
        for j in range( 0, rigidBodyCount ):
            offset += self.__unpackRigidBody( data[offset:] )

        return offset

    # Unpack data from a motion capture frame message
    def __unpackMocapData( self, data ): 
        trace( "Begin MoCap Frame\n-----------------\n" )

        # data = memoryview( data )
        offset = 0
        
        # Frame number (4 bytes)
        frameNumber = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4
        trace( "Frame #:", frameNumber )

        # Marker set count (4 bytes)
        markerSetCount = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4
        trace( "Marker Set Count:", markerSetCount )

        for i in range( 0, markerSetCount ):
            # Model name
            modelName, separator, remainder = bytes(data[offset:]).partition( b'\0' )
            offset += len( modelName ) + 1
            trace( "Model Name:", modelName.decode( 'utf-8' ) )

            # Marker count (4 bytes)
            markerCount = from_bytes( data[offset:offset+4], byteorder='little' )
            offset += 4
            trace( "Marker Count:", markerCount )

            for j in range( 0, markerCount ):
                pos = Vector3.unpack( data[offset:offset+12] )
                offset += 12
                trace( "\tMarker", j, ":", pos[0],",", pos[1],",", pos[2] )
                         
        # Unlabeled markers count (4 bytes)
        unlabeledMarkersCount = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4
        trace( "Unlabeled Markers Count:", unlabeledMarkersCount )

        for i in range( 0, unlabeledMarkersCount ):
            pos = Vector3.unpack( data[offset:offset+12] )
            offset += 12
            trace( "\tMarker", i, ":", pos[0],",", pos[1],",", pos[2] )

        # Rigid body count (4 bytes)
        rigidBodyCount = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4
        trace( "Rigid Body Count:", rigidBodyCount )
         
        for i in range( 0, rigidBodyCount ):
            offset += self.__unpackRigidBody( data[offset:] )
        
        # Version 2.1 and later
        skeletonCount = 0
        if( ( self.__natNetStreamVersion[0] == 2 and self.__natNetStreamVersion[1] > 0 ) or self.__natNetStreamVersion[0] > 2 ):
            skeletonCount = from_bytes( data[offset:offset+4], byteorder='little' )
            offset += 4
            trace( "Skeleton Count:", skeletonCount )
            for i in range( 0, skeletonCount ):
                offset += self.__unpackSkeleton( data[offset:] )

        # Labeled markers (Version 2.3 and later)
        labeledMarkerCount = 0
        if( ( self.__natNetStreamVersion[0] == 2 and self.__natNetStreamVersion[1] > 3 ) or self.__natNetStreamVersion[0] > 2 ):
            labeledMarkerCount = from_bytes( data[offset:offset+4], byteorder='little' )
            offset += 4
            trace( "Labeled Marker Count:", labeledMarkerCount )
            for i in range( 0, labeledMarkerCount ):
                id = from_bytes( data[offset:offset+4], byteorder='little' )
                offset += 4
                pos = Vector3.unpack( data[offset:offset+12] )
                offset += 12
                size = FloatValue.unpack( data[offset:offset+4] )
                offset += 4

                # Version 2.6 and later
                if( ( self.__natNetStreamVersion[0] == 2 and self.__natNetStreamVersion[1] >= 6 ) or self.__natNetStreamVersion[0] > 2):
                    param, = struct.unpack( 'h', data[offset:offset+2] )
                    offset += 2
                    occluded = ( param & 0x01 ) != 0
                    pointCloudSolved = ( param & 0x02 ) != 0
                    modelSolved = ( param & 0x04 ) != 0

                # Version 3.0 and later
                if( ( self.__natNetStreamVersion[0] >= 3 )):
                    residual, = FloatValue.unpack( data[offset:offset+4] )
                    offset += 4
                    trace( "Residual:", residual )

        # Force Plate data (version 2.9 and later)
        if( ( self.__natNetStreamVersion[0] == 2 and self.__natNetStreamVersion[1] >= 9 ) or self.__natNetStreamVersion[0] > 2 ):
            forcePlateCount = from_bytes( data[offset:offset+4], byteorder='little' )
            offset += 4
            trace( "Force Plate Count:", forcePlateCount )
            for i in range( 0, forcePlateCount ):
                # ID
                forcePlateID = from_bytes( data[offset:offset+4], byteorder='little' )
                offset += 4
                trace( "Force Plate", i, ":", forcePlateID )

                # Channel Count
                forcePlateChannelCount = from_bytes( data[offset:offset+4], byteorder='little' )
                offset += 4

                # Channel Data
                for j in range( 0, forcePlateChannelCount ):
                    trace( "\tChannel", j, ":", forcePlateID )
                    forcePlateChannelFrameCount = from_bytes( data[offset:offset+4], byteorder='little' )
                    offset += 4
                    for k in range( 0, forcePlateChannelFrameCount ):
                        forcePlateChannelVal = from_bytes( data[offset:offset+4], byteorder='little' )
                        offset += 4
                        trace( "\t\t", forcePlateChannelVal )

        # Device data (version 2.11 and later)
        if( ( self.__natNetStreamVersion[0] == 2 and self.__natNetStreamVersion[1] >= 11 ) or self.__natNetStreamVersion[0] > 2 ):
            deviceCount = from_bytes( data[offset:offset+4], byteorder='little' )
            offset += 4
            trace( "Device Count:", deviceCount )
            for i in range( 0, deviceCount ):
                # ID
                deviceID = from_bytes( data[offset:offset+4], byteorder='little' )
                offset += 4
                trace( "Device", i, ":", deviceID )

                # Channel Count
                deviceChannelCount = from_bytes( data[offset:offset+4], byteorder='little' )
                offset += 4

                # Channel Data
                for j in range( 0, deviceChannelCount ):
                    trace( "\tChannel", j, ":", deviceID )
                    deviceChannelFrameCount = from_bytes( data[offset:offset+4], byteorder='little' )
                    offset += 4
                    for k in range( 0, deviceChannelFrameCount ):
                        deviceChannelVal = from_bytes( data[offset:offset+4], byteorder='little' )
                        offset += 4
                        trace( "\t\t", deviceChannelVal )
						       
        # Timecode            
        timecode = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4
        timecodeSub = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4

        # Timestamp (increased to double precision in 2.7 and later)
        if( ( self.__natNetStreamVersion[0] == 2 and self.__natNetStreamVersion[1] >= 7 ) or self.__natNetStreamVersion[0] > 2 ):
            timestamp, = DoubleValue.unpack( data[offset:offset+8] )
            offset += 8
        else:
            timestamp, = FloatValue.unpack( data[offset:offset+4] )
            offset += 4

        # Hires Timestamp (Version 3.0 and later)
        if( self.__natNetStreamVersion[0] >= 3 ):
            stampCameraExposure = from_bytes( data[offset:offset+8], byteorder='little' )
            offset += 8
            stampDataReceived = from_bytes( data[offset:offset+8], byteorder='little' )
            offset += 8
            stampTransmit = from_bytes( data[offset:offset+8], byteorder='little' )
            offset += 8

        # Frame parameters
        param, = struct.unpack( 'h', data[offset:offset+2] )
        isRecording = ( param & 0x01 ) != 0
        trackedModelsChanged = ( param & 0x02 ) != 0
        offset += 2

        # Send information to any listener.
        if self.newFrameListener is not None:
            self.newFrameListener( frameNumber, markerSetCount, unlabeledMarkersCount, rigidBodyCount, skeletonCount,
                                  labeledMarkerCount, timecode, timecodeSub, timestamp, isRecording, trackedModelsChanged )


    # Unpack a marker set description packet

    def __unpackMarkerSetDescription(self, data):
        offset=0

        name, separator, remainder=bytes(data[offset:]).partition(b'\0')
        offset += len(name) + 1
        trace("Markerset Name:", name.decode('utf-8'))

        markerCount=from_bytes(
            data[offset:offset + 4], byteorder='little')
        offset += 4

        for i in range(0, markerCount):
            name, separator, remainder=bytes(data[offset:]).partition(b'\0')
            offset += len(name) + 1
            trace("\tMarker Name:", name.decode('utf-8'))

        return offset

    # Unpack a rigid body description packet
    def __unpackRigidBodyDescription( self, data ):
        offset = 0

        # Version 2.0 or higher
        if( self.__natNetStreamVersion[0] >= 2 ):
            name, separator, remainder = bytes(data[offset:]).partition( b'\0' )
            offset += len( name ) + 1
            trace( "\tRigidBody Name:", name.decode( 'utf-8' ) )

        rigidbody_ID = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4

        rigidbody_parentID = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4

        rigidbody_timestamp = Vector3.unpack( data[offset:offset+12] )
        offset += 12
        
        # Version 3.0 and higher, rigid body marker information contained in description
        if (self.__natNetStreamVersion[0] >= 3 or self.__natNetStreamVersion[0] == 0 ):
            markerCount = from_bytes( data[offset:offset+4], byteorder='little' ) 
            offset += 4
            trace( "\tRigidBody Marker Count:", markerCount )

            markerCountRange = range( 0, markerCount )
            for marker in markerCountRange:
                markerOffset = Vector3.unpack(data[offset:offset+12])
                offset +=12
            for marker in markerCountRange:
                activeLabel = from_bytes(data[offset:offset+4],byteorder = 'little')
                offset += 4

        self.rigidBodyDescriptor[name]=(
            rigidbody_ID, rigidbody_parentID, rigidbody_timestamp)

        return offset        

    # Unpack a skeleton description packet
    def __unpackSkeletonDescription( self, data ):
        offset = 0

        name, separator, remainder = bytes(data[offset:]).partition( b'\0' )
        offset += len( name ) + 1
        trace( "\tMarker Name:", name.decode( 'utf-8' ) )
        
        id = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4

        rigidBodyCount = from_bytes( data[offset:offset+4], byteorder='little' )
        offset += 4

        for i in range( 0, rigidBodyCount ):
            offset += self.__unpackRigidBodyDescription( data[offset:] )

        return offset


    # Unpack a data description packet
    def __unpackDataDescriptions(self, data):
        offset=0
        datasetCount=from_bytes(
            data[offset:offset + 4], byteorder='little')
        offset += 4

        self.rigidBodyDescriptor={}  # this only happens once as
                                       # a response to self.NAT_REQUEST_MODELDEF

        for i in range(0, datasetCount):
            msgtype=from_bytes(data[offset:offset + 4], byteorder='little')
            offset += 4
            if (msgtype == 0):
                offset += self.__unpackMarkerSetDescription(data[offset:])
            elif (msgtype == 1):
                offset += self.__unpackRigidBodyDescription(data[offset:])
            elif( msgtype == 2 ):
                offset += self.__unpackSkeletonDescription( data[offset:] )                

    def __dataThreadFunction(self, socketd, timeout=0.1):
        # _buffersize = socketd.getsockopt(socket.SOL_SOCKET,
        #                                  socket.SO_RCVBUF)
        socketd.settimeout(timeout)

        while self.is_alive:
            try:
                # Block for input
                trace('Listening on data thread...')
                data=socketd.recv(32768)  # 32k byte buffer size
                if (len(data) > 0):
                    self.__processMessage(data)
            except socket.timeout:
                trace('Socket timemout!')
                continue
        try:
            socketd.setsockopt(socket.SOL_IP, 
                               socket.IP_DROP_MEMBERSHIP, 
                               socket.inet_aton(self.multicast_address) + socket.inet_aton('0.0.0.0'))
        except:
            pass

        socketd.close()

    def __processMessage( self, data ):
        trace( "Begin Packet\n------------\n" )

        messageID = from_bytes( data[0:2], byteorder='little' )
        trace( "Message ID:", messageID )
        
        self.packetSize = from_bytes( data[2:4], byteorder='little' )
        trace( "Packet Size:", self.packetSize )

        # Ultra-low-tech CRC test...
        if len(data) > (self.packetSize+4):
            return

        offset = 4
        if( messageID == self.NAT_FRAMEOFDATA ):
            self.__unpackMocapData( data[offset:] )
        elif( messageID == self.NAT_MODELDEF ):
            self.__unpackDataDescriptions( data[offset:] )
        elif( messageID == self.NAT_PINGRESPONSE ):
            offset += 256   # Skip the sending app's Name field
            offset += 4     # Skip the sending app's Version info
            self.__natNetStreamVersion = struct.unpack( 'BBBB', data[offset:offset+4] )
            trace("NetStreamVersion: {}".format(self.__natNetStreamVersion))
            offset += 4
        elif( messageID == self.NAT_RESPONSE ):
            if( self.packetSize == 4 ):
                commandResponse = from_bytes( data[offset:offset+4], byteorder='little' )
                offset += 4
            else:
                message, separator, remainder = bytes(data[offset:]).partition( b'\0' )
                offset += len( message ) + 1
                trace( "Command response:", message.decode( 'utf-8' ) )
        elif( messageID == self.NAT_UNRECOGNIZED_REQUEST ):
            trace( "Received 'Unrecognized request' from server" )
        elif( messageID == self.NAT_MESSAGESTRING ):
            message, separator, remainder = bytes(data[offset:]).partition( b'\0' )
            offset += len( message ) + 1
            trace( "Received message from server:", message.decode( 'utf-8' ) )
        else:
            trace( "ERROR: Unrecognized packet type" )
            
        trace( "End Packet\n----------\n" )

    def __sendCommand(self, command, commandStr, sockets, address):
        # Compose the message in our known message format
        if (command == self.NAT_REQUEST_MODELDEF or command == self.NAT_REQUEST_FRAMEOFDATA):
            self.packetSize=0
            commandStr=""
        elif (command == self.NAT_REQUEST):
            self.packetSize=len(commandStr) + 1
        elif (command == self.NAT_PING):
            commandStr="Ping"
            self.packetSize=len(commandStr) + 1

        data=struct.pack('<H', command)

        data += struct.pack('<H', self.packetSize)

        data += commandStr.encode('utf-8')
        data += b'\0'

        sockets.sendto(data, address)

    def run(self):
        # Create the data socket
        self.dataSocket=self.__createDataSocket(self.data_port, self.client_ip)
        if (self.dataSocket is None):
            trace("Could not open data channel")
            exit

        # Create the command socket
        self.commandSocket=self.__createCommandSocket()
        if (self.commandSocket is None):
            trace("Could not open command channel")
            exit

        # Create a separate thread for receiving data packets
        self.dataThread=Thread(target=self.__dataThreadFunction,
                                 args=(self.dataSocket,))
        self.dataThread.start()

        # Create a separate thread for receiving command packets
        self.commandThread=Thread(
            target=self.__dataThreadFunction, args=(self.commandSocket,))
        self.commandThread.start()
        trace('Data threads started!')

        self.__sendCommand(self.NAT_PING, "",
                           self.commandSocket, (self.server_address, self.command_port))

        self.__sendCommand(self.NAT_REQUEST_MODELDEF, "",
                           self.commandSocket, (self.server_address, self.command_port))


if __name__ == '__main__':
    VERBOSE=True

    # This is a callback function that gets connected to the NatNet client. It is called once per rigid body per frame

    rigid_body_name = "RigidBody 1"

    def receiveRigidBodyFrame(id, position, rotation, rigidBodyDescriptor):
        if rigidBodyDescriptor:
            if rigid_body_name in rigidBodyDescriptor:
                if id == rigidBodyDescriptor[rigid_body_name][0]:
                    print("Received frame for rigid body {}:\n id: {} \n position: {}\n rotation: {}".format(rigid_body_name,
                        id, position, rotation))

    # This will create a new NatNet client
    streamingClient=OptiTrackPythonClient(client_ip='192.168.2.101')

    # Configure the streaming client to call our rigid body handler on the emulator to send data out.
    streamingClient.rigidBodyListener=receiveRigidBodyFrame

    # Start up the streaming client now that the callbacks are set up.
    # This will run perpetually, and operate on a separate thread.
    streamingClient.run()

    while True:
        try:
            time.sleep(0.01)
        except KeyboardInterrupt:
            streamingClient.is_alive=False
            break