#!/bin/bash
# Start the file server on port 8777 (file.adobefoundry.com)
cd "$(dirname "$0")"
pip install -q -r requirements.txt
nohup python3 app.py 8777 > server.log 2>&1 &
echo "File server started (PID $!), log: $(pwd)/server.log"
