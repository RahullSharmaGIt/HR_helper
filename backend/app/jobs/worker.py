import logging
import sys

import redis
from rq import Worker

from app.config import settings

logger = logging.getLogger("worker")


def get_redis_connection() -> redis.Redis:
    """Creates a Redis connection using configured application settings."""
    return redis.from_url(settings.redis_url)


def run_worker(queues: list[str] | None = None, burst: bool = False) -> None:
    """Runs the RQ worker listening on specified queues.

    If burst=True, runs until all current jobs are processed and exits.
    """
    queue_names = queues or ["default"]
    logger.info(
        "Starting RQ worker on queues: %s (Redis URL: %s)",
        queue_names,
        settings.redis_url,
    )
    try:
        redis_conn = get_redis_connection()
        worker = Worker(queue_names, connection=redis_conn)
        worker.work(with_scheduler=True, burst=burst)
    except Exception:
        logger.exception("RQ worker encountered an unhandled exception")
        sys.exit(1)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_worker()
