"""Tests for simulation topic registration and event publisher."""
from platform_shared.topics import topics_for_tenant

def test_simulation_events_topic_name():
    t = topics_for_tenant("t1")
    assert t.simulation_events == "cpm.t1.simulation.events"

def test_simulation_events_in_all_topics():
    t = topics_for_tenant("t1")
    assert t.simulation_events in t.all_topics()
