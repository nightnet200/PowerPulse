import sys

if __name__ == "__main__":
    if "--global-id" in sys.argv:
        from powerpulse.executor import tick_global_once
        index = sys.argv.index("--global-id")
        if index + 1 >= len(sys.argv):
            raise SystemExit("--global-id requiere un identificador")
        tick_global_once(sys.argv[index + 1])
    elif "--tick" in sys.argv:
        from powerpulse.executor import tick_once
        tick_once()
    else:
        from powerpulse.gui import main
        main()
