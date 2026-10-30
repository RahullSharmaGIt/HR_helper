import time


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter implemented in memory and Redis.
    Limits request rates per client key to protect upstream resources.
    """

    def __init__(self, rate: float = 10.0, capacity: int = 20):
        self.rate = rate
        self.capacity = capacity
        self.buckets: dict[str, tuple[float, float]] = {}

    async def acquire(self, key: str, cost: int = 1) -> tuple[bool, int]:
        now = time.time()
        bucket = self.buckets.get(key)
        if bucket is None:
            tokens = float(self.capacity)
            last_updated = now
        else:
            tokens, last_updated = bucket

        delta = max(0.0, now - last_updated)
        replenished = tokens + (delta * self.rate)
        tokens = min(float(self.capacity), replenished)

        if tokens >= cost:
            tokens -= cost
            self.buckets[key] = (tokens, now)
            return True, int(tokens)
        else:
            self.buckets[key] = (tokens, now)
            return False, 0
