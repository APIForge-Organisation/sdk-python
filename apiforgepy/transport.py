import time


CIRCUIT_OPEN_S    = 60
FAILURE_THRESHOLD = 5


class LocalTransport:
    def __init__(self, db):
        self._db = db
        self._failures = 0
        self._open_until = 0.0

    def write(self, rows: list[dict]):
        if not rows:
            return
        if time.time() < self._open_until:
            return
        try:
            self._db.insert_batch(rows)
            self._failures = 0
        except Exception as e:
            self._failures += 1
            if self._failures >= FAILURE_THRESHOLD:
                self._open_until = time.time() + CIRCUIT_OPEN_S
                self._failures = 0
                print(f"[apiforgepy] SQLite write failures — pausing for {CIRCUIT_OPEN_S}s. Error: {e}")
