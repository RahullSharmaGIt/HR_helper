import datetime
import uuid

from vehicle import Vehicle


class ParkingTicket:
    def __init__(self, vehicle: Vehicle, spot_id: int):
        self.ticket_id = f"TICK-{uuid.uuid4().hex[:8].upper()}"
        self.vehicle = vehicle
        self.spot_id = spot_id
        self.entry_time = datetime.datetime.now(datetime.timezone.utc)
        self.exit_time: datetime.datetime | None = None
        self.fee: float | None = None

    def close(self) -> None:
        self.exit_time = datetime.datetime.now(datetime.timezone.utc)
