# Job Queue

I run a handful of services that shell out to slow background tasks — video transcodes, report generation, that kind of thing. Right now everything is either blocking a request thread or run through a janky cron script, and it's a mess. I want a small self-hosted job queue service in Go.

Basic idea: a client enqueues a job over HTTP with some payload (whatever the job needs, could be a file path, could be JSON params), a pool of workers pulls jobs off the queue and runs them, and I can query a job's status later (queued, running, done, failed, whatever). It needs to survive restarts — if the process or the box reboots, jobs that were queued or in flight shouldn't just vanish.

Single node is totally fine for now, I'm not trying to build something distributed. I don't want to bring in Redis or RabbitMQ or anything like that — too much operational overhead for what's basically a task list with workers. Would rather it just run as one Go binary with maybe a local database file for persistence. Keep the HTTP API simple, just enough to enqueue and check status.
