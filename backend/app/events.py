import asyncio
from collections import defaultdict


class DeviceEventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, object]]]] = defaultdict(set)

    def subscribe(self, device_id: str) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=16)
        self._subscribers[device_id].add(queue)
        return queue

    def unsubscribe(self, device_id: str, queue: asyncio.Queue[dict[str, object]]) -> None:
        subscribers = self._subscribers.get(device_id)
        if not subscribers:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(device_id, None)

    def publish(self, device_id: str, event_type: str, data: object) -> None:
        event = {"type": event_type, "data": data}
        for queue in list(self._subscribers.get(device_id, ())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    continue


event_broker = DeviceEventBroker()
