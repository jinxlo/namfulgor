# /home/ec2-user/namwoo_app/run.py
import os
import sys
import logging

# Basic logging setup for this entrypoint script.
# If the app creation fails before the app's logger is configured,
# these messages will still be captured.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
entrypoint_logger = logging.getLogger("namfulgor.run_entrypoint") # More specific logger name

# The sys.path manipulations are generally not needed when WORKDIR is correctly set
# in Docker and the application package is correctly identified.
# Given the flat structure, Python's default import mechanism for scripts
# in the current directory should work.

try:
    # MODIFIED: Import create_app from '__init__.py' in the current directory.
    # This assumes your app factory (create_app function) is defined in
    # /usr/src/app/__init__.py inside the Docker container,
    # which corresponds to /home/ec2-user/namwoo_app/__init__.py on your EC2 host.
    entrypoint_logger.info("Attempting to import 'create_app' from '__init__.py' in current directory...")
    from __init__ import create_app # <--- THIS IS THE CORRECTED IMPORT
    entrypoint_logger.info("'create_app' imported successfully from '__init__.py'.")

except ImportError as e:
    # This failure means Python cannot find 'create_app' in the '__init__.py'
    # file located in the same directory as this run.py script.
    # This could be due to:
    # 1. '__init__.py' missing from /usr/src/app (or corresponding host path).
    # 2. '__init__.py' exists but does not define a function named 'create_app'.
    # 3. A typo in 'create_app' within '__init__.py'.
    entrypoint_logger.critical(
        f"CRITICAL IMPORT ERROR: Failed to import 'create_app' from '__init__.py' in the current directory. "
        f"Ensure '__init__.py' exists in the working directory and defines 'create_app'. Error: {e}",
        exc_info=True # Includes traceback for detailed debugging
    )
    # Print to stderr as well, in case logging isn't fully flushed or visible.
    print(
        f"FATAL: Could not import 'create_app' from '__init__.py'. "
        f"Check logs for details. Error: {e}",
        file=sys.stderr
    )
    sys.exit(1) # Exit immediately, Gunicorn worker will fail to boot.

except Exception as e:
    # Catch any other unexpected errors during the import phase.
    entrypoint_logger.critical(
        f"UNEXPECTED CRITICAL ERROR during import of 'create_app': {e}",
        exc_info=True
    )
    print(
        f"FATAL: Unexpected error during import of 'create_app'. Error: {e}",
        file=sys.stderr
    )
    sys.exit(1)


# Create the Flask app instance using the factory.
# This is the 'app' instance that Gunicorn will look for.
try:
    entrypoint_logger.info("Calling 'create_app()' to instantiate the Flask application...")
    app = create_app() # The create_app function should handle its own internal logging.
    # The app's own logger should now take over for app-specific messages.
    # For example, if create_app configures Flask's app.logger.
    if app and hasattr(app, 'logger'):
        app.logger.info("Flask application (NamFulgor) created successfully by factory in run.py.")
    else:
        entrypoint_logger.info("Flask application (NamFulgor) created (basic check, app logger not confirmed).")

except Exception as e:
    # Catch critical errors during app creation itself (e.g., config loading, early init failures)
    # The app's logger might not be configured yet if the failure is very early in create_app.
    entrypoint_logger.critical(
        "!!! CRITICAL ERROR DURING FLASK APP CREATION (call to create_app()) IN RUN.PY (NamFulgor) !!!",
        exc_info=True
    )
    print(
        f"FATAL: Failed to create Flask app (NamFulgor) in run.py during create_app() call: {e}",
        file=sys.stderr
    )
    sys.exit(1) # Exit here if the app cannot even be created, Gunicorn will fail anyway.


# This block is for running the Flask development server directly
# (e.g., `python run.py` for local testing).
# It is NOT executed when Gunicorn runs the application.
if __name__ == '__main__':
    # Get host and port from environment variables or use defaults
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0') # Listen on all interfaces
    try:
        port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    except ValueError:
        entrypoint_logger.warning("Invalid FLASK_RUN_PORT value. Using default port 5000.")
        port = 5000

    # Get debug setting from the app's configuration (which was loaded by create_app)
    # Ensure 'app' is not None before accessing app.config
    if app:
        debug_mode = app.config.get('DEBUG', False) # Default to False if DEBUG key missing
    else:
        entrypoint_logger.error("Flask app object is None, cannot determine debug_mode. Defaulting to False.")
        debug_mode = False # Fallback, though app creation failure should have exited.

    entrypoint_logger.info(f"Starting NamFulgor Flask development server on http://{host}:{port}/ (Debug Mode: {debug_mode})")
    print(f"[*] NamFulgor Flask app '{app.name if app and hasattr(app, 'name') else 'UNKNOWN'}' running on http://{host}:{port}/")
    print(f"[*] Debug mode is: {'on' if debug_mode else 'off'}")
    print("[!] WARNING: This is a development server. Do not use it in a production deployment.")
    print("[!] Use a production WSGI server like Gunicorn.")
    print("    For Docker, Gunicorn is typically invoked via the CMD in your Dockerfile.")
    print("Press CTRL+C to quit")

    # Run the Flask development server
    # use_reloader=debug_mode enables auto-restarts on code changes when debug_mode is True.
    try:
        if app: # Ensure app object exists before trying to run it
            app.run(host=host, port=port, debug=debug_mode, use_reloader=debug_mode)
        else:
            entrypoint_logger.critical("Cannot start development server: Flask app object is None.")
            print("FATAL: Cannot start development server, Flask app object is None.", file=sys.stderr)
    except Exception as e:
         entrypoint_logger.exception("NamFulgor Flask development server failed to start or crashed.")
         print(f"Error starting development server: {e}", file=sys.stderr)

# When Gunicorn runs this file (e.g., gunicorn 'run:app'),
# it looks for an object named 'app' at the module level.
# The 'app = create_app()' line above provides this.
# The `if __name__ == '__main__':` block is skipped by Gunicorn.