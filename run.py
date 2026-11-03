import sys

if __name__ == "__main__":
    if "--tick" in sys.argv:
        from powerpulse.executor import tick_once
        tick_once()
    else:
        from powerpulse.gui import main
        main()
