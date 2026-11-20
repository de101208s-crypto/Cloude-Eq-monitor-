import json
import time
import websocket  # py -m pip install -U websocket-client

PROJECT_ID = "YOUR_PROJECT_ID"
USER = "YOUR_USERNAME"
CONTACT = "https://example.com/"
VAR_NAME = "eqquake"
VALUE = "123"

ws = websocket.create_connection(
    "wss://clouddata.turbowarp.org/",
    header=[f"User-Agent: my-script (contact: {CONTACT})"],
    timeout=10,
)
try:
    ws.send(json.dumps({"method": "handshake", "user": USER, "project_id": PROJECT_ID}))
    time.sleep(0.3)
    ws.send(json.dumps({"method": "set", "user": USER, "project_id": PROJECT_ID,
                        "name": "\u2601 " + VAR_NAME, "value": VALUE}))
    time.sleep(0.3)
finally:
    ws.close()
print("送信済み")
