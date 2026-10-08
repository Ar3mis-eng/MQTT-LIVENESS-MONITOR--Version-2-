# MQTT Topic Liveness Monitor

A passive PySide6 desktop application for monitoring the hotel kitchen
exhaust and fresh-air MQTT system. The default registry contains the
professor-provided EX/FA topics; the application is read-only and does
not publish to a broker.

## Features

- **Monitor tab**: tier-sorted real-topic table with value, quality,
  liveness, age, expected interval, retained indicator, group filters,
  device summary, and live terminal.
- **Topics tab**: edit every topics.json field, load/save/save-as,
  add/remove, search, plus **Discover mode** (subscribe `#`, guess class,
  operator corrects, save to data/topics.json).
- **Settings tab**: broker profiles (CRUD, masked password, Test
  Connection), monitoring thresholds, raw-capture toggle, Tier-1 sound.
- **Liveness engine**: class-specific rules (no generic timeout).
- **States**: ALIVE / STALE / DEAD / BAD QUALITY / NEVER SEEN.
- **Auto-reconnect** with backoff, resubscribe, logging.
- **Tests** (21, no broker) + **local simulator** (fake_broker.py).

## Layout

```text
main.py | requirements.txt | .gitignore | README.md
data/topics.json data/profiles.example.json data/logs/
app/config/ app/mqtt/ app/monitoring/ app/logging/ app/gui/
tools/fake_broker.py tools/run_tests.py tools/sanity_check.py
tests/test_monitor.py test_classifiers.py test_discovery.py test_topic_config.py
```

## Install (Windows)

```bat
cd /d "D:\MQTT LIVENESS MONITOR"
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bat
.venv\Scripts\python main.py
```

## Broker profiles

The built-in first profile is **Hotel Kitchen MQTT**
(`192.168.50.11:1883`) with no username or password. It can be edited
and saved in Settings; additional profiles remain supported.

Settings tab -> Name/Host/Port/Username/Password -> Save Profile.
Stored ONLY in data/profiles.json (git-ignored), masked in GUI, never
logged, never in topics.json. Select profile -> Connect. Header shows
profile, host:port, state, laptop IP, msg/s.

## Discover mode

Topics tab -> Start Discover (subscribes `#`, records first/last seen,
count, retain flag, sample payload, non-retained intervals). Correct the
guessed Class/Tier, then Save Discovered -> topics.json (merges new).

## topics.json

Primary config, indented JSON, NO credentials. Fields: topic,
short_name, purpose, entity, class, period_s, tier, if_silent,
sample_value, first_seen, kind, unit, readback_topics, retained flag,
monitor_only, and publish_allowed. The old demo registry is replaced
with the official list on first load. Only documented heartbeat and AFS
intervals are configured; unspecified intervals remain unset.

Normal monitoring subscribes to the two full system roots:
`prion-clabz/aeon/kitch01/exhaust-system/main/#` and
`prion-clabz/aeon/kitch01/fresh-air-system/main/#`. Each known topic is
still represented individually in the registry. Discover mode
temporarily adds `#` monitoring and marks unregistered topics as new;
it never replaces the official list automatically.


## Liveness rules (per class)

- **connection**: live ONLINE + quality GOOD = ALIVE; OFFLINE = DEAD
  (even retained OFFLINE). Retained ONLINE is shown as STALE until a
  live connection update verifies it.
- **heartbeat** (default period 2 s): ALIVE only if fresh within
  2.5x period AND counter increasing; stuck/backwards/reset = STALE
  (never ALIVE on timing alone); overdue past 5x = DEAD.
- **periodic**: ALIVE within 3x period AND quality GOOD; BAD quality =
  BAD QUALITY; overdue = STALE then DEAD (6x).
- **on_change**: age alone does not expire a live event-driven value;
  BAD quality is distinct, while retained snapshots remain STALE until
  a live update arrives.
- **command**: event-driven; last-seen shown, never STALE/DEAD.

## Tiers and sorting

1 Critical - 2 High - 3 Medium - 4 Low. Table sorts by tier, then
severity DEAD > STALE > BAD QUALITY > NEVER SEEN > ALIVE, then topic.

## Retained messages

`message.retain` is stored per topic and displayed as RETAINED. Freshness
uses payload `ts` when present (retained snapshots judged by content age,
not arrival). Retained arrivals are excluded from interval stats.

## Testing WITHOUT the plant broker

```bat
mosquitto -p 1883 -v
.venv\Scripts\python tools\fake_broker.py --scenario demo
.venv\Scripts\python tools\fake_broker.py --scenario offline-retained
.venv\Scripts\python tools\run_tests.py
```

Arc: start fakes -> ALIVE; stop -> STALE -> DEAD (Tier 1 on top);
restart -> ALIVE; retained OFFLINE -> DEAD. Fakes REFUSE plant host
192.168.50.11 unless explicitly overridden.

## Verify the app never publishes

1. `ReadOnlyMqttClient` has no `publish` attribute
   (`tools/sanity_check.py` asserts this + client id `ojt-g1-monitor`).
2. No `.publish(` calls outside the simulator and the forbidden-stub.
3. Runtime: sniff `#` on the test broker while operating the app;
   confirm the monitor client only subscribes, never publishes.

## Troubleshooting

- Missing/corrupt topics.json: app seeds the official topic registry.
  The built-in broker profile remains available if profiles.json is
  missing or corrupt.
- Auth failure / unreachable broker: ERROR state with detail, backoff
  reconnect, no crash. Bad payloads logged and skipped.
- GUI stays responsive: MQTT on its own thread into a bounded queue; GUI
  drains at ~10 Hz; terminal capped at 5000 lines.

## Known limitations / next steps

- History tab + CSV export, raw capture file, .exe packaging are
  optional/stubbed (toggles exist for raw capture + sound).
- Consider per-tier sound + tray alerts, and retained-vs-live age polish.
