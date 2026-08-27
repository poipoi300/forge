Couple more things I need. First, drafts — I want to be able to mark a post as a draft in the front matter, and have it show up when I'm running serve so I can preview it, but never get included when I actually run build. Right now half-finished posts leak into the deployed site and it's embarrassing.

Second, scheduling. I'd like to set a post's date to something in the future and have it just not appear in the build output until that date actually arrives. I deploy via a cron job that runs build every night, so the idea is I can write a post today, backdate... well, future-date it to next Monday, and it'll quietly show up on its own once Monday's build runs, without me touching anything.

Also could you add an RSS feed? Just the usual thing, list of recent posts with title/link/date. Obviously it should respect the same rules as everything else — no drafts in it, and no future posts until their date's actually passed.
