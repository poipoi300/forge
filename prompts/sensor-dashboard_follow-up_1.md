# Backlog uploads from flaky sensors

Noticed something annoying: a couple of the sensors are on the edge of my WiFi range and drop out pretty often. When they reconnect they dump a backlog of everything they buffered while offline, all in one go, so I get a burst of readings that are actually from 20 minutes ago arriving all at once. Sometimes they even resend a few readings that already made it through before the drop, I think because the ESP32 isn't sure what actually got acked.

Can you make sure the dashboard handles this gracefully? The charts should end up looking correct either way, no duplicate points, and any gap should get filled in properly once the backlog comes in rather than just showing a hole forever. The "current value" shown for a room is the part I care about most though. Right now I bet a late-arriving backlog reading could show up as the "latest" temperature even though it's actually old, and that would be pretty confusing to look at on the dashboard.
