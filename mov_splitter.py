#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
  elphel-mov-splitter - Elphel MOV to jp4 splitter

  Copyright (c) 2014 FOXEL SA - http://foxel.ch
  Please read <http://foxel.ch/license> for more information.


  Author(s):

       Kevin Velickovic <k.velickovic@foxel.ch>


  This file is part of the FOXEL project <http://foxel.ch>.

  This program is free software: you can redistribute it and/or modify
  it under the terms of the GNU Affero General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU Affero General Public License for more details.

  You should have received a copy of the GNU Affero General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.


  Additional Terms:

       You are required to preserve legal notices and author attributions in
       that material or in the Appropriate Legal Notices displayed by works
       containing it.

       You are required to attribute the work as explained in the "Usage and
       Attribution" section of <http://foxel.ch/license>.
"""

# Imports
import calendar
import datetime
import getopt
import glob
import os
import Queue
import shutil
import signal
import string
import sys
import threading
import time
from cStringIO import StringIO
from datetime import datetime
from functools import wraps

import exifread

# Global variables
QUEUE_Done     = 0
QUEUE_Count    = 0
QUEUE_Slots    = []
CAMERA_MODULES = 9

# KML file header
KML_Header = \
"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://earth.google.com/kml/2.2">
<Document>"""

# KML file entry
KML_Entry = \
"""<PhotoOverlay>
    <Camera>
        <longitude>%f</longitude>
        <latitude>%f</latitude>
        <altitude>%s</altitude>
        <heading>%d</heading>
        <tilt>%d</tilt>
        <roll>%d</roll>
    </Camera>
    <Icon>
        <href>%s</href>
    </Icon>
</PhotoOverlay>
"""

# KML file footer
KML_Footer = \
"""</Document>
</kml>"""

# Config variables
DEBUG_MODE = 0
NO_COLORS  = 0
NO_FILTER  = 0
QUIET_MODE = 0
LOG_FILE   = ""

# MOV file container class
class MovFile:
    def __init__(self, path, modulename):
        self.path = path
        self.module = int(modulename)

# JP4 file container class
class JP4Image:
    def __init__(self, timestamp, module, base_folder=-1, threadid=-1):
        self.timestamp = timestamp
        self.module = int(module)
        self.base_folder = int(base_folder)
        self.threadid = threadid

        # Compute default path
        if self.base_folder != -1:
            if threadid != -1:
                self.path = "%s/%s/%s_%s" % (threadid, base_folder, timestamp, module)
            else:
                self.path = "%s/%s_%s" % (base_folder, timestamp, module)
        else:
            if threadid != -1:
                self.path = "%s/%s_%s" % (threadid, timestamp, module)
            else:
                self.path = "%s_%s" % (timestamp, module)

# Function to print debug messages
def ShowMessage(Message, Type=0, Halt=0, ThreadID=-1):

    # Flush stdout
    sys.stdout.flush()

    # Get current date
    DateNow = datetime.now().strftime("%H:%M:%S")

    # Display proper message
    Prepend = ""

    if ThreadID != -1:
        Prepend = "[Thread %d]" % (ThreadID+1)

    # Write to log file
    if len(LOG_FILE) > 0:
        with open(LOG_FILE, "a+") as logFile:
            logFile.write("%s %s[INFO] %s\n" % (DateNow, Prepend, Message))

    if Type == 0:
        if NO_COLORS:
            sys.stdout.write("%s %s[INFO] %s\n" % (DateNow, Prepend, Message))
        else:
            sys.stdout.write("%s \033[32m%s[INFO]\033[39m %s\n" % (DateNow, Prepend, Message))
    elif Type == 1:
        if NO_COLORS:
            sys.stdout.write("%s %s[WARNING] %s\n" % (DateNow, Prepend, Message))
        else:
            sys.stdout.write("%s \033[33m%s[WARNING]\033[39m %s\n" % (DateNow, Prepend, Message))
    elif Type == 2:
        if NO_COLORS:
            sys.stdout.write("%s %s[ERROR] %s\n" % (DateNow, Prepend, Message))
        else:
            sys.stdout.write("%s \033[31m%s[ERROR]\033[39m %s\n" % (DateNow, Prepend, Message))
    elif Type == 3:
        if NO_COLORS:
            sys.stdout.write("%s %s[DEBUG] %s\n" % (DateNow, Prepend, Message))
        else:
            sys.stdout.write("%s \033[34m%s[DEBUG]\033[39m %s\n" % (DateNow, Prepend, Message))

    # Flush stdout
    sys.stdout.flush()

    # Halt program if requested
    if Halt:
        sys.exit()

# Function to catch CTRL-C
def signal_handler(_signal, _frame):
    del _signal
    del _frame

    ShowMessage("Interrupted!", 2, 1)
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

# Function to moditor execution time of functions
def timed(f):
    @wraps(f)
    def wrapper(*args, **kwds):

        # Start timer initialization
        if DEBUG_MODE:
            start = time.time()

        # Call original function
        result = f(*args, **kwds)

        # Show final result
        if DEBUG_MODE:
            elapsed = time.time() - start
            ShowMessage("%s took %ds to finish" % (f.__name__, elapsed), 3)

        return result
    return wrapper

# Function to determine if quiet mode is enabled
def quietEnabled():
    return QUIET_MODE

# Function to find all occurences of a given input
@timed
def find_all(a_str, sub):
    start = 0
    while True:
        # Find first element
        start = a_str.find(sub, start)

        # If no match found exit function
        if start == -1: return

        # If there is a match return it and process the next element
        yield start

        # Move pointer to next occurence
        start += len(sub)

# Function to count JPEG images inside a MOV file
@timed
def countMOV(InputFile, tid):

    # Local variables
    JPEGHeader    = b'\xff\xd8\xff\xe1'

    mov = open(InputFile, 'rb')
    mov_data = mov.read()
    mov.close()

    # Search all JPEG files inside the MOV file
    JPEG_Offsets     = list(find_all(mov_data, JPEGHeader))
    JPEG_Offsets_len = len(JPEG_Offsets)

    # Variable to store results
    Result = [0, 0, tid]

    # Store images count
    Result[0] = JPEG_Offsets_len

    # Iterate over all images
    for _Index, _Offset in enumerate(JPEG_Offsets):

        # Calculate the filesize for extraction
        if (_Index >= len(JPEG_Offsets) - 1):
            Size = len(mov_data) - _Offset
        else:
            Size = (JPEG_Offsets[_Index+1] - _Offset)

        # Increment images size
        Result[1] += Size

    # Return result
    return Result

# Thread function to count MOV files
def countMOV_Thread(Threads, InputFile, tid):

    # Add action to queue
    Threads.put(
        countMOV(InputFile, tid)
    )

# Function to extract JPEG images inside a MOV file
@timed
def extractMOV(tid, InputFile, OutputFolder, TrashFolder, ModuleName, Results_back):

    # Local variables
    JPEGHeader    = b'\xff\xd8\xff\xe1'
    Results       = [0, []]

    mov = open(InputFile, 'rb')
    mov_data = mov.read()
    mov.close()

    # Initialize results counter
    Results = Results_back
    Results[1] = []
    Results[2] = []

    # Search all JPEG files inside the MOV file
    JPEG_Offsets     = list(find_all(mov_data, JPEGHeader))
    JPEG_Offsets_len = len(JPEG_Offsets)

    # Display message when no headers are found inside the MOV file
    if JPEG_Offsets_len == 0:
        ShowMessage("No JPEG headers found in MOV file %s" % InputFile, 1)

    if Results[4] != 0:
        if not os.path.isdir("%s/0" % OutputFolder):
            os.makedirs("%s/0" % OutputFolder)

    # Walk over JPEG files positions
    for _Index, _Offset in enumerate(JPEG_Offsets):

        # Calculate the filesize for extraction
        if (_Index >= len(JPEG_Offsets) - 1):
            Size = len(mov_data) - _Offset
        else:
            Size = (JPEG_Offsets[_Index+1] - _Offset)

        # Extract JPEG from MOV file
        ImageData = mov_data[_Offset:(Size + _Offset if Size is not None else None)]

        # Extract EXIF data from JPEG file
        ImageData_File = StringIO(ImageData)
        EXIF_Tags = exifread.process_file(ImageData_File)
        ImageData_File.close()

        # Output file variables
        Output_Name = ""
        Output_Image = None

        # Error handling
        if len(EXIF_Tags) <= 0:

            # Print error
            ShowMessage("Failed to read EXIF data", 1, 0, tid)

            # Calculate filename
            Output_Name = "fail_%d_exif" % (Results[0])

            # Open output file
            Output_Image = open('%s/%s.jp4' % (TrashFolder, Output_Name), 'wb')

            # Print error
            ShowMessage("Saving image to %s/%s.jp4" % (TrashFolder, Output_Name), 1, 0, tid)

            # Increment fail counter
            Results[0] += 1
        else:

            # Calculate the output filename
            date_object = datetime.strptime(str(EXIF_Tags["Image DateTime"]), '%Y:%m:%d %H:%M:%S')
            epoch = calendar.timegm(date_object.utctimetuple())
            Output_Name = "%d_%s_%s" % (epoch, EXIF_Tags["EXIF SubSecTimeOriginal"], ModuleName)

            # Increment extracted files count
            Results[3] += 1

            # Save output folder
            OutDir = OutputFolder

            # Check if max files option is specified
            if Results[4] != 0:

                # Initialize base folder (0)
                OutDir = "%s/%s" % (OutputFolder, Results[6])

                # Check if extracted files exceed limit
                if Results[3] > Results[5]:

                    # Increment folder index
                    Results[6] += 1

                    # Increment actual limit by max files
                    Results[5] += Results[4]

                    # Determine output folder
                    OutDir = "%s/%s" % (OutputFolder, Results[6])

                    # Notify user about directory change
                    ShowMessage("Directory changed to %s due to files limit" % (OutDir), 0, 0, tid)

                    # Create directory if not exists
                    if not os.path.isdir(OutDir):
                        os.makedirs(OutDir)

            # Add timestamp to list
            if Results[4] != 0:
                Results[1].append("t%d/%d/%s" % (Results[7], Results[6], Output_Name))
                Results[2].append("t%d/%d/%s" % (Results[7], Results[6], Output_Name))
            else:
                Results[1].append("t%d/%s" % (Results[7], Output_Name))
                Results[2].append("t%d/%s" % (Results[7], Output_Name))

            # Open output file
            Output_Image = open('%s/%s.jp4' % (OutDir, Output_Name), 'wb')

        # write the file
        Output_Image.write(ImageData)
        Output_Image.close()

    return Results

# Thread function to extract MOV files
def extractMOV_Thread(tid, Threads, InputFile, OutputFolder, TrashFolder, ModuleName, Results_back):

    # Add action to queue
    Threads.put(
        extractMOV(
            tid,
            InputFile,
            OutputFolder,
            TrashFolder,
            ModuleName,
            Results_back
        )
    )

# Function to retrieve each timestamps into an array of strings
@timed
def getTimeStamps(Output):

    # local variable
    TimeStamps = []

    # Walk over jp4 files in the __Output__ folder
    for i in glob.glob("%s/*.jp4" % Output):

        # Retrieve just the filename
        Fname = i.split('/')
        Fname = Fname[len(Fname) - 1]

        # Extract timestamp from filename
        TimeStamp = "%s_%s" % (Fname.split('_')[0], Fname.split('_')[1])

        # Insert to list if timestamp are not present
        if TimeStamp not in TimeStamps:
            TimeStamps.append(TimeStamp)

    # Return timestamp list
    return sorted(TimeStamps)

# Function to move all incomplete sequences to __Trash__ folder, a complete sequence need to be 1-9
@timed
def filterImages(Output, Trash, Results):

    # Variable to store images informations
    TSList = {}
    ValidatedImages = []

    # Iterate over extracted images
    for elem in Results[2]:

        # Retrieve base folder if available and timestamp
        seg = elem.split('/')

        # Check presense of base folder
        if len(seg) > 2:

            # Extract parts (timestamp, microsec, module)
            parts = seg[2].split('_')

            # Build timestamp without module
            ts = "%s_%s" % (parts[0], parts[1])

            # Insert timestamp into list if not exists
            if not ts in TSList:
                TSList[ ts ] = {}

            # Insert module and base folder to list if module not exists
            if not parts[2] in TSList[ts]:
                TSList[ ts ][ int(parts[2]) ] = [seg[0], int(seg[1])]

        else:

            # Extract parts (timestamp, microsec, module)
            parts = seg[1].split('_')

            # Build timestamp without module
            ts = "%s_%s" % (parts[0], parts[1])

            # Insert timestamp into list if not exists
            if not ts in TSList:
                TSList[ts] = {}

            # Insert module into list if module not exists
            if not parts[2] in TSList[ts]:
                TSList[ts][int(parts[2])] = [seg[0], -1]

    # Walk over paths
    for ts in TSList:

        # Missing modules array
        Missing_Modules = []

        # Walk over modules range 1-9
        for i in range(1, CAMERA_MODULES + 1):

            # Check if module exists
            if not(i in TSList[ts]):

                # Append missing module to list
                Missing_Modules.append(i)

        # Check presense of missing modules
        if len(Missing_Modules) > 0:

            # Calculate modules to be removed
            ToRemove = [x for x in range(1, CAMERA_MODULES + 1) if x not in Missing_Modules]

            # Debug output
            if not quietEnabled():
                ShowMessage("Incomplete timestamp %s (Missing module(s) %s)" % (ts, str(Missing_Modules)[1:-1]), 1)

            # Iterate over missing modules
            for m in ToRemove:

                # Get subfolder (if not set is -1)
                SubFolder = TSList[ts][m][1]

                # Check presense of subfolder and calculate source file name
                if SubFolder != -1:
                    SourceFile = "%s/%s/%s/%s_%s.jp4" % (Output, TSList[ts][m][0], TSList[ts][m][1], ts, m)
                else:
                    SourceFile = "%s/%s/%s_%s.jp4" % (Output, TSList[ts][m][0], ts, m)

                # Calculate destination file name
                DestFile   = "%s/%s_%s.jp4" % (Trash, ts, m)

                # Check if dest trash file exists, if exists remove it
                if os.path.isfile(DestFile):
                    os.remove(DestFile)

                # Move file
                if os.path.isfile(SourceFile):
                    shutil.move(SourceFile, DestFile)
        else:
            # Iterate over possible modules
            for i in range(1, CAMERA_MODULES + 1):

                # Get base folder
                folder = TSList[ts][i][1]

                # Check presence of base folder
                if folder != -1:
                    ValidatedImages.append( JP4Image(ts, i, TSList[ts][i][1], TSList[ts][i][0]) )
                else:
                    ValidatedImages.append( JP4Image(ts, i, -1, TSList[ts][i][0]) )
    # Sort images
    ValidatedImages = sorted(ValidatedImages, key=lambda item: item.timestamp)

    # Return sorted result
    return ValidatedImages

# Function to rearange images into full modules sets
def rearrangeImages(Folder, Images, Output, Limit):

    # Scope variables
    Counter = 0
    Folder_Index = 0
    Limit_Counter = Limit
    Arranged_List = []

    # Iterate over images
    if Limit > 0:
        for image in Images:

            # Compute output directory
            OutDir = '%s/../%s' % (Output, Folder_Index)

            # Create output directory if not exists
            if not os.path.isdir(OutDir):
                os.makedirs(OutDir)

            # Compute source file name
            SourceFile = '%s/%s.jp4' % (Folder, image.path)

            # If file exists move it
            if os.path.isfile(SourceFile):
                shutil.move(SourceFile, '%s/%s_%d.jp4' % (OutDir, image.timestamp, image.module))
                Arranged_List.append( JP4Image(image.timestamp, image.module, Folder_Index, -1) )

            # Increment index
            Counter += 1

            # Check file limit
            if Counter > Limit_Counter and (Counter % CAMERA_MODULES == 0):
                Limit_Counter += Limit
                Folder_Index += 1
    else:
        for image in Images:
            # Compute output directory
            OutDir = '%s/..' % (Output)

            # Compute source file name
            SourceFile = '%s/%s.jp4' % (Folder, image.path)

            # If file exists move it
            if os.path.isfile(SourceFile):
                shutil.move(SourceFile, '%s/%s_%d.jp4' % (OutDir, image.timestamp, image.module))
                Arranged_List.append( JP4Image(image.timestamp, image.module, -1, -1) )

    # Return result
    return Arranged_List

# Function to convert a fractioned EXIF array into degrees
def array2degrees(dms):

    # Rounding factor
    _round=1000000

    # Splitting input values
    d = string.split(str(dms.values[0]), '/')
    m = string.split(str(dms.values[1]), '/')
    s = string.split(str(dms.values[2]), '/')

    # Variables padding
    if len(d) == 1:
        d.append(1)
    if len(m) == 1:
        m.append(1)
    if len(s) == 1:
        s.append(1)

    # Compute degrees
    rslt = float(d[0]) / float(d[1]) + (float(m[0]) / float(m[1])) / 60.0 + (float(s[0]) / float(s[1])) / 3600.0

    # Return result
    return round(_round*rslt)/_round

# Function to convert a fractioned EXIF altidute into meters
def parseAlt(alt):

    # Rounding factor
    _round=1000000

    # Splitting input values
    a = string.split(str(alt), '/')

    # Variables padding
    if len(a) == 1:
        a.append(1)

    # Compute altitude
    rslt = float(a[0]) / float(a[1])

    # Return result
    return round(_round*rslt)/_round

# Function to convert bytes to an human readable file size
def human_size(nbytes):

    # Units
    suffixes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

    # Check for zero input
    if nbytes == 0: return '0 B'
    i = 0

    # Convert input
    while nbytes >= 1024 and i < len(suffixes)-1:
        nbytes /= 1024.
        i += 1
    f = ('%.2f' % nbytes).rstrip('0').rstrip('.')

    # Return result
    return '%s %s' % (f, suffixes[i])

# Function to generate KML file
@timed
def generateKML(Input, BaseURL, Results):

    # Open KML file for writing
    KML_File = open("%s/../map_points.kml" % Input, "wb")

    # Write header
    KML_File.write(KML_Header)

    # Build a list with only module 1
    List = []
    for image in Results:
        if image.module == 1:
            List.append("%s.jp4" % (image.path))

    if len(List) <= 0:
        ShowMessage("Nothing to generate", 1)
        return

    if not quietEnabled():
        ShowMessage("Generating %d entries..." % len(List))

    # Walk over files
    for f in List:

        # Determine base path
        BasePath = ""

        # Split base path
        segs = f.split('/')

        # Check base path presence, and calculate apropriate result
        if len(segs) > 1:
            BasePath = "%s/%s/%s" % (BaseURL, segs[0], segs[1])
        else:
            BasePath = "%s/%s" % (BaseURL, f)


        # Open image and extract EXIF data
        Image = open("%s/%s" % (Input, f), "rb")
        EXIFData = exifread.process_file(Image)
        Image.close()

        # Compute GPS data
        Longitude = (-1 if (EXIFData['GPS GPSLongitudeRef'] == "W") else 1) * array2degrees(EXIFData['GPS GPSLongitude'])
        Latitude  = (-1 if (EXIFData['GPS GPSLatitudeRef'] == "S") else 1)  * array2degrees(EXIFData['GPS GPSLatitude'])
        Altitude  = (-1 if (EXIFData['GPS GPSAltitudeRef'] == "S") else 1)  * parseAlt(EXIFData['GPS GPSAltitude'])

        Heading = 0
        Tilt    = 90
        Roll    = 0

        if 'GPS GPSImgDirection' in EXIFData:

            # Compute GPS data
            Heading = parseAlt(EXIFData['GPS GPSImgDirection'])
            Tilt    = (-1 if (EXIFData['GPS GPSDestLatitudeRef'] == "S") else 1) * array2degrees(EXIFData['GPS GPSDestLatitude']) + 90.0

            if (Tilt < 0):
                Tilt = 0
            elif (Tilt > 180):
                Tilt = 180

            Roll = (-1 if (EXIFData['GPS GPSDestLongitudeRef'] == "W") else 1) * array2degrees(EXIFData['GPS GPSDestLongitude'])

        # Write KML entry
        KML_File.write(KML_Entry % (Longitude, Latitude, "{0:.1f}".format(Altitude), Heading, Tilt, Roll, BasePath))

    # Write KML footer
    KML_File.write(KML_Footer)

    # Close KML file
    KML_File.close()

# Function to merge threads results
@timed
def mergeResults(Source, Dest):

    # Merge Fail counter
    Dest[0] += Source[0]

    # Merge Extracted files timestamps
    for i in range(0, len(Source[1])):
        Dest[2].append(Source[1][i])

    # Merge Extracted files count
    Dest[3] += len(Source[1])

    # Merge file limit counter
    Dest[5] += Source[5]

    # Merge file limit dir index
    Dest[6] = Source[6]

# Function to get first available slot
def GetSlot(Slots):

    # Iterate over slots
    for i in range(0, len(Slots)):

        # If slot is not used return it
        if Slots[i] == 0:
            return i

# Function to count used slots
def UsedSlots(Slots):

    # Local result variable
    ret = 0

    # Iterate over slots
    for i in range(0, len(Slots)):

        # If slot is used increment result
        if Slots[i] == 1:
            ret += 1

    # Return result
    return ret

# MOV extraction data collector
# pylint: disable=W0602
@timed
def WorkerThread_MOVCollector(Source, Dest):

    # Global variables
    global QUEUE_Done, QUEUE_Slots

    # Infinite while
    while QUEUE_Done != -1:

        # Check if results queue is not empty
        if not Source.empty():

            # Retrieve the result
            Ret = Source.get()

            # Unlock thread slot
            QUEUE_Slots[Ret[7]] = 0

            # Merge results
            mergeResults(Ret, Dest)

            # Increment processed MOVs index
            QUEUE_Done  += 1

        # Wait 200ms
        time.sleep(0.2)

# MOV counting data collector
# pylint: disable=W0602
@timed
def WorkerThread_CountCollector(Source, Dest):

    # Global variables
    global QUEUE_Done, QUEUE_Slots

    # Infinite while
    while QUEUE_Done != -1:

        # Check if results queue is not empty
        if not Source.empty():

            # Retrieve the result
            Ret = Source.get()

            # Unlock thread slot
            QUEUE_Slots[Ret[2]] = 0

            Dest[0] += Ret[0]
            Dest[1] += Ret[1]

            # Increment processed MOVs index
            QUEUE_Done  += 1

        # Wait 200ms
        time.sleep(0.2)

# Main thread
# pylint: disable=W0602
@timed
def WorkerThread(__extractMOV_Results__, __extractMOV_Results_Template__, __countMOV_Results__, __Jobs__, __Count_Images__, __Total_Files__, __MOV_List_Optimized__, __Output__, __Trash__):

    # Global variables
    global QUEUE_Done, QUEUE_Slots

    # Local variables
    __Processed_Files__ = 1
    Threads = Queue.Queue()
    Threads_Results = []

    # Check if in counting mode
    if __Count_Images__ == 0:

        # Initialize default threads results containers
        for i in range(0, __Jobs__):
            Threads_Results.append(__extractMOV_Results_Template__[:])
            QUEUE_Slots.append(0)

        # Create collector thread
        CollectorThread = threading.Thread(
            target = WorkerThread_MOVCollector,
            args = (Threads, __extractMOV_Results__)
        )

        # Start collector thread
        CollectorThread.setDaemon(True)
        CollectorThread.start()

        # Loop until all MOVS are extracted
        while QUEUE_Done < __Total_Files__:

            # Insert a new item to the queue if not full
            if (UsedSlots(QUEUE_Slots) < __Jobs__) and (len(__MOV_List_Optimized__) > 0):

                # Get an available thread slot
                Index = GetSlot(QUEUE_Slots)

                # Pick one MOV file
                MOV = __MOV_List_Optimized__[0]

                # Debug output
                ShowMessage("Extracting (%d/%d): %s..." % (__Processed_Files__, __Total_Files__, MOV.path))

                # Issue 7980 fix
                datetime.strptime('', '')

                # Assign thread id
                Threads_Results[Index][7] = Index

                # Lock thread slot
                QUEUE_Slots[Index] = 1

                # Compute output folder
                Output = "%s/t%d" % (__Output__, Index)

                # Create dir if not exists
                if not os.path.isdir(Output):
                    os.makedirs(Output)

                # Create thread
                ThreadJob = threading.Thread(
                    target = extractMOV_Thread,
                    args = (Index, Threads, MOV.path, Output, __Trash__, MOV.module, Threads_Results[Index])
                )

                # Start thread
                ThreadJob.setDaemon(True)
                ThreadJob.start()

                # Increment index
                __Processed_Files__ += 1

                # Remove processed MOV file from list
                __MOV_List_Optimized__.pop(0)

            else:

                # Wait 200ms
                time.sleep(0.2)

        # Exit threads
        QUEUE_Done = -1

    else:

        # Initialize default threads results containers
        for i in range(0, __Jobs__):
            QUEUE_Slots.append(0)

        # Create collector thread
        CollectorThread = threading.Thread(
            target = WorkerThread_CountCollector,
            args = (Threads, __countMOV_Results__)
        )

        # Start collector thread
        CollectorThread.setDaemon(True)
        CollectorThread.start()

        # Loop until all MOVS are extracted
        while QUEUE_Done < __Total_Files__:

            # Insert a new item to the queue if not full
            if (UsedSlots(QUEUE_Slots) < __Jobs__) and (len(__MOV_List_Optimized__) > 0):

                # Get an available thread slot
                Index = GetSlot(QUEUE_Slots)

                # Pick one MOV file
                MOV = __MOV_List_Optimized__[0]

                # Debug output
                ShowMessage("Counting (%d/%d): %s..." % (__Processed_Files__, __Total_Files__, MOV.path))

                # Issue 7980 fix
                datetime.strptime('', '')

                # Lock thread slot
                QUEUE_Slots[Index] = 1

                # Create thread
                ThreadJob = threading.Thread(
                    target = countMOV_Thread,
                    args = (Threads, MOV.path, Index)
                )

                # Start thread
                ThreadJob.setDaemon(True)
                ThreadJob.start()

                # Increment index
                __Processed_Files__ += 1

                # Remove processed MOV file from list
                __MOV_List_Optimized__.pop(0)

            else:

                # Wait 200ms
                time.sleep(0.2)

        # Exit threads
        QUEUE_Done = -1

# Usage display function
def _usage():
    print """
    Usage: %s [OPTIONS]

    [Required arguments]
    -f --folder         Base working folder (where mov folder are)
    [and/or]
    -i --input          Input MOV folder
    -o --output         Output JP4 folder
    -t --trash          JP4 trash folder

    [Optional arguments]
    -h --help           Prints this

    -j --jobs           Jobs count (Threads)
    -x --modules        Number of JP4 modules (Default 9)
    -c --count          Don't extract MOV files, just count images
    -m --maxfiles       Max JP4 files per folder, will create folders 0, 1, 2, 3 to place next files
    -k --kmlbase        KML base url
    -g --filelist       Write final JP4 paths to file
    -l --logfile        Log file path
    -f --nofilter       Don't filter images (trashing)

    -d --debug          Debug mode
    -q --quiet          Quiet mode (Silent)
    -n --nocolors       Disable stdout colors

    """ % sys.argv[0]

# Program entry point function
# pylint: disable=W0603
def main(argv):

    # Global variables
    global CAMERA_MODULES

    # Arguments variables initialisation
    __Folder__       = ""
    __Input__        = ""
    __Output__       = ""
    __Trash__        = ""
    __Jobs__         = 1
    __Count_Images__ = 0
    __Max_Files__    = 0
    __FileList__     = ""
    __KMLBase__      = "__BASE__URL__"

    # Scope variables initialisation
    __Exec_Timer__         = time.clock()
    __MOV_List__           = []
    __MOV_List_Optimized__ = []
    __Total_Files__        = 0
    __countMOV_Results__ = [
        0, # Images count
        0, # Total images size
        0  # Thread id
    ]
    __extractMOV_Results_Template__ = [
        0,  # Fail counter
        [], # Last extracted files timestamps
        [], # Extracted files timestamps
        0,  # Extracted files count
        0,  # File limit value
        0,  # File limit counter
        0,  # File limit dir index
        0   # Thread id
    ]

    __extractMOV_Results__ = __extractMOV_Results_Template__[:]

    __Filtered_Images__ = []

    # Arguments parser
    try:
        opt, args = getopt.getopt(argv, "hf:i:o:t:k:g:j:x:cm:dql:nf", ["help", "folder=", "input=", "output=", "trash=", "kmlbase=", "filelist=", "jobs=", "modules=", "count", "maxfiles=", "debug", "quiet", "logfile=", "nocolors", "nofilter"])
        args = args
    except getopt.GetoptError, err:
        print str(err)
        _usage()
        sys.exit(2)
    for o, a in opt:
        if o in ("-h", "--help"):
            _usage()
            sys.exit()
        elif o in ("-f", "--folder"):
            __Folder__  = a.rstrip('/')
        elif o in ("-i", "--input"):
            __Input__  = a.rstrip('/')
        elif o in ("-o", "--output"):
            __Output__  = a.rstrip('/')
        elif o in ("-t", "--trash"):
            __Trash__  = a.rstrip('/')
        elif o in ("-j", "--jobs"):
            __Jobs__ = int(a)
        elif o in ("-x", "--modules"):
            CAMERA_MODULES = int(a)
        elif o in ("-c", "--count"):
            __Count_Images__ = 1
        elif o in ("-m", "--maxfiles"):
            __Max_Files__  = int(a)
            __extractMOV_Results_Template__[4] = __Max_Files__
            __extractMOV_Results_Template__[5] = __Max_Files__
        elif o in ("-k", "--kmlbase"):
            __KMLBase__  = a.rstrip('/')
        elif o in ("-g", "--filelist"):
            __FileList__ = a
        elif o in ("-d", "--debug"):
            global DEBUG_MODE
            DEBUG_MODE = 1
        elif o in ("-q", "--quiet"):
            global QUIET_MODE
            QUIET_MODE = 1
        elif o in ("-l", "--logfile"):
            global LOG_FILE
            LOG_FILE  = a
        elif o in ("-n", "--nocolors"):
            global NO_COLORS
            NO_COLORS = 1
        elif o in ("-f", "--nofilter"):
            global NO_FILTER
            NO_FILTER  = 1
        else:
            assert False, "unhandled option"

    # Base folder check
    if __Folder__:

        # Backup variables
        Input = __Input__
        Output = __Output__
        Trash = __Trash__

        # Calculate default paths
        __Input__ = ("%s/mov" % __Folder__)
        __Output__ = ("%s/jp4" % __Folder__)
        __Trash__ = ("%s/trash" % __Folder__)

        # Override paths
        if Input:
            __Input__ = Input
        if Output:
            __Output__ = Output
        if Trash:
            __Trash__ = Trash

    # Arguments checking
    if not __Input__:
        _usage()
        return

    if not __Count_Images__:
        if (not __Output__) or (not NO_FILTER and not __Trash__):
            _usage()
            return

    # Append temp folder to output path
    __Output__ = ("%s/temp" % __Output__)

    # Create default directories
    if __Output__ and not os.path.isdir(__Output__):
        os.makedirs(__Output__)

    if __Output__ and not os.path.isdir(__Output__):
        os.makedirs(__Output__)

    if __Trash__ and not os.path.isdir(__Trash__):
        os.makedirs(__Trash__)

    # Get modules from input folder
    CameraModules = sorted(os.listdir(__Input__))

    # Error handling
    if len(CameraModules) == 0:
        ShowMessage("No camera modules found in %s" % __Input__, 2, 1)

    # Insert all MOV files into a temporary array
    for mn in CameraModules:
        Movs = []
        for MOV in sorted(glob.glob("%s/%s/*.mov" % (__Input__, mn))):
            Movs.append( MovFile(MOV, mn) )
        __MOV_List__.append(Movs)

    # Sort MOV files
    while len(__MOV_List__) > 0:
        for MovArray in __MOV_List__:
            for MOV in MovArray:
                __MOV_List_Optimized__.append(MOV)
                __Total_Files__ += 1
                MovArray.pop(0)
                break
        if len(__MOV_List__[0]) <= 0:
            __MOV_List__.pop(0)

    # Debug output
    if not quietEnabled():

        if __Count_Images__ == 0:
            ShowMessage("Extracting MOV files...")
        else:
            ShowMessage("Counting MOV files...")

    # Error handling
    if __Total_Files__ == 0:
        ShowMessage("No MOV files", 2)

    #Create main thread
    MainThread = threading.Thread(
        target = WorkerThread,
        args = (__extractMOV_Results__, __extractMOV_Results_Template__, __countMOV_Results__, __Jobs__, __Count_Images__, __Total_Files__, __MOV_List_Optimized__, __Output__, __Trash__)
    )

    # Start main thread
    MainThread.setDaemon(True)
    MainThread.start()

    # Wait until main thread finishes
    while MainThread.is_alive():
        time.sleep(0.5)

    # Check presence of count mode
    if __Count_Images__ == 0:

        # Debug output
        if not quietEnabled():
            ShowMessage("Extraction done, %d image(s) extracted" % __extractMOV_Results__[3])

        # Filter check
        if not quietEnabled() and NO_FILTER == 0:
            # Debug output
            ShowMessage("Filtering images...")

            # Start image filtering
            __Filtered_Images__ = filterImages(__Output__, __Trash__, __extractMOV_Results__)

        # Check presence of max files option
        if __Max_Files__ != 0:

            # Clamp max files to 9
            if __Max_Files__ < CAMERA_MODULES:
                __Max_Files__ = CAMERA_MODULES

            # Convert limit to a power of 9
            Limit = (__Max_Files__ / CAMERA_MODULES) * CAMERA_MODULES

            # Debug output
            if not quietEnabled():
                ShowMessage("Rearranging images...")

            # Rearrange images
            __Aranged_Images__ = rearrangeImages(__Output__, __Filtered_Images__, __Output__, Limit)
        else:

            # Debug output
            if not quietEnabled():
                ShowMessage("Rearranging images...")

            # Rearrange images
            __Aranged_Images__ = rearrangeImages(__Output__, __Filtered_Images__, __Output__, -1)

        # Check if filelist option is specified
        if __FileList__:
            with open(__FileList__, "w") as f:
                for image in __Aranged_Images__:
                    f.write("%s\n" % image.path)

        # Debug output
        if not quietEnabled():
            ShowMessage("Starting KML file generation...")

        # Generate KML file
        generateKML('%s/..' % __Output__, __KMLBase__, __Aranged_Images__)

        # Remove temp folder
        shutil.rmtree(__Output__)

    else:

        # Debug output
        if not quietEnabled():
            ShowMessage("Total images: %d" % __countMOV_Results__[0])
            ShowMessage("Total size: %s" % human_size(__countMOV_Results__[1]))

    # Debug output
    if not quietEnabled():
        Delay = (time.clock() - __Exec_Timer__)
        ShowMessage("Done in %s" % time.strftime("%H:%M:%S", time.gmtime(Delay)))

# Program entry point
if __name__ == "__main__":
    main(sys.argv[1:])
