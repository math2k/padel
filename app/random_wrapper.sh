#!/bin/bash
# File: random_wrapper.sh

# Add a random delay between 0-180 seconds (3 minutes)
sleep $((RANDOM % 180))

# Replace with your actual script and its arguments
cd /var/www/vhosts/padel.math2k.net/padel/app
python3 monitor.py 
~                 
