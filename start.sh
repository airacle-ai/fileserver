#!/bin/bash
# Start the file server on port 41011
cd "$(dirname "$0")"
pip install -q -r requirements.txt
nohup python app.py 41011 > server.log 2>&1 &
echo "File server started (PID $!), log: $(pwd)/server.log"
