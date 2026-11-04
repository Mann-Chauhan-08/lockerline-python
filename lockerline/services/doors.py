"""The wall. State is derived on read — `holding` when a parcel sits in the door, `free` otherwise.
The size and state filters arrive already validated (typed query parameters); `free` counts the doors after them."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..clock import Clock, as_utc
from ..errors import NoSuchDoor, NoSuchTower
from ..ids import parcel_public
from ..models import Door, Parcel, Tower
from ..schemas import DoorListItem, DoorOut, DoorsOut, DoorState, SizeClass

SIZES = ("S", "M", "L")

def get_tower(session: Session, code: str) -> Tower:
    tower = session.scalar(select(Tower).where(Tower.code == code))
    if not tower:
        raise NoSuchTower()
    return tower

def door_state(current_parcel_id: int | None) -> DoorState:
    return "free" if current_parcel_id is None else "holding"


def _dwell(parcel: Parcel, clock: Clock) -> int:
    return int((clock.now() - as_utc(parcel.dropped_at)).total_seconds())


def list_doors(
    session: Session, tower: str, size: SizeClass | None, state: DoorState | None, clock: Clock
) -> DoorsOut:
    tower_row = session.scalar(select(Tower).where(Tower.code == tower))
    if not tower_row:
        raise NoSuchTower()

    q = select(Door).where(Door.tower_id == tower_row.id)
    if size:
        q = q.where(Door.size_class == size)
    doors = list(session.scalars(q))

    if state is not None:
        doors = [d for d in doors if door_state(d.current_parcel_id) == state]

    held_ids = [d.current_parcel_id for d in doors if d.current_parcel_id is not None]
    parcels = {p.id: p for p in session.scalars(select(Parcel).where(Parcel.id.in_(held_ids)))} if held_ids else {}

    items = []
    for d in doors:
        item = DoorListItem(no=d.no, size=d.size_class, state=door_state(d.current_parcel_id))
        if d.current_parcel_id is not None:
            parcel = parcels[d.current_parcel_id]
            item.parcel_id, item.dwell_seconds = parcel_public(parcel.id), _dwell(parcel, clock)
        items.append(item)

    free_count = sum(1 for item in items if item.state == "free")
    return DoorsOut(tower=tower, free=free_count, doors=items)


def get_door(session: Session, tower: str, no: str, clock: Clock) -> DoorOut:
    tower_row = session.scalar(select(Tower).where(Tower.code == tower))
    if not tower_row:
        raise NoSuchTower()

    door = session.scalar(select(Door).where(Door.tower_id == tower_row.id, Door.no == no))
    if not door:
        raise NoSuchDoor()

    out = DoorOut(no=door.no, size=door.size_class, state=door_state(door.current_parcel_id))
    if door.current_parcel_id is not None:
        parcel = session.get(Parcel, door.current_parcel_id)
        out.parcel_id, out.flat, out.dwell_seconds = parcel_public(parcel.id), parcel.flat, _dwell(parcel, clock)
    return out


def free_sizes(session: Session, tower_id: int) -> list[str]:
    rows = session.scalars(
        select(Door.size_class).where(Door.tower_id == tower_id, Door.current_parcel_id.is_(None)).distinct()
    )
    present = set(rows)
    return [s for s in SIZES if s in present]
