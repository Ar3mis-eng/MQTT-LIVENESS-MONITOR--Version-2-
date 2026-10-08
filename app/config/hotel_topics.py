"""Authoritative read-only topic registry for the hotel kitchen system."""
from __future__ import annotations

from .models import TopicClass, TopicConfig

EX_ROOT = "prion-clabz/aeon/kitch01/exhaust-system/main"
FA_ROOT = "prion-clabz/aeon/kitch01/fresh-air-system/main"

READBACKS = {
    f"{EX_ROOT}/panel/cmd/system-run": (f"{EX_ROOT}/panel/state/system-run",),
    f"{EX_ROOT}/fan-select/cmd/force-rotate": (f"{EX_ROOT}/fan-select/state/active-fan",),
    f"{EX_ROOT}/fan-select/cmd/mode": (f"{EX_ROOT}/fan-select/state/mode",),
    f"{EX_ROOT}/fan-select/cmd/rotation-interval-hours": (f"{EX_ROOT}/fan-select/state/rotation-interval-hours",),
    f"{EX_ROOT}/fan-select/cmd/normal-start-fan": (f"{EX_ROOT}/fan-select/state/normal-start-fan",),
    f"{EX_ROOT}/fan-select/cmd/manual-fan": (f"{EX_ROOT}/fan-select/state/manual-fan",),
    f"{EX_ROOT}/VFD-EX/cmd/normal-speed-preset": (f"{EX_ROOT}/VFD-EX/state/normal-speed-preset",),
    f"{EX_ROOT}/VFD-EX/cmd/manual-override-enable": (f"{EX_ROOT}/VFD-EX/state/manual-override-active",),
    f"{EX_ROOT}/VFD-EX/cmd/run": (f"{EX_ROOT}/VFD-EX/state/run-status",),
    f"{EX_ROOT}/VFD-EX/cmd/speed-ref": (f"{EX_ROOT}/VFD-EX/state/speed-ref-active",),
    f"{EX_ROOT}/VFD-EX/cmd/pid-override-enable": (f"{EX_ROOT}/VFD-EX/state/pid-override-active",),
    f"{FA_ROOT}/VFD-FA/cmd/manual-override-enable": (f"{FA_ROOT}/VFD-FA/state/manual-override-active",),
    f"{FA_ROOT}/VFD-FA/cmd/run": (f"{FA_ROOT}/VFD-FA/state/run-status",),
    f"{FA_ROOT}/VFD-FA/cmd/speed-set": (f"{FA_ROOT}/VFD-FA/state/speed-ref",),
    f"{EX_ROOT}/panel/alarm/comms-loss/cmd/ack": (f"{EX_ROOT}/panel/alarm/comms-loss",),
    f"{EX_ROOT}/EF-01/alarm/vfd-fault/cmd/ack": (f"{EX_ROOT}/EF-01/alarm/vfd-fault",),
    f"{EX_ROOT}/EF-02/alarm/vfd-fault/cmd/ack": (f"{EX_ROOT}/EF-02/alarm/vfd-fault",),
    f"{FA_ROOT}/FAF-01/alarm/vfd-fault/cmd/ack": (f"{FA_ROOT}/FAF-01/alarm/vfd-fault",),
    f"{EX_ROOT}/fan-select/alarm/interlock-fault/cmd/ack": (f"{EX_ROOT}/fan-select/alarm/interlock-fault",),
    f"{EX_ROOT}/dampers/cmd/position": (
        f"{EX_ROOT}/MD-EX-01/state/position",
        f"{FA_ROOT}/MD-FA-01/state/position",
    ),
}


def _topic(
    root: str,
    path: str,
    entity: str,
    label: str,
    kind: str,
    purpose: str,
    *,
    topic_class: TopicClass = TopicClass.ON_CHANGE,
    period_s: float | None = None,
    tier: int = 2,
    unit: str = "",
    retained: bool | None = None,
) -> TopicConfig:
    return TopicConfig(
        topic=f"{root}/{path}",
        short_name=label,
        purpose=purpose,
        entity=entity,
        topic_class=topic_class,
        period_s=period_s,
        tier=tier,
        if_silent="No recent update; inspect the broker and source device.",
        kind=kind,
        unit=unit,
        readback_topics=READBACKS.get(f"{root}/{path}", ()),
        monitor_only=True,
        publish_allowed=False,
        retained_expected=retained,
    )


def build_hotel_topics() -> list[TopicConfig]:
    """Return the official topics only; undefined/disabled diagnostics are excluded."""
    topics: list[TopicConfig] = []

    fixed = [
        (EX_ROOT, "panel/state/connection", "PLC", "PLC Connection", "CONNECTION", "Retained PLC ONLINE/OFFLINE state with last-will.", TopicClass.CONNECTION, None, 1, "", True),
        (EX_ROOT, "panel/state/plc-heartbeat", "PLC", "PLC Heartbeat", "HEARTBEAT", "PLC counter; verify that successive values increase.", TopicClass.HEARTBEAT, 2, 1, "", False),
        (EX_ROOT, "panel/state/system-run", "PLC", "System Run", "STATE", "System run-state readback for panel/cmd/system-run.", TopicClass.ON_CHANGE, None, 1, "", None),
        (EX_ROOT, "panel/state/comm-ok", "PLC", "Communication Status", "DIAGNOSTIC", "Communication status and optional reason/detail/devices.", TopicClass.ON_CHANGE, None, 1, "", None),
        (EX_ROOT, "panel/alarm/comms-loss", "PLC", "Communication Loss", "ALARM", "Communication-loss alarm readback.", TopicClass.ON_CHANGE, None, 1, "", None),
        (EX_ROOT, "main-power/state/estop-status", "E-Stop", "E-Stop Status", "STATE", "Critical emergency-stop status.", TopicClass.ON_CHANGE, None, 1, "", None),
        (EX_ROOT, "main-power/alarm/estop-tripped", "E-Stop", "E-Stop Alarm", "ALARM", "Emergency-stop trip alarm; no acknowledgement is sent.", TopicClass.ON_CHANGE, None, 1, "", None),
        (EX_ROOT, "fan-select/state/active-fan", "Fan Select", "Active Fan", "STATE", "Currently selected exhaust fan.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "fan-select/state/hmi-control-allowed", "Fan Select", "HMI Control Allowed", "STATE", "Whether HMI control is permitted.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "fan-select/state/hmi-control-reason", "Fan Select", "HMI Control Reason", "STATE", "Reason for the current HMI control state.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "fan-select/state/rotation-status", "Fan Select", "Rotation Status", "STATE", "Fan-rotation sequence status.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "fan-select/state/rotation-remaining-sec", "Fan Select", "Rotation Remaining", "STATE", "Remaining rotation time.", TopicClass.ON_CHANGE, None, 2, "s", None),
        (EX_ROOT, "fan-select/state/rotation-interval-hours", "Fan Select", "Rotation Interval", "STATE", "Configured fan-rotation interval.", TopicClass.ON_CHANGE, None, 2, "h", None),
        (EX_ROOT, "fan-select/state/mode", "Fan Select", "Fan Select Mode", "STATE", "Automatic or manual fan-selection mode.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "fan-select/state/normal-start-fan", "Fan Select", "Normal Start Fan", "STATE", "Fan selected for normal starts.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "fan-select/state/manual-fan", "Fan Select", "Manual Fan", "STATE", "Fan selected in manual mode.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "fan-select/alarm/interlock-fault", "Fan Select", "Interlock Fault", "ALARM", "Fan-selection interlock alarm.", TopicClass.ON_CHANGE, None, 1, "", None),
        (EX_ROOT, "VFD-EX/state/run-status", "VFD-EX", "Exhaust VFD Run", "STATE", "Exhaust VFD run-status readback.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "VFD-EX/state/speed-confirm", "VFD-EX", "Speed Confirmation", "STATE", "Speed command confirmation and optional target_hz/how.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "VFD-EX/state/speed-ref-active", "VFD-EX", "Active Speed Reference", "STATE", "Active exhaust VFD speed reference.", TopicClass.ON_CHANGE, None, 2, "%", None),
        (EX_ROOT, "VFD-EX/state/normal-speed-preset", "VFD-EX", "Normal Speed Preset", "STATE", "Current normal-speed preset.", TopicClass.ON_CHANGE, None, 2, "%", None),
        (EX_ROOT, "VFD-EX/state/manual-override-active", "VFD-EX", "Manual Override", "STATE", "Exhaust VFD manual override readback.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "VFD-EX/state/pid-override-active", "VFD-EX", "PID Override", "STATE", "Exhaust VFD PID override readback.", TopicClass.ON_CHANGE, None, 2, "", None),
        (EX_ROOT, "VFD-EX/telemetry/speed-actual", "VFD-EX", "Exhaust VFD Speed", "TELEMETRY", "Actual exhaust VFD speed from RS-485.", TopicClass.ON_CHANGE, None, 3, "Hz", None),
        (EX_ROOT, "VFD-EX/telemetry/current", "VFD-EX", "Exhaust VFD Current", "TELEMETRY", "Measured exhaust VFD current.", TopicClass.ON_CHANGE, None, 3, "A", None),
        (EX_ROOT, "VFD-EX/alarm/fault-code", "VFD-EX", "Exhaust VFD Fault", "ALARM", "Exhaust VFD fault code; NONE indicates no fault.", TopicClass.ON_CHANGE, None, 1, "", None),
        (FA_ROOT, "VFD-FA/state/run-status", "VFD-FA", "Fresh-Air VFD Run", "STATE", "Fresh-air VFD run-status readback.", TopicClass.ON_CHANGE, None, 2, "", None),
        (FA_ROOT, "VFD-FA/state/speed-confirm", "VFD-FA", "FA Speed Confirmation", "STATE", "Fresh-air VFD speed command confirmation.", TopicClass.ON_CHANGE, None, 2, "", None),
        (FA_ROOT, "VFD-FA/state/speed-ref", "VFD-FA", "FA Speed Reference", "STATE", "Fresh-air VFD speed reference.", TopicClass.ON_CHANGE, None, 2, "Hz", None),
        (FA_ROOT, "VFD-FA/state/speed-source", "VFD-FA", "FA Speed Source", "STATE", "Fresh-air VFD speed-reference source.", TopicClass.ON_CHANGE, None, 2, "", None),
        (FA_ROOT, "VFD-FA/state/manual-override-active", "VFD-FA", "FA Manual Override", "STATE", "Fresh-air VFD manual override readback.", TopicClass.ON_CHANGE, None, 2, "", None),
        (FA_ROOT, "VFD-FA/telemetry/speed-actual", "VFD-FA", "Fresh-Air VFD Speed", "TELEMETRY", "Actual fresh-air VFD speed.", TopicClass.ON_CHANGE, None, 3, "Hz", None),
        (FA_ROOT, "VFD-FA/telemetry/current", "VFD-FA", "Fresh-Air VFD Current", "TELEMETRY", "Measured fresh-air VFD current.", TopicClass.ON_CHANGE, None, 3, "A", None),
        (FA_ROOT, "VFD-FA/alarm/fault-code", "VFD-FA", "Fresh-Air VFD Fault", "ALARM", "Fresh-air VFD fault code; NONE indicates no fault.", TopicClass.ON_CHANGE, None, 1, "", None),
        (EX_ROOT, "MD-EX-01/state/position", "MD-EX-01", "Exhaust Damper Position", "STATE", "Retained damper position; quality becomes BAD after three failed reads.", TopicClass.ON_CHANGE, None, 2, "", True),
        (FA_ROOT, "MD-FA-01/state/position", "MD-FA-01", "Fresh-Air Damper Position", "STATE", "Retained damper position; quality becomes BAD after three failed reads.", TopicClass.ON_CHANGE, None, 2, "", True),
        (EX_ROOT, "AFS-01/telemetry/wind-speed-ms", "AFS-01", "Wind Speed", "TELEMETRY", "Airflow station wind speed.", TopicClass.PERIODIC, 2, 3, "m/s", None),
        (EX_ROOT, "AFS-01/telemetry/wind-speed-percent", "AFS-01", "Wind Speed Percent", "TELEMETRY", "Airflow station wind-speed percentage.", TopicClass.PERIODIC, 2, 3, "%", None),
        (EX_ROOT, "crowpanel/state/connection", "CrowPanel", "CrowPanel Connection", "CONNECTION", "Retained CrowPanel ONLINE/OFFLINE state with last-will.", TopicClass.CONNECTION, None, 2, "", True),
        (EX_ROOT, "crowpanel/state/heartbeat", "CrowPanel", "CrowPanel Heartbeat", "HEARTBEAT", "CrowPanel counter; verify that successive values increase.", TopicClass.HEARTBEAT, 2, 2, "", False),
    ]
    for root, path, entity, label, kind, purpose, cls, period, tier, unit, retained in fixed:
        topics.append(_topic(root, path, entity, label, kind, purpose, topic_class=cls,
                             period_s=period, tier=tier, unit=unit, retained=retained))

    for fan in ("EF-01", "EF-02"):
        for tail, label, kind, tier, purpose in (
            ("state/hoa", "HOA", "STATE", 2, "Hand-off-auto selector state."),
            ("state/run-status", "Run Status", "STATE", 2, "Contactor run feedback."),
            ("state/duty-standby", "Duty / Standby", "STATE", 2, "Duty or standby assignment."),
            ("state/bypass-active", "Bypass Active", "STATE", 2, "VFD bypass state."),
            ("state/control-mode", "Control Mode", "STATE", 2, "Current fan control mode."),
            ("alarm/vfd-fault", "VFD Fault", "ALARM", 1, "Fan VFD fault alarm."),
        ):
            topics.append(_topic(EX_ROOT, f"{fan}/{tail}", fan, f"{fan} {label}", kind,
                                 purpose, tier=tier))
    for path, label, kind, purpose, unit in (
        ("state/hoa", "HOA", "STATE", "Hand-off-auto selector state.", ""),
        ("state/control-mode", "Control Mode", "STATE", "Fresh-air fan control mode.", ""),
        ("state/run-status", "Run Status", "STATE", "Fresh-air fan contactor feedback.", ""),
        ("state/bypass-active", "Bypass Active", "STATE", "Fresh-air fan bypass state.", ""),
        ("alarm/vfd-fault", "VFD Fault", "ALARM", "Fresh-air fan VFD fault alarm.", ""),
    ):
        topics.append(_topic(FA_ROOT, f"FAF-01/{path}", "FAF-01", f"FAF-01 {label}",
                             kind, purpose, tier=1 if kind == "ALARM" else 2, unit=unit))

    commands = [
        (EX_ROOT, "panel/cmd/system-run", "PLC"),
        (EX_ROOT, "fan-select/cmd/force-rotate", "Fan Select"),
        (EX_ROOT, "fan-select/cmd/mode", "Fan Select"),
        (EX_ROOT, "fan-select/cmd/rotation-interval-hours", "Fan Select"),
        (EX_ROOT, "fan-select/cmd/normal-start-fan", "Fan Select"),
        (EX_ROOT, "fan-select/cmd/manual-fan", "Fan Select"),
        (EX_ROOT, "VFD-EX/cmd/normal-speed-preset", "VFD-EX"),
        (EX_ROOT, "VFD-EX/cmd/manual-override-enable", "VFD-EX"),
        (EX_ROOT, "VFD-EX/cmd/run", "VFD-EX"),
        (EX_ROOT, "VFD-EX/cmd/speed-ref", "VFD-EX"),
        (EX_ROOT, "VFD-EX/cmd/pid-override-enable", "VFD-EX"),
        (FA_ROOT, "VFD-FA/cmd/manual-override-enable", "VFD-FA"),
        (FA_ROOT, "VFD-FA/cmd/run", "VFD-FA"),
        (FA_ROOT, "VFD-FA/cmd/speed-set", "VFD-FA"),
        (EX_ROOT, "panel/alarm/comms-loss/cmd/ack", "PLC"),
        (EX_ROOT, "EF-01/alarm/vfd-fault/cmd/ack", "EF-01"),
        (EX_ROOT, "EF-02/alarm/vfd-fault/cmd/ack", "EF-02"),
        (FA_ROOT, "FAF-01/alarm/vfd-fault/cmd/ack", "FAF-01"),
        (EX_ROOT, "fan-select/alarm/interlock-fault/cmd/ack", "Fan Select"),
        (EX_ROOT, "dampers/cmd/position", "Dampers"),
        (EX_ROOT, "panel/cmd/clock-set", "PLC"),
    ]
    for root, path, entity in commands:
        topics.append(_topic(root, path, entity, path.rsplit("/", 1)[-1],
                             "COMMAND", "Observed HMI command; monitoring only.",
                             topic_class=TopicClass.COMMAND, tier=4))

    return topics
