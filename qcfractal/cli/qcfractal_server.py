"""
A command line interface to the qcfractal server.
"""

import sys
import argparse
import secrets
import yaml
import shutil
import qcfractal

from ..config import DatabaseSettings, FractalConfig, FractalServerSettings
from ..postgres_manipulation import shutdown_postgres, initialize_postgres
from .cli_utils import install_signal_handlers


def parse_args():
    parser = argparse.ArgumentParser(description='A CLI for the QCFractalServer.')
    subparsers = parser.add_subparsers(dest="command")

    ### Init subcommands
    init = subparsers.add_parser('init', help="Initializes a QCFractal server and database information.")
    db_init = init.add_argument_group('Database Settings')
    for field in DatabaseSettings.field_names():
        cli_name = "--db-" + field.replace("_", "-")
        db_init.add_argument(cli_name, **DatabaseSettings.help_info(field))

    server_init = init.add_argument_group('Server Settings')
    for field in FractalServerSettings.field_names():
        cli_name = "--" + field.replace("_", "-")
        server_init.add_argument(cli_name, **FractalServerSettings.help_info(field))

    init.add_argument("--overwrite", action='store_true', help="Overwrites the current configuration file.")
    init.add_argument("--base-folder", **FractalConfig.help_info("base_folder"))

    ### Start subcommands
    start = subparsers.add_parser('start', help="Starts a QCFractal server instance.")
    start.add_argument("--base-folder", **FractalConfig.help_info("base_folder"))

    fractal_args = start.add_argument_group('Server Settings')
    # Allow port and logfile to be altered on the fly
    for field in ["port", "logfile"]:
        cli_name = "--" + field.replace("_", "-")
        fractal_args.add_argument(cli_name, **FractalServerSettings.help_info(field))

    fractal_args.add_argument("--database-name",
                              default=None,
                              type=str,
                              help="The database to connect to, defaults to the default database name.")
    fractal_args.add_argument("--server-name", **FractalServerSettings.help_info("name"))
    fractal_args.add_argument(
        "--start-periodics",
        default=True,
        type=bool,
        help="Expert! Can disable periodic update (services, heartbeats) if False. Useful when running behind a proxy."
    )

    fractal_args.add_argument("--disable_ssl",
                              default=False,
                              type=bool,
                              help="Disables SSL if present, if False a SSL cert will be created for you.")
    fractal_args.add_argument("--tls-cert", type=str, default=None, help="Certificate file for TLS (in PEM format)")
    fractal_args.add_argument("--tls-key", type=str, default=None, help="Private key file for TLS (in PEM format)")

    compute_args = start.add_argument_group('Local Computation Settings')
    compute_args.add_argument("--local-manager",
                              const=-1,
                              default=None,
                              action='store',
                              nargs='?',
                              type=int,
                              help='Creates a local pool QueueManager attached to the server.')

    ### Config subcommands
    config = subparsers.add_parser('config', help="Starts a QCFractal server instance.")
    config.add_argument("--base-folder", **FractalConfig.help_info("base_folder"))

    ### Move args around
    args = vars(parser.parse_args())

    ret = {}
    ret["database"] = {}
    ret["fractal"] = {}
    for key, value, in args.items():

        # DB bucket
        if ("db_" in key) and (key.replace("db_", "") in DatabaseSettings.field_names()):
            if value is None:
                continue
            ret["database"][key.replace("db_", "")] = value

        # Fractal bucket
        elif key in FractalServerSettings.field_names():
            if value is None:
                continue
            ret["fractal"][key] = value

        # Additional base values that should be none
        elif key in ["base_folder"]:
            if value is None:
                continue
            ret[key] = value
        else:
            ret[key] = value

    if args["command"] is None:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return ret


def server_init(args, config):

    print("Initializing QCFractal configuration.")
    # Configuration settings

    config.base_path.mkdir(exist_ok=True)
    overwrite = args.get("overwrite", False)

    # Make sure we do not delete anything.
    if config.config_file_path.exists():
        print()
        if not overwrite:
            print("QCFractal configuration file already exists, to overwrite use '--overwrite' "
                  "or use the `qcfractal-server config` command line to alter settings.")
            sys.exit(2)
        else:
            print("!WARNING! A QCFractal configuration is currently initalized")
            print(
                f"!WARNING! Overwriting will delete all current Fractal data, this includes all data in {str(config.database_path)}."
            )
            print("!WARNING! Please use `qcfractal-server config` to alter configuration settings instead.")
            print()
            print("!WARNING! If you are sure you wish to procede please type 'REMOVEALLDATA' below.")
            # inp = input("  > ")
            inp = "REMOVEALLDATA"
            print()
            if inp == "REMOVEALLDATA":
                print("All data will be removed from the current QCFractal instance.")
                shutdown_postgres(config)
                shutil.rmtree(str(config.database_path), ignore_errors=True)
            else:
                print("Input does not match 'REMOVEALLDATA', exiting.")
                sys.exit(1)

    # WARNING! Passwords do not currently work.
    # if config.database.password is None:
    #     print("  Database password is None, generating a new private key.")
    #     config.database.password = secrets.token_urlsafe(16)

    print_config = config.dict()
    print_config["database"]["password"] = "**************"
    print_config = yaml.dump(print_config, default_flow_style=False)
    print("\n>>> Settings found:\n")
    print(print_config)

    print("\n>>> Setting up PostgreSQL...\n")
    config.database_path.mkdir(exist_ok=True)
    if config.database.own:
        initialize_postgres(config, quiet=False)
    else:
        print(
            "Own was set to False, QCFractal will expect a live PostgreSQL server with the above connection information."
        )

    print("\n>>> Writing settings...")
    config.config_file_path.write_text(yaml.dump(config.dict(), default_flow_style=False))

    print("\n>>> Finishing up...")
    print("\n>>> Success! Please run `qcfractal-server start` to boot a FractalServer!")


def server_config(config):

    print(f"Displaying QCFractal configuration:\n")
    print(yaml.dump(config.dict(), default_flow_style=False))


def server_start(args, config):

    print("Starting a QCFractal server.\n")

    print(f"QCFractal server base folder: {config.base_folder}")
    # Build an optional adapter
    if args["local_manager"]:
        ncores = args["local_manager"]
        if ncores == -1:
            ncores = None

        from concurrent.futures import ProcessPoolExecutor

        adapter = ProcessPoolExecutor(max_workers=ncores)

    else:
        adapter = None

    print("\n>>> Examining SSL Certificates...")
    # Handle SSL
    if args["disable_ssl"]:
        print("\nSSL disabled.")
        ssl_options = False
    else:
        ssl_certs = sum(args[x] is not None for x in ["tls_key", "tls_cert"])
        if ssl_certs == 0:
            ssl_options = True
            print("\nAutogenerated SSL certificates, clients must use 'verify=False' when connecting.")
        elif ssl_certs == 2:
            ssl_options = {"crt": args["tls_cert"], "key": args["tls_key"]}
            print("\nReading SSL certificates.")
        else:
            raise KeyError("Both tls-cert and tls-key must be passed in.")

    # Build the server itself
    if config.fractal.logfile is None:
        logfile = None
    else:
        logfile = str(config.base_path / config.fractal.logfile)

    try:
        server = qcfractal.FractalServer(
            name=args.get("server_name", None) or config.fractal.name,
            port=config.fractal.port,
            compress_response=config.fractal.compress_response,

            # Security
            security=config.fractal.security,
            allow_read=config.fractal.allow_read,
            ssl_options=ssl_options,

            # Database
            storage_uri=config.database_uri(safe=False, database=""),
            storage_project_name=args.get("database_name", None) or config.database.default_database,
            query_limit=config.fractal.query_limit,

            # Log options
            logfile_prefix=logfile,

            # Queue options
            heartbeat_frequency=config.fractal.heartbeat_frequency,
            max_active_services=config.fractal.max_active_services,
            queue_socket=adapter)

    except Exception as e:
        print("Fatal during server startup:\n")
        print(str(e))
        print("\nFailed to start the server, shutting down.")
        sys.exit(1)

    print("\n>>> QCFractal server initialized...")
    print(f"Server: {str(server)}")

    # Register closing
    install_signal_handlers(server.loop, server.stop)

    # Blocks until keyboard interupt
    print("\n>>> Starting QCFractal server...")
    server.start(start_periodics=args["start_periodics"])


def main(args=None):

    # Grab CLI args if not present
    if args is None:
        args = parse_args()
        print(args)

    command = args.pop("command")

    # More default manipulation to get supersets correct
    config_kwargs = ["base_folder", "fractal", "database"]
    config_args = {}
    for x in config_kwargs:
        if x in args:
            config_args[x] = args.pop(x)

    config = FractalConfig(**config_args)

    # Merge files
    if command != "init":
        if not config.base_path.exists():
            print(f"Could not find configuration file path: {config.base_path}")
            sys.exit(1)
        if not config.config_file_path.exists():
            print(f"Could not find configuration file: {config.config_file_path}")
            sys.exit(1)

        file_dict = FractalConfig(**yaml.load(config.config_file_path.read_text())).dict()
        config_dict = config.dict(skip_defaults=True)

        # Only fractal options can be changed by user input parameters
        file_dict["fractal"] = {**file_dict.pop("fractal"), **config_dict.pop("fractal")}

        config = FractalConfig(**file_dict)

    if command == "init":
        return server_init(args, config)
    elif command == "config":
        return server_config(args, config)
    elif command == "start":
        return server_start(args, config)


if __name__ == '__main__':
    main()
