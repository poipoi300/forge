So this happened — someone on the team flipped the wrong flag in prod on a Friday afternoon and it took us way too long to even figure out who did it or when. We need better visibility here.

For every flag I want to be able to see a history of who changed it, what they changed, and when — basically an audit trail so next time this happens we can immediately see what happened instead of guessing. Doesn't need to be fancy, just needs to answer "who touched this and what did they do."

And building on that, I want a one-click revert. If a flag was in some state at, say, 2pm yesterday, I want to be able to pick that point in time and roll the flag back to exactly how it was configured then, without having to manually reconstruct the old settings by hand. That would've saved us a bad hour on Friday.

Curious how you'd expose this in the UI, doesn't need to be complicated, just needs to actually work when someone's panicking.
