# Feature flag service

My team is tired of doing a full deploy every time we want to turn something on or off. We're a small team (4 devs) running a handful of Go services, and I want to build a self-hosted feature flag service to fix this.

Basic idea: a service that stores boolean flags, exposes an HTTP API our apps can poll to get current flag values, and has some kind of minimal UI or CLI where we can flip a flag on or off. Needs real persistence so flags survive a restart, not just in-memory.

Latency matters a lot here since this sits directly in the request path of our other services — every request potentially checks a flag, so evaluation needs to be fast, no slow round trips or heavy locking.

I don't need anything fancy for v1, just boolean on/off per flag, a way to list/create/update flags, and something a human can use to toggle them without touching a database directly. Go is our stack so let's build it in Go. Open to your take on storage choice and how the polling API should look.
