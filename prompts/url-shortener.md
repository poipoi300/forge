# URL Shortener

I want a small self-hosted URL shortener written in Go. Basic idea: I POST a long URL to it, I get back a short code, and then hitting that short code in a browser redirects to the original URL.

Keep it simple, single binary, no external services. SQLite or even a flat file for storage is totally fine, whatever's easiest to ship. I'll be running this on a cheap VPS so I don't want a database server to manage.

Short codes can be random, doesn't need to be pretty, just short enough to paste places (6-ish characters is fine). Would like a tiny JSON API for creating links, and then plain GET requests do the redirect. No auth for now, it's just me using it.

If you want to throw in a minimal HTML page for pasting a URL in a browser that's a nice bonus but not required. Mostly I just want something I can `go build` and run.
