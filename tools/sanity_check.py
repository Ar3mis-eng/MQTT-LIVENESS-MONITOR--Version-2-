"""Quick sanity checks run during development (not part of the test suite)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mqtt.client import CLIENT_ID, PublishForbiddenError, ReadOnlyMqttClient

c = ReadOnlyMqttClient()
print("client id:", CLIENT_ID)
print("no publish method on wrapper:", not hasattr(c, "publish"))
try:
    c._client.publish("x", "y")
    print("FAIL: publish not blocked")
except PublishForbiddenError:
    print("publish blocked OK")

from app.config.config_manager import TopicConfigFile, load_profiles, load_settings

tcf = TopicConfigFile.load()
print("topics loaded:", len(tcf.topics), "errors:", tcf.validate())
print("profiles:", len(load_profiles()))
print("settings:", load_settings())
