#!/bin/bash

# Start the Telegram notifier in the background
source venv/bin/activate
python notifier.py &
NOTIFIER_PID=$!

# Start the Streamlit app headlessly to avoid email prompt
streamlit run app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true

# Trap SIGINT and SIGTERM to kill the notifier when streamlit stops
trap "kill $NOTIFIER_PID" SIGINT SIGTERM EXIT
