#!/bin/bash

# This script outputs some useful information so we can see what parallel
# and srun are doing.

sleepsecs=$[ $RANDOM % 10 + 10 ]

task="rm -r run$1"
$task 

# $1 is arg1:{1} from GNU parallel.

# Sleep a random amount of time.
sleep $sleepsecs
