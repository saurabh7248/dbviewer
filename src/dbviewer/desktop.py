"""Start the local API and open the DBViewer desktop window."""
import socket
import threading
import time
import webbrowser

from src.dbviewer.api.app import create_app
from src.dbviewer.config import DEFAULT_API_HOST, DEFAULT_API_PORT


def _find_port(host, preferred):
    with socket.socket() as sock:
        try: sock.bind((host, preferred)); return preferred
        except OSError:
            sock.bind((host, 0)); return sock.getsockname()[1]


def launch(host=DEFAULT_API_HOST, port=DEFAULT_API_PORT, open_browser=True):
    app=create_app(); actual_port=_find_port(host,port)
    thread=threading.Thread(target=lambda:app.run(host=host,port=actual_port,debug=False,use_reloader=False,threaded=True),daemon=True)
    thread.start(); url=f"http://{host}:{actual_port}/"
    for _ in range(50):
        try:
            with socket.create_connection((host,actual_port),timeout=.1): break
        except OSError: time.sleep(.1)
    try:
        import webview
        webview.create_window("DBViewer",url,width=1400,height=900,min_size=(900,600)); webview.start()
    except ImportError:
        if open_browser: webbrowser.open(url)
        print(f"DBViewer is running at {url}. Press Ctrl+C to stop.")
        try: thread.join()
        except KeyboardInterrupt: pass
    return thread
