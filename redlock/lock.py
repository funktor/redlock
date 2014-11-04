"""Distributed locks with Redis
"""

from datetime import datetime
import random
import time
import uuid

import redis


DEFAULT_RETRY_TIMES = 3
DEFAULT_RETRY_DELAY = 200
DEFAULT_TTL = 1000
CLOCK_DRIFT_FACTOR = 0.01
RELEASE_LUA_SCRIPT = """
    if redis.call("get",KEYS[1]) == ARGV[1] then
        return redis.call("del",KEYS[1])
    else
        return 0
    end
"""


class RedLockFactory(object):

    def __init__(self):
        self.redis_nodes = []

        for conn in connections:
            node = redis.StrictRedis(**conn)
            node._release_script = node.register_script(RELEASE_LUA_SCRIPT)
            self.redis_nodes.append(node)


class RedLock(object):

    """
    """

    def __init__(self, resource, connections,
                 retry_times=DEFAULT_RETRY_TIMES,
                 retry_delay=DEFAULT_RETRY_DELAY,
                 ttl=DEFAULT_TTL):

        self.resource = resource
        self.retry_times = retry_times
        self.retry_delay = retry_delay
        self.ttl = ttl

        self.redis_nodes = []

        for conn in connections:
            node = redis.StrictRedis(**conn)
            node._release_script = node.register_script(RELEASE_LUA_SCRIPT)
            self.redis_nodes.append(node)
        self.quorum = len(self.redis_nodes) / 2 + 1

    def __enter__(self):
        self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()

    def acquire_node(self, node):
        return node.set(self.resource, self.lock_key, nx=True, px=self.ttl)

    def release_node(self, node):
        node._release_script(keys=[self.resource], args=[self.lock_key])

    def acquire(self):
        self.lock_key = uuid.uuid4().hex

        for retry in range(self.retry_times):
            acquired_node_count = 0
            start_time = datetime.utcnow()

            for node in self.redis_nodes:
                if self.acquire_node(node):
                    acquired_node_count += 1

            end_time = datetime.utcnow()
            elapsed_milliesconds = (end_time - start_time).microseconds / 1000

            # Add 2 milliseconds to the drift to account for Redis expires
            # precision, which is 1 milliescond, plus 1 millisecond min drift
            # for small TTLs.
            drift = (self.ttl * CLOCK_DRIFT_FACTOR) + 2

            if acquired_node_count >= self.quorum and self.ttl > (elapsed_milliesconds + drift):
                return True
            else:
                for node in self.redis_nodes:
                    self.release_node(node)
                time.sleep(random.randint(0, self.retry_delay)/1000.0)
        return False

    def release(self):
        for node in self.redis_nodes:
            self.release_node(node)