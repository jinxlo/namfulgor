# namwoo_app/celery_app.py
from celery import Celery

# Import Application Configuration
from .config import Config

# Import Flask App Factory
# Adjust this import if your create_app function is located elsewhere.
# e.g., from .app import create_app
from namwoo_app import create_app

# Create a Flask App Instance for Celery Context
flask_app_for_celery = create_app()

# Initialize Celery
celery_app = Celery(
    'namwoo_tasks',
    broker=Config.CELERY_BROKER_URL,
    backend=Config.CELERY_RESULT_BACKEND,
    include=['namwoo_app.celery_tasks']
)

# Celery Configuration
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    broker_connection_retry_on_startup=True
    # You can add other Celery configurations from Config object if needed:
    # e.g., task_acks_late=Config.CELERY_TASK_ACKS_LATE,
)

# Flask Application Context for Celery Tasks
class FlaskTask(Celery.Task):
    def __call__(self, *args, **kwargs):
        with flask_app_for_celery.app_context():
            return self.run(*args, **kwargs)

# Set the custom FlaskTask as the default base class for all tasks
celery_app.Task = FlaskTask

# The `if __name__ == '__main__':` block is generally not used for starting
# Celery workers in production. Workers are started via the Celery CLI:
# `celery -A namwoo_app.celery_app worker -l info`
#
# If you want to be able to run `python celery_app.py worker -l info` (less common):
# if __name__ == '__main__':
#     import sys
#     # This allows running "python celery_app.py worker ..."
#     if len(sys.argv) > 1 and sys.argv[1] in ('worker', 'beat', 'events', 'flower'):
#         celery_app.worker_main(sys.argv[1:])
#     else:
#         print("To start Celery components, use the Celery CLI, e.g.:")
#         print("  celery -A namwoo_app.celery_app worker -l info")
#         print("  celery -A namwoo_app.celery_app beat -l info")
#         # Or to enable direct `python celery_app.py worker ...`
#         # print("Or run: python celery_app.py worker -l info")