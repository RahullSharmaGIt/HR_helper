from ticket import ParkingTicket
from vehicle import Vehicle, VehicleType


class ParkingSpot:
    def __init__(self, spot_id: int, spot_type: VehicleType, floor: int):
        self.spot_id = spot_id
        self.spot_type = spot_type
        self.floor = floor
        self.vehicle: Vehicle | None = None

    def is_available(self) -> bool:
        return self.vehicle is None

    def assign_vehicle(self, vehicle: Vehicle) -> bool:
        if self.is_available() and vehicle.vehicle_type == self.spot_type:
            self.vehicle = vehicle
            return True
        return False

    def remove_vehicle(self) -> Vehicle | None:
        v = self.vehicle
        self.vehicle = None
        return v


class ParkingLot:
    def __init__(self, name: str, hourly_rate: float = 20.0):
        self.name = name
        self.hourly_rate = hourly_rate
        self.spots: dict[int, ParkingSpot] = {}
        self.active_tickets: dict[str, ParkingTicket] = {}

    def add_spot(self, spot: ParkingSpot) -> None:
        self.spots[spot.spot_id] = spot

    def park_vehicle(self, vehicle: Vehicle) -> ParkingTicket | None:
        for spot in self.spots.values():
            if spot.assign_vehicle(vehicle):
                ticket = ParkingTicket(vehicle=vehicle, spot_id=spot.spot_id)
                self.active_tickets[ticket.ticket_id] = ticket
                return ticket
        return None

    def unpark_vehicle(self, ticket_id: str) -> float:
        ticket = self.active_tickets.pop(ticket_id, None)
        if not ticket:
            raise ValueError(f"Invalid ticket id: {ticket_id}")
        spot = self.spots.get(ticket.spot_id)
        if spot:
            spot.remove_vehicle()
        ticket.close()
        duration_hours = max(1.0, (ticket.exit_time - ticket.entry_time).total_seconds() / 3600.0)
        return round(duration_hours * self.hourly_rate, 2)
