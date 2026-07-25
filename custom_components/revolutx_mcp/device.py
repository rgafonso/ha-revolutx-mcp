"""Shared DeviceInfo builder — one HA device per config entry (this integration
assumes a single Revolut X account per entry), used by both entity platforms.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Revolut X",
        manufacturer="Revolut",
        model="Revolut X MCP",
    )
