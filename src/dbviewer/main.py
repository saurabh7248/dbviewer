"""DBViewer command-line entry point."""
import argparse
from src.dbviewer.desktop import launch


def main():
    parser=argparse.ArgumentParser(description="Multi-database diagnostic viewer")
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=5000)
    parser.add_argument("--no-browser",action="store_true")
    args=parser.parse_args()
    launch(args.host,args.port,not args.no_browser)


if __name__=="__main__": main()
