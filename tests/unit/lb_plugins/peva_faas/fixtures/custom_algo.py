from __future__ import annotations


class CustomPolicy:
    def choose_batch(self, *, candidates, desired_size):
        return list(reversed(candidates))[:desired_size]

    def update_online(self, event):
        _ = event

    def update_batch(self, events):
        _ = events
