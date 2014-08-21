#!/usr/bin/env python
#
# elphel-mov-splitter - Elphel MOV to jp4 splitter using hachoir
#
# Copyright (c) 2013-2014 FOXEL SA - http://foxel.ch
# Please read <http://foxel.ch/license> for more information.
#
# Author(s):
#
#      Kevin Velickovic <k.velickovic@foxel.ch>
#
# This file is part of the FOXEL project <http://foxel.ch>.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#
# Additional Terms:
#
#      You are required to preserve legal notices and author attributions in
#      that material or in the Appropriate Legal Notices displayed by works
#      containing it.
#
#      You are required to attribute the work as explained in the "Usage and
#      Attribution" section of <http://foxel.ch/license>.

import sys
import glob
import os
import exifread
import shutil
from datetime import datetime


from hachoir_subfile.search import SearchSubfile
from hachoir_core.cmd_line import unicodeFilename
from hachoir_core.stream import FileInputStream

Input = ""
Output = ""
Trash = ""

Total_Files = 0
Processed_Files = 0

Modules = []

# Function to disable output on function call
class suppress_stdout_stderr(object):
    def __init__(self):
        # Open a pair of null files
        self.null_fds =  [os.open(os.devnull,os.O_RDWR) for x in range(2)]
        # Save the actual stdout (1) and stderr (2) file descriptors.
        self.save_fds = (os.dup(1), os.dup(2))

    def __enter__(self):
        # Assign the null pointers to stdout and stderr.
        os.dup2(self.null_fds[0],1)
        os.dup2(self.null_fds[1],2)

    def __exit__(self, *_):
        # Re-assign the real stdout/stderr back to (1) and (2)
        os.dup2(self.save_fds[0],1)
        os.dup2(self.save_fds[1],2)
        # Close the null files
        os.close(self.null_fds[0])
        os.close(self.null_fds[1])

# Function to retrive each timestamps into an array of strings
def getTimeStamps():
	TimeStamps = []

	for i in glob.glob("%s/*.jp4" % Output):
		Fname = i.split('/')
		Fname = Fname[len(Fname) - 1]

		TimeStamp = "%s_%s" % (Fname.split('_')[0], Fname.split('_')[1])

		if TimeStamp not in TimeStamps:
			TimeStamps.append(TimeStamp)

	return sorted(TimeStamps)

# Function to rename all images generated images by hachoir to a correct format (UnixTimeSTamp_SubSecTime_Module.jp4)
def renameImages(mn):
	for fn in glob.glob("%s/%s" % (Output, "file-*.jpg")):
		f = open(fn, 'rb')
		tags = exifread.process_file(f)
		f.close()

		date_object = datetime.strptime(str(tags["Image DateTime"]), '%Y:%m:%d %H:%M:%S')
		OutName = "%s_%s_%s" % (date_object.strftime("%s"), tags["EXIF SubSecTimeOriginal"], mn)

		os.rename(fn, "%s/%s.jp4" % (Output, OutName))

# Function to move all incomplete sequences to Trash folder, a complete sequence need to be 1-9
def filterImages():
	for ts in getTimeStamps():

		for i in range(1, 10):
			FileName = "%s/%s_%s.jp4" % (Output, ts, i)

			if not(os.path.isfile(FileName)):
				print "Incomplete timestamp %s" % ts
				os.system("mv %s/%s* %s" % (Output, ts, Trash))
				break
			else:
				continue

# Program entry point function
def main():
	global Input, Output, Trash

	if len(sys.argv) < 4:
		print "Usage: %s <Input folder> <Output folder> <Trash folder>" % sys.argv[0]
		return

	Input = sys.argv[1].rstrip('/')
	Output = sys.argv[2].rstrip('/')
	Trash = sys.argv[3].rstrip('/')

	Modules = sorted(os.listdir(Input))

	Module_Index = 1

	print "Extracting MOV files..."
	for mn in Modules:
		print "Processing module %d/%d..." % (Module_Index, len(Modules))

		MovList = glob.glob("%s/%s/*.mov" % (Input, mn))
		Total_Files = len(MovList)
		Processed_Files = 1

		for fn in MovList:
			print "Extracting (%d/%d): %s..." % (Processed_Files, Total_Files, fn)
			
			stream = FileInputStream(unicodeFilename(fn), real_filename=fn)
			
			subfile = SearchSubfile(stream, 0, None)
			subfile.verbose = False
			subfile.setOutput(Output)
			subfile.loadParsers(categories=["images"], parser_ids=["jpeg"])
			
			with suppress_stdout_stderr():
				subfile.main()

			print "Renaming images..."
			renameImages(mn)

			Processed_Files+=1

		Module_Index+=1 

	print "Filtering images..."
	filterImages()

# Program entry point
if __name__ == "__main__":
    main()