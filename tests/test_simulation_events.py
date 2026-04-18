"""Tests for simulation topic registration and event publisher."""
from platform_shared.topics import topics_for_tenant

def test_simulation_events_topic_name():
    t = topics_for_tenant("t1")
    assert t.simulation_events == "cpm.t1.simulation.events"

def test_simulation_events_in_all_topics():
    t = topics_for_tenant("t1")
    assert t.simulation_events in t.all_topics()

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'api'))
from consumers.topic_resolver import resolve_topics

def test_simulation_events_topic_in_resolver():
    topics = resolve_topics(["t1"])
    assert "cpm.t1.simulation.events" in topics
