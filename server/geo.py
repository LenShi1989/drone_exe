"""大圓距離、方位角與航線估算 / GeoJSON 快照。"""
from __future__ import annotations

import math

from .enums import WaypointAction

EARTH_RADIUS_M = 6_371_000.0
ROUTE_CRUISE_SPEED_MPS = 9.0
ROUTE_AVG_POWER_W = 380.0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(d_lon))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def interpolate(lat1: float, lon1: float, lat2: float, lon2: float, ratio: float) -> tuple[float, float]:
    """沿兩點連線線性內插 (短距離下誤差可忽略)。"""
    ratio = min(1.0, max(0.0, ratio))
    return lat1 + (lat2 - lat1) * ratio, lon1 + (lon2 - lon1) * ratio


def recalculate_route(route) -> None:
    """依航點重算總距離、預估分鐘與預估耗電。"""
    wps = sorted(route.waypoints, key=lambda w: w.sequence)
    distance = sum(distance_m(a.latitude, a.longitude, b.latitude, b.longitude) for a, b in zip(wps, wps[1:]))
    seconds = distance / ROUTE_CRUISE_SPEED_MPS + sum(w.hover_seconds for w in wps)
    route.total_distance_m = round(distance, 1)
    route.estimated_minutes = max(1, math.ceil(seconds / 60))
    route.estimated_energy_wh = round(seconds / 3600 * ROUTE_AVG_POWER_W, 2)


def route_geojson(route) -> dict:
    """航線快照:一條 LineString + 每個航點一個 Point (欄位與原版相同)。"""
    wps = sorted(route.waypoints, key=lambda w: w.sequence)
    features: list[dict] = [{
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[w.longitude, w.latitude] for w in wps]},
        "properties": {"kind": "path"},
    }]
    for w in wps:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [w.longitude, w.latitude]},
            "properties": {
                "kind": "waypoint",
                "sequence": w.sequence,
                "altitudeM": w.altitude_m,
                "action": WaypointAction(w.action).name,
                "hoverSeconds": w.hover_seconds,
                "mapPointId": w.map_point_id,
            },
        })
    return {
        "type": "FeatureCollection",
        "properties": {
            "routeId": route.id,
            "name": route.name,
            "version": route.version,
            "totalDistanceM": route.total_distance_m,
            "estimatedMinutes": route.estimated_minutes,
            "estimatedEnergyWh": route.estimated_energy_wh,
        },
        "features": features,
    }
