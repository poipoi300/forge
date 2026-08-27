Next thing I want out of this: gradual rollouts instead of just flipping a flag fully on or off. Like, turn a flag on for 10% of users first, watch for a bit, then bump it to 50%, then 100% once we're confident.

The important part is that a given user needs to stay on the same side consistently. If someone's in the 10% getting the new thing, they shouldn't randomly flip back to the old behavior on their next request, and when we bump the rollout to 50% the people who were already in shouldn't get kicked out — we just want to grow the group, not reshuffle it.

Also need a way to force certain accounts on regardless of the percentage, mainly for our own test accounts and a couple of beta customers who want early access no matter what the rollout number says. Whatever the API looks like for evaluating a flag, it's probably going to need to know who's asking now, not just which flag.

Let me know how you want to model the percentage and the identity piece.
