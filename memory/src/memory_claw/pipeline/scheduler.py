from __future__ import annotations

import time

from memory_claw.pipeline.extractor_runner import ExtractorRunner
from memory_claw.pipeline.reflector import Reflector
from memory_claw.pipeline.watcher import Watcher


class Scheduler:
    def __init__(self, watcher: Watcher, extractors: ExtractorRunner, reflector: Reflector, cfg) -> None:
        self.watcher = watcher
        self.extractors = extractors
        self.reflector = reflector
        self.cfg = cfg

    def run_forever(self) -> None:
        last_watcher = 0.0
        last_extractors = 0.0
        last_reflector = 0.0

        while True:
            now = time.monotonic()

            if now - last_watcher >= self.cfg.schedule.watcher_interval_minutes * 60:
                self.watcher.run_once()
                last_watcher = now

            if now - last_extractors >= self.cfg.schedule.extractor_interval_minutes * 60:
                self.extractors.run_once()
                last_extractors = now

            if now - last_reflector >= self.cfg.schedule.reflector_interval_minutes * 60:
                self.reflector.run_once()
                last_reflector = now

            time.sleep(1)
