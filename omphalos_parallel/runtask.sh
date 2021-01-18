#!/bin/bash

# This script outputs some useful information so we can see what parallel
# and srun are doing.

sleepsecs=$[ $RANDOM % 10 + 10 ]


task="python3 /home/af606/Omphalos/omphalos_parallel/slurm_exec.py $1 $2"
$task 

# $1 is arg1:{1} from GNU parallel.
#
# $PARALLEL_SEQ is a special variable from GNU parallel. It gives the
# number of the job in the sequence.
#
# Here we print the sleep time, host name, and the date and time.
echo $task seq:$PARALLEL_SEQ sleep:$sleepsecs host:$(hostname) date:$(date)

# Sleep a random amount of time.
sleep $sleepsecs
